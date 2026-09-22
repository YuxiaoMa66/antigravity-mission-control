"""Policies and signed, prompt-bound approval manifests."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import secrets
import uuid
from pathlib import Path

from .common import STATE_ROOT, atomic_write_json, atomic_write_private_bytes, sha256_text
from .jobstore import read_job, refresh_job
from .routing import available_models, is_non_high_gemini, select_model
from .workspace import canonical_workspace


APPROVAL_ROOT = STATE_ROOT / "approvals"


APPROVAL_KEY_PATH = STATE_ROOT / "approval.key"


def approval_key(create: bool = False) -> bytes:
    if APPROVAL_KEY_PATH.is_file():
        key = APPROVAL_KEY_PATH.read_bytes()
        if len(key) != 32:
            raise RuntimeError(f"Approval key is invalid: {APPROVAL_KEY_PATH}")
        return key
    if not create:
        raise RuntimeError("Approval key is missing; create a new approval manifest on this machine")
    key = secrets.token_bytes(32)
    atomic_write_private_bytes(APPROVAL_KEY_PATH, key)
    return key


def approval_signature(payload: dict, key: bytes) -> str:
    unsigned = {name: value for name, value in payload.items() if name != "signature"}
    encoded = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key, encoded, hashlib.sha256).hexdigest()


def load_approval(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Approval manifest does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Approval manifest is invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "agy-mc-approval.v1":
        raise RuntimeError(f"Unsupported approval manifest: {path}")
    signature = payload.get("signature")
    expected = approval_signature(payload, approval_key(create=False))
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
        raise RuntimeError("Approval manifest signature does not match this machine or its contents")
    try:
        expires_at = datetime.fromisoformat(str(payload["expires_at"]))
    except (KeyError, ValueError) as exc:
        raise RuntimeError("Approval manifest has an invalid expiration") from exc
    if expires_at.tzinfo is None or datetime.now(timezone.utc) >= expires_at.astimezone(timezone.utc):
        raise RuntimeError(f"Approval manifest expired at {payload.get('expires_at')}")
    return payload


POLICY_NAMES = ("strict", "balanced")


def canonical_policy_name(name: str) -> str:
    # Hidden migration alias; public commands and output use the generic name.
    return "strict" if name == "strict-yuxiao" else name


def normalized_policy(policy: dict) -> dict:
    return dict(policy, name=canonical_policy_name(policy["name"]))


def effective_policy(name: str = "strict") -> dict:
    name = canonical_policy_name(name)
    if name not in POLICY_NAMES:
        raise RuntimeError(f"Unknown policy: {name}")
    path = Path(__file__).with_name("skill_bundle") / "policies" / f"{name}.json"
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy.get("schema") != "agy-mc-policy.v1" or policy.get("name") != name:
        raise RuntimeError(f"Invalid policy: {path}")
    return policy


def cmd_policy(args: argparse.Namespace) -> int:
    print(json.dumps({"policy": effective_policy(args.name),
        "limits": "Confirmation flags are caller assertions, not proof of human approval. "
                  "Correction limits apply to recorded correction chains; legacy runs are uncounted."}, indent=2))
    return 0


def correction_context(job_id: str, policy: dict, is_correction: bool = True) -> tuple[dict, int]:
    job = refresh_job(read_job(job_id))
    if job.get("status") in {"starting", "running", "canceling"}:
        raise RuntimeError("Wait for the parent job before approving a correction")
    if not job.get("policy"):
        raise RuntimeError("Legacy job has no policy lineage; establish a new approved task")
    if normalized_policy(job["policy"]) != normalized_policy(policy):
        raise RuntimeError("A correction must retain its parent's effective policy")
    round_number = job.get("correction_round", 0) + int(is_correction)
    if round_number > policy["max_correction_rounds"]:
        raise RuntimeError("Correction limit reached; diagnose the failure before approving a new task")
    return job, round_number


def cmd_approve(args: argparse.Namespace) -> int:
    if not args.confirmed:
        raise RuntimeError("Creating an approval manifest requires --confirmed after explicit user confirmation")
    if args.expires_minutes < 1 or args.expires_minutes > 1440:
        raise RuntimeError("--expires-minutes must be between 1 and 1440")
    if args.permission_profile == "unrestricted" and not args.unrestricted_confirmed:
        raise RuntimeError("Unrestricted approval requires separate confirmation and --unrestricted-confirmed")
    if args.unrestricted_confirmed and args.permission_profile != "unrestricted":
        raise RuntimeError("--unrestricted-confirmed requires --permission-profile unrestricted")

    cwd = canonical_workspace(args.cwd)
    prompt_path = Path(args.prompt_file).expanduser().resolve()
    if not prompt_path.is_file():
        raise RuntimeError(f"Prompt file does not exist: {prompt_path}")
    prompt_text = prompt_path.read_text(encoding="utf-8")
    models = available_models()
    model_ids = {model["id"] for model in models}
    if args.model not in model_ids:
        raise RuntimeError(f"Requested model is unavailable: {args.model}")
    if args.strategy == "C":
        required_model = select_model(args.role, models, strategy="C")
        if args.model != required_model:
            raise RuntimeError(f"Strategy C requires {required_model}; got {args.model}")
    allow_non_high = bool(args.non_high_gemini_confirmed)
    if is_non_high_gemini(args.model) and not allow_non_high:
        raise RuntimeError("A Gemini medium/low approval requires --non-high-gemini-confirmed")

    policy = effective_policy(getattr(args, "policy", "strict"))
    correction_id = getattr(args, "correction_of", None)
    follow_up_id = getattr(args, "follow_up_of", None)
    if correction_id and follow_up_id:
        raise RuntimeError("Choose --correction-of or --follow-up-of, not both")
    parent_id = correction_id or follow_up_id
    correction_round = 0
    if parent_id:
        parent, correction_round = correction_context(parent_id, policy, bool(correction_id))
        expected = {"strategy": args.strategy, "role": args.role, "model": args.model,
                    "cwd": str(cwd), "mode": args.mode,
                    "permission_profile": args.permission_profile}
        if any(parent.get(key) != value for key, value in expected.items()):
            raise RuntimeError("Correction changes the approved roster or permission profile")
        if not parent.get("conversation_id") or args.conversation != parent["conversation_id"]:
            raise RuntimeError("Correction requires the exact parent conversation")
    elif policy["require_three_rosters"] and not getattr(args, "three_rosters_presented", False):
        raise RuntimeError("strict requires --three-rosters-presented after presenting A/B/C")

    created = datetime.now(timezone.utc)
    approval_id = f"approval-{created.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    payload = {
        "schema": "agy-mc-approval.v1",
        "approval_id": approval_id,
        "policy": policy,
        "correction_of": correction_id,
        "follow_up_of": follow_up_id,
        "correction_round": correction_round,
        "created_at": created.isoformat(),
        "expires_at": (created + timedelta(minutes=args.expires_minutes)).isoformat(),
        "strategy": args.strategy,
        "role": args.role,
        "model": args.model,
        "cwd": str(cwd),
        "prompt_sha256": sha256_text(prompt_text),
        "mode": args.mode,
        "permission_profile": args.permission_profile,
        "allow_non_high_gemini": allow_non_high,
        "conversation": args.conversation,
    }
    payload["signature"] = approval_signature(payload, approval_key(create=True))
    if args.output:
        output = Path(args.output).expanduser().resolve()
    else:
        APPROVAL_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(APPROVAL_ROOT, 0o700)
        output = APPROVAL_ROOT / f"{approval_id}.json"
    atomic_write_json(output, payload)
    print(
        json.dumps(
            {
                "schema": "agy-mc-approval-created.v1",
                "status": "created",
                "approval_id": approval_id,
                "approval_file": str(output),
                "expires_at": payload["expires_at"],
                "binding": {
                    "strategy": args.strategy,
                    "role": args.role,
                    "model": args.model,
                    "cwd": str(cwd),
                    "prompt_sha256": payload["prompt_sha256"],
                    "mode": args.mode,
                    "permission_profile": args.permission_profile,
                    "policy": policy,
                    "correction_round": correction_round,
                    "parent_job_id": parent_id,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def validate_approval_binding(args: argparse.Namespace, cwd: Path, prompt_text: str) -> dict | None:
    raw_path = getattr(args, "approval_file", None)
    if not raw_path:
        return None
    path = Path(raw_path).expanduser().resolve()
    approval = load_approval(path)
    expected = {
        "strategy": args.strategy,
        "role": args.role,
        "model": args.model,
        "cwd": str(cwd),
        "prompt_sha256": sha256_text(prompt_text),
        "mode": args.mode,
        "permission_profile": "unrestricted" if args.unrestricted else "standard",
        "conversation": getattr(args, "conversation", None),
    }
    mismatches = [name for name, value in expected.items() if approval.get(name) != value]
    if mismatches:
        raise RuntimeError("Approval manifest does not match this run: " + ", ".join(mismatches))
    if approval.get("policy"):
        if normalized_policy(approval["policy"]) != effective_policy(approval["policy"]["name"]):
            raise RuntimeError("Effective policy changed; create a new approval")
        approval = dict(approval, policy=normalized_policy(approval["policy"]))
        parent_id = approval.get("correction_of") or approval.get("follow_up_of")
        if parent_id:
            _, round_number = correction_context(parent_id, approval["policy"], bool(approval.get("correction_of")))
            if approval.get("correction_round") != round_number:
                raise RuntimeError("Invalid correction lineage")
    return approval
