import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from antigravity_mission_control import cli

ROOT = Path(__file__).resolve().parents[1]


class PolicyWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.prompt = self.root / 'prompt.txt'
        self.prompt.write_text('Make the approved bounded change.')
        settings = self.root / 'settings.json'
        settings.write_text(json.dumps({'trustedWorkspaces': [str(self.workspace) + os.sep]}))
        self.env = {**os.environ, 'AGY_MC_BIN': str(ROOT / 'tests/fake_agy.py'),
                    'AGY_MC_STATE_ROOT': str(self.root / 'state'),
                    'AGY_MC_JOB_ROOT': str(self.root / 'state/jobs'),
                    'AGY_MC_SETTINGS_PATH': str(settings)}

    def call(self, *args, env=None):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/agy_delegate.py'), *args],
                              env=env or self.env, text=True, capture_output=True, timeout=40)

    def approval(self, *extra):
        return self.call('approve', '--strategy', 'A', '--role', 'implementer',
                         '--model', 'gemini-3.7-flash-high', '--cwd', str(self.workspace),
                         '--prompt-file', str(self.prompt), '--mode', 'accept-edits',
                         '--confirmed', *extra)

    def run_job(self, approval, *, parent=None, env=None):
        path = json.loads(approval.stdout)['approval_file']
        if parent:
            args = ['continue', parent, '--prompt-file', str(self.prompt), '--approval-file', path]
        else:
            args = ['run', '--strategy', 'A', '--role', 'implementer', '--model',
                    'gemini-3.7-flash-high', '--cwd', str(self.workspace), '--mode',
                    'accept-edits', '--prompt-file', str(self.prompt), '--approval-file', path]
        started = self.call(*args, '--background', '--timeout-seconds', '10', env=env)
        self.assertEqual(started.returncode, 0, started.stderr)
        job_id = json.loads(started.stdout)['job_id']
        result = self.call('wait', job_id, '--timeout', '15s')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return job_id, json.loads(result.stdout)

    def git(self, *args):
        result = subprocess.run(['git', *args], cwd=self.workspace, capture_output=True, check=True)
        return result.stdout

    def init_repo(self):
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fake Test')
        self.git('config', 'user.email', 'fake@example.invalid')
        (self.workspace / 'user.txt').write_text('original\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'baseline')

    def test_strict_requires_assertion_balanced_does_not_bypass_other_approval(self):
        denied = self.approval()
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('three-rosters-presented', denied.stderr)
        strict = self.approval('--three-rosters-presented')
        self.assertEqual(strict.returncode, 0, strict.stderr)
        balanced = self.approval('--policy', 'balanced')
        self.assertEqual(balanced.returncode, 0, balanced.stderr)
        payload = json.loads(Path(json.loads(balanced.stdout)['approval_file']).read_text())
        self.assertFalse(payload['policy']['require_three_rosters'])
        denied = self.approval('--policy', 'balanced', '--permission-profile', 'unrestricted')
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('separate confirmation', denied.stderr)

    def test_correction_chain_survives_followups_and_stops_at_limit(self):
        parent, result = self.run_job(self.approval('--three-rosters-presented'))
        self.assertEqual(result['correction_round'], 0)
        for expected in (1, 2):
            approval = self.approval('--correction-of', parent, '--conversation', 'fake-conversation')
            self.assertEqual(approval.returncode, 0, approval.stderr)
            parent, result = self.run_job(approval, parent=parent)
            self.assertEqual(result['correction_round'], expected)
        followup = self.approval('--follow-up-of', parent, '--conversation', 'fake-conversation')
        self.assertEqual(followup.returncode, 0, followup.stderr)
        parent, result = self.run_job(followup, parent=parent)
        self.assertEqual(result['correction_round'], 2)
        denied = self.approval('--correction-of', parent, '--conversation', 'fake-conversation')
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('Correction limit', denied.stderr)
        changed = self.approval('--policy', 'balanced', '--follow-up-of', parent,
                                '--conversation', 'fake-conversation')
        self.assertNotEqual(changed.returncode, 0)
        self.assertIn('effective policy', changed.stderr)

    def test_continuation_cannot_silently_reset_lineage(self):
        parent, _ = self.run_job(self.approval('--policy', 'balanced'))
        root = self.approval('--policy', 'balanced', '--conversation', 'fake-conversation')
        path = json.loads(root.stdout)['approval_file']
        denied = self.call('continue', parent, '--prompt-file', str(self.prompt), '--approval-file', path)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('preserve', denied.stderr)

    def test_background_evidence_detects_same_status_content_change_and_untracked(self):
        self.init_repo()
        (self.workspace / 'user.txt').write_text('user existing edit\n')
        (self.workspace / 'user-new.txt').write_text('user untracked\n')
        _, result = self.run_job(self.approval('--policy', 'balanced'),
                                env={**self.env, 'FAKE_AGY_EDIT': '1', 'FAKE_AGY_WARNING': '1'})
        self.assertEqual(result['status'], 'done_with_warnings')
        self.assertEqual(result['acceptance'], 'not_evaluated')
        evidence = Path(result['evidence_path'])
        before = json.loads((evidence / 'before.json').read_text())
        after = json.loads((evidence / 'after.json').read_text())
        delta = json.loads((evidence / 'delta.json').read_text())
        self.assertEqual(before['paths']['user.txt']['status'], after['paths']['user.txt']['status'])
        self.assertIn('user.txt', delta['changed_paths'])
        self.assertIn('worker-new.txt', delta['changed_paths'])
        self.assertNotIn('user-new.txt', delta['changed_paths'])
        request = json.loads(result['payload']['response'])['message']['content']
        self.assertIn('user-new.txt', request)
        self.assertEqual((self.workspace / 'user-new.txt').read_text(), 'user untracked\n')
        self.assertEqual(stat.S_IMODE((evidence / 'before.json').stat().st_mode), 0o600)
        self.assertNotIn(str(self.workspace), str(evidence))

    def test_legacy_policy_alias_is_hidden_and_normalized(self):
        help_output = self.call('approve', '--help')
        self.assertNotIn('strict-yuxiao', help_output.stdout)
        result = self.call('policy', 'strict-yuxiao')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['policy']['name'], 'strict')
        result = self.approval('--policy', 'strict-yuxiao', '--three-rosters-presented')
        path = Path(json.loads(result.stdout)['approval_file'])
        payload = json.loads(path.read_text())
        self.assertEqual(payload['policy']['name'], 'strict')
        # Model a genuine pre-rename signed manifest without changing other fields.
        payload['policy']['name'] = 'strict-yuxiao'
        key = (self.root / 'state/approval.key').read_bytes()
        payload['signature'] = cli.approval_signature(payload, key)
        path.write_text(json.dumps(payload))
        _, completed = self.run_job(result)
        self.assertEqual(completed['policy']['name'], 'strict')

    def test_quota_and_policy_do_not_require_model_discovery_or_roster(self):
        env = {**self.env, 'FAKE_AGY_MODELS_ERROR': '1'}
        quota = self.call('usage', '--format', 'json', env=env)
        self.assertEqual(quota.returncode, 0, quota.stderr)
        policy = self.call('policy', 'balanced', env={**env, 'AGY_MC_BIN': '/missing-agy'})
        self.assertEqual(policy.returncode, 0, policy.stderr)
        self.assertFalse(json.loads(policy.stdout)['policy']['require_three_rosters'])

    def test_non_git_and_oversize_fingerprints_are_not_clean_claims(self):
        snapshot = cli.workspace_snapshot(self.workspace)
        self.assertEqual(snapshot['status'], 'unknown')
        self.init_repo()
        (self.workspace / 'large.bin').write_bytes(b'x' * (8 * 1024 * 1024 + 1))
        snapshot = cli.workspace_snapshot(self.workspace)
        self.assertEqual(snapshot['status'], 'partial')
        self.assertIn('skipped', snapshot['paths']['large.bin']['fingerprint'])

    def test_renames_newlines_staged_changes_and_external_diff_not_executed(self):
        self.init_repo()
        self.git('mv', 'user.txt', 'renamed\nfile.txt')
        (self.workspace / 'renamed\nfile.txt').write_text('staged and unstaged\n')
        marker = self.root / 'external-diff-ran'
        script = self.root / 'external-diff'
        script.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n')
        script.chmod(0o700)
        self.git('config', 'diff.external', str(script))
        snapshot = cli.workspace_snapshot(self.workspace)
        self.assertEqual(snapshot['status'], 'ok', snapshot)
        self.assertIn('renamed\nfile.txt', snapshot['paths'])
        self.assertEqual(snapshot['paths']['renamed\nfile.txt']['original_path'], 'user.txt')
        self.assertIsNotNone(snapshot['staged_diff_sha256'])
        self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
