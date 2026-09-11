import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
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
        missing = self.call('continue', parent, '--prompt-file', str(self.prompt), '--roster-approved')
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('requires --approval-file', missing.stderr)

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

    def test_malformed_rename_snapshot_becomes_incomplete_evidence(self):
        responses = [
            subprocess.CompletedProcess([], 0, stdout=(str(self.workspace) + '\n').encode(), stderr=b''),
            subprocess.CompletedProcess([], 0, stdout=(b'a' * 40) + b'\n', stderr=b''),
            subprocess.CompletedProcess([], 0, stdout=b'R  renamed-without-origin\0', stderr=b''),
            subprocess.CompletedProcess([], 0, stdout=b'', stderr=b''),
            subprocess.CompletedProcess([], 0, stdout=b'', stderr=b''),
        ]
        with mock.patch.object(cli.subprocess, 'run', side_effect=responses):
            snapshot = cli.workspace_snapshot(self.workspace)
        self.assertEqual(snapshot['status'], 'partial')
        self.assertIn('Malformed rename/copy status entry', snapshot['limitations'][0])

    def test_scoped_approval_validation(self):
        denied = self.approval('--policy', 'balanced', '--forbidden-path', 'secret.txt')
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('--forbidden-path requires at least one --allowed-path', denied.stderr)

        denied = self.approval('--policy', 'balanced', '--required-check', 'test')
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('--required-check requires at least one --allowed-path', denied.stderr)

        denied = self.approval('--policy', 'balanced', '--base-commit', '0' * 40)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('--base-commit requires at least one --allowed-path', denied.stderr)

        denied = self.call('approve', '--strategy', 'A', '--role', 'implementer',
                           '--model', 'gemini-3.7-flash-high', '--cwd', str(self.workspace),
                           '--prompt-file', str(self.prompt), '--mode', 'plan',
                           '--confirmed', '--policy', 'balanced', '--allowed-path', 'user.txt')
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('accept-edits mode', denied.stderr)

        for invalid_rule in ('', '/abs/path', 'back\\slash', 'dup//sep', 'foo*bar', 'foo/../bar', '.', '..', './'):
            denied = self.approval('--policy', 'balanced', '--allowed-path', invalid_rule)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn('Invalid path rule', denied.stderr)

        # Scoped approve on non-git workspace
        denied = self.approval('--policy', 'balanced', '--allowed-path', 'user.txt')
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('Git repository', denied.stderr)

        self.init_repo()
        nested = self.workspace / 'nested'
        nested.mkdir()
        nested_approval = self.call(
            'approve', '--strategy', 'A', '--role', 'implementer',
            '--model', 'gemini-3.7-flash-high', '--cwd', str(nested),
            '--prompt-file', str(self.prompt), '--mode', 'accept-edits',
            '--confirmed', '--policy', 'balanced', '--allowed-path', 'nested/'
        )
        self.assertNotEqual(nested_approval.returncode, 0)
        self.assertIn('Git repository root', nested_approval.stderr)

        # Invalid base-commit format
        denied = self.approval('--policy', 'balanced', '--allowed-path', 'user.txt', '--base-commit', 'not-a-hash')
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('40-hex', denied.stderr)

        # Base-commit mismatch
        denied = self.approval('--policy', 'balanced', '--allowed-path', 'user.txt', '--base-commit', '0' * 40)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('does not match current HEAD', denied.stderr)

        # Valid scoped approve
        head = self.git('rev-parse', 'HEAD').decode().strip()
        ok = self.approval('--policy', 'balanced', '--allowed-path', 'user.txt', '--base-commit', head)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        data = json.loads(ok.stdout)
        self.assertEqual(data['binding']['base_commit'], head)
        self.assertIn('preflight_sha256', data['binding'])
        self.assertEqual(data['binding']['allowed_paths'], ['user.txt'])
        self.assertIn('.git', data['binding']['forbidden_paths'])
        self.assertIn('.git/', data['binding']['forbidden_paths'])

    def test_required_checks_catalog_validation(self):
        self.init_repo()
        denied = self.approval('--policy', 'balanced', '--allowed-path', 'user.txt', '--required-check', 'lint')
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('checks file does not exist', denied.stderr)

        checks_dir = self.workspace / '.agy-mc'
        checks_dir.mkdir()
        checks_file = checks_dir / 'checks.json'

        checks_file.write_text('{not valid json')
        denied = self.approval('--policy', 'balanced', '--allowed-path', 'user.txt', '--required-check', 'lint')
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('invalid JSON', denied.stderr)

        checks_file.write_text(json.dumps({'schema': 'wrong-schema', 'checks': {}}))
        denied = self.approval('--policy', 'balanced', '--allowed-path', 'user.txt', '--required-check', 'lint')
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('Invalid required checks schema', denied.stderr)

        checks_file.write_text(json.dumps({'schema': 'agy-mc-checks.v1', 'checks': {'test': {'argv': []}}}))
        denied = self.approval('--policy', 'balanced', '--allowed-path', 'user.txt', '--required-check', 'test')
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('Invalid argv', denied.stderr)

        # Valid catalog: .agy-mc/checks.json is automatically forbidden
        checks_file.write_text(json.dumps({
            'schema': 'agy-mc-checks.v1',
            'checks': {
                'ok_check': {'argv': ['true'], 'timeout_seconds': 60}
            }
        }))
        ok = self.approval('--policy', 'balanced', '--allowed-path', 'user.txt', '--required-check', 'ok_check')
        self.assertEqual(ok.returncode, 0, ok.stderr)
        manifest = json.loads(Path(json.loads(ok.stdout)['approval_file']).read_text())
        self.assertIn('.agy-mc/checks.json', manifest['forbidden_paths'])
        self.assertEqual(manifest['required_checks'][0]['id'], 'ok_check')

    def test_scoped_preflight_drift_rejection(self):
        self.init_repo()
        app = self.approval('--policy', 'balanced', '--allowed-path', 'user.txt')
        self.assertEqual(app.returncode, 0, app.stderr)
        app_file = json.loads(app.stdout)['approval_file']

        # Commit drift
        self.git('commit', '--allow-empty', '-qm', 'drift commit')
        run = self.call('run', '--strategy', 'A', '--role', 'implementer', '--model', 'gemini-3.7-flash-high',
                        '--cwd', str(self.workspace), '--mode', 'accept-edits', '--prompt-file', str(self.prompt),
                        '--approval-file', app_file)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('Commit drift detected', run.stderr)

        # Dirty tracked content drift
        app2 = self.approval('--policy', 'balanced', '--allowed-path', 'user.txt')
        self.assertEqual(app2.returncode, 0, app2.stderr)
        app_file2 = json.loads(app2.stdout)['approval_file']
        (self.workspace / 'user.txt').write_text('dirty preflight content\n')
        run2 = self.call('run', '--strategy', 'A', '--role', 'implementer', '--model', 'gemini-3.7-flash-high',
                         '--cwd', str(self.workspace), '--mode', 'accept-edits', '--prompt-file', str(self.prompt),
                         '--approval-file', app_file2)
        self.assertNotEqual(run2.returncode, 0)
        self.assertIn('preflight digest mismatch', run2.stderr)

        # Untracked content drift
        self.git('checkout', 'HEAD', '--', 'user.txt')
        app3 = self.approval('--policy', 'balanced', '--allowed-path', 'user.txt')
        self.assertEqual(app3.returncode, 0, app3.stderr)
        app_file3 = json.loads(app3.stdout)['approval_file']
        (self.workspace / 'untracked_drift.txt').write_text('untracked\n')
        run3 = self.call('run', '--strategy', 'A', '--role', 'implementer', '--model', 'gemini-3.7-flash-high',
                         '--cwd', str(self.workspace), '--mode', 'accept-edits', '--prompt-file', str(self.prompt),
                         '--approval-file', app_file3)
        self.assertNotEqual(run3.returncode, 0)
        self.assertIn('preflight digest mismatch', run3.stderr)

    def test_scoped_enforcement_clean_scope_and_checks(self):
        self.init_repo()
        app = self.approval('--policy', 'balanced', '--allowed-path', 'user.txt')
        self.assertEqual(app.returncode, 0, app.stderr)
        app_file = json.loads(app.stdout)['approval_file']

        action = json.dumps({'write': [{'path': 'user.txt', 'content': 'clean edit\n'}]})
        run = self.call('run', '--strategy', 'A', '--role', 'implementer', '--model', 'gemini-3.7-flash-high',
                        '--cwd', str(self.workspace), '--mode', 'accept-edits', '--prompt-file', str(self.prompt),
                        '--approval-file', app_file,
                        env={**self.env, 'FAKE_AGY_CUSTOM_ACTION': action})
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('"status": "scope_passed"', run.stderr)
        self.assertIn('"acceptance": "not_evaluated"', run.stderr)

        # With passing required check
        checks_dir = self.workspace / '.agy-mc'
        checks_dir.mkdir(exist_ok=True)
        (checks_dir / 'checks.json').write_text(json.dumps({
            'schema': 'agy-mc-checks.v1',
            'checks': {
                'pass_check': {'argv': [sys.executable, '-c', 'import sys; sys.exit(0)'], 'timeout_seconds': 30}
            }
        }))
        self.git('add', '.')
        self.git('commit', '-qm', 'add checks')
        app_check = self.approval('--policy', 'balanced', '--allowed-path', 'user.txt', '--required-check', 'pass_check')
        self.assertEqual(app_check.returncode, 0, app_check.stderr)
        app_check_file = json.loads(app_check.stdout)['approval_file']

        run_check = self.call('run', '--strategy', 'A', '--role', 'implementer', '--model', 'gemini-3.7-flash-high',
                              '--cwd', str(self.workspace), '--mode', 'accept-edits', '--prompt-file', str(self.prompt),
                              '--approval-file', app_check_file,
                              env={**self.env, 'FAKE_AGY_CUSTOM_ACTION': action})
        self.assertEqual(run_check.returncode, 0, run_check.stderr)
        self.assertIn('"status": "passed"', run_check.stderr)

    def test_scoped_enforcement_violations_and_failures(self):
        self.init_repo()
        secret_dir = self.workspace / 'src' / 'secret-dir'
        secret_dir.mkdir(parents=True)
        (secret_dir / 'hidden.txt').write_text('hidden\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'add forbidden directory fixture')
        head_commit = self.git('rev-parse', 'HEAD').decode().strip()

        def run_scenario(action, allowed=('user.txt', 'src/'), forbidden=('src/secret.txt',), checks=()):
            self.git('reset', '--hard', head_commit)
            self.git('clean', '-fdx')
            args = ['--policy', 'balanced']
            for a in allowed:
                args.extend(['--allowed-path', a])
            for f in forbidden:
                args.extend(['--forbidden-path', f])
            for c in checks:
                args.extend(['--required-check', c])
            app = self.approval(*args)
            self.assertEqual(app.returncode, 0, app.stderr)
            app_file = json.loads(app.stdout)['approval_file']
            return self.call('run', '--strategy', 'A', '--role', 'implementer', '--model', 'gemini-3.7-flash-high',
                             '--cwd', str(self.workspace), '--mode', 'accept-edits', '--prompt-file', str(self.prompt),
                             '--approval-file', app_file,
                             env={**self.env, 'FAKE_AGY_CUSTOM_ACTION': json.dumps(action)})

        # Out-of-allowed path
        run_out = run_scenario({'write': [{'path': 'outside.txt', 'content': 'out\n'}]})
        self.assertEqual(run_out.returncode, 5, run_out.stderr)
        self.assertIn('"status": "scope_violation"', run_out.stderr)

        # Forbidden path
        run_forbid = run_scenario({'write': [{'path': 'src/secret.txt', 'content': 'leak\n'}]})
        self.assertEqual(run_forbid.returncode, 5, run_forbid.stderr)
        self.assertIn('"status": "scope_violation"', run_forbid.stderr)

        # Symlink escaping outside repo
        run_sym_out = run_scenario({'symlink': [{'link': 'src/escape.txt', 'target': '/etc/passwd'}]})
        self.assertEqual(run_sym_out.returncode, 5, run_sym_out.stderr)
        self.assertIn('"status": "scope_violation"', run_sym_out.stderr)

        # Symlink to forbidden file
        run_sym_forbid = run_scenario({'symlink': [{'link': 'src/link.txt', 'target': 'secret.txt'}]})
        self.assertEqual(run_sym_forbid.returncode, 5, run_sym_forbid.stderr)
        self.assertIn('"status": "scope_violation"', run_sym_forbid.stderr)

        # Symlink to the root of a forbidden directory
        run_sym_forbid_dir = run_scenario(
            {'symlink': [{'link': 'src/dir-link', 'target': 'secret-dir'}]},
            forbidden=('src/secret-dir/',),
        )
        self.assertEqual(run_sym_forbid_dir.returncode, 5, run_sym_forbid_dir.stderr)
        self.assertIn('"status": "scope_violation"', run_sym_forbid_dir.stderr)

        # Symlink to Git metadata is always forbidden by scoped approvals
        run_sym_git = run_scenario({'symlink': [{'link': 'src/git-link', 'target': '../.git'}]}, forbidden=())
        self.assertEqual(run_sym_git.returncode, 5, run_sym_git.stderr)
        self.assertIn('"status": "scope_violation"', run_sym_git.stderr)

        # Symlink loop / unresolvable target
        run_sym_loop = run_scenario({'symlink': [{'link': 'src/loop.txt', 'target': 'loop.txt'}]})
        self.assertEqual(run_sym_loop.returncode, 5, run_sym_loop.stderr)
        self.assertIn('"status": "scope_violation"', run_sym_loop.stderr)

        # HEAD changed during run
        run_head = run_scenario({'write': [{'path': 'user.txt', 'content': 'head change\n'}],
                                 'git_commit': 'illegal commit'})
        self.assertEqual(run_head.returncode, 5, run_head.stderr)
        self.assertIn('"status": "scope_violation"', run_head.stderr)

        # Provider failure with out-of-scope modification reports scope_violation with provider_exit_code
        action_prov_viol = {'write': [{'path': 'outside.txt', 'content': 'bad\n'}], 'exit_code': 3}
        run_prov_viol = run_scenario(action_prov_viol)
        self.assertEqual(run_prov_viol.returncode, 5, run_prov_viol.stderr)
        self.assertIn('"status": "scope_violation"', run_prov_viol.stderr)
        self.assertIn('"provider_exit_code": 3', run_prov_viol.stderr)

        # Provider failure with clean scope reports provider_error with provider exit code
        action_prov_clean = {'exit_code': 3}
        run_prov_clean = run_scenario(action_prov_clean)
        self.assertEqual(run_prov_clean.returncode, 3, run_prov_clean.stderr)
        self.assertIn('"status": "provider_error"', run_prov_clean.stderr)
        self.assertIn('"provider_exit_code": 3', run_prov_clean.stderr)

        # Setup checks in catalog
        self.git('reset', '--hard', head_commit)
        self.git('clean', '-fdx')
        checks_dir = self.workspace / '.agy-mc'
        checks_dir.mkdir(exist_ok=True)
        (checks_dir / 'checks.json').write_text(json.dumps({
            'schema': 'agy-mc-checks.v1',
            'checks': {
                'fail_check': {'argv': [sys.executable, '-c', 'import sys; sys.exit(2)'], 'timeout_seconds': 30},
                'missing_check': {'argv': ['nonexistent_binary_xyz_123'], 'timeout_seconds': 30},
                'timeout_check': {'argv': [sys.executable, '-c', 'import time; time.sleep(5)'], 'timeout_seconds': 1},
                'orphan_timeout_check': {
                    'argv': [
                        sys.executable,
                        '-c',
                        'import subprocess, sys, time; '
                        'subprocess.Popen([sys.executable, "-c", '
                        '"import time; from pathlib import Path; time.sleep(1.2); '
                        'Path(\\"orphan-after-timeout.txt\\").write_text(\\"bad\\\\n\\")"]); '
                        'time.sleep(5)',
                    ],
                    'timeout_seconds': 1,
                },
                'side_effect_fail': {
                    'argv': [sys.executable, '-c', 'from pathlib import Path; Path("side_effect_outside.txt").write_text("bad\\n"); import sys; sys.exit(2)'],
                    'timeout_seconds': 30,
                },
            }
        }))
        self.git('add', '.')
        self.git('commit', '-qm', 'add check catalog')
        checks_commit = self.git('rev-parse', 'HEAD').decode().strip()

        # Update head_commit for checks scenarios
        head_commit = checks_commit

        # Required check failing (scope clean)
        action_clean = {'write': [{'path': 'user.txt', 'content': 'clean\n'}]}
        run_fail = run_scenario(action_clean, checks=('fail_check',))
        self.assertEqual(run_fail.returncode, 5, run_fail.stderr)
        self.assertIn('"status": "check_failed"', run_fail.stderr)

        # Missing executable check
        run_missing = run_scenario(action_clean, checks=('missing_check',))
        self.assertEqual(run_missing.returncode, 5, run_missing.stderr)
        self.assertIn('"status": "check_failed"', run_missing.stderr)
        ev_match = re.search(r'"amc_evidence":\s*"([^"]+)"', run_missing.stderr)
        self.assertIsNotNone(ev_match)
        checks_data = json.loads((Path(ev_match.group(1)) / "checks.json").read_text(encoding='utf-8'))
        self.assertEqual(checks_data["checks"][0]["exit_code"], 127)

        # Timeout check
        run_timeout = run_scenario(action_clean, checks=('timeout_check',))
        self.assertEqual(run_timeout.returncode, 5, run_timeout.stderr)
        self.assertIn('"status": "check_failed"', run_timeout.stderr)
        ev_match_to = re.search(r'"amc_evidence":\s*"([^"]+)"', run_timeout.stderr)
        self.assertIsNotNone(ev_match_to)
        checks_data_to = json.loads((Path(ev_match_to.group(1)) / "checks.json").read_text(encoding='utf-8'))
        self.assertEqual(checks_data_to["checks"][0]["exit_code"], 124)
        self.assertTrue(checks_data_to["checks"][0]["timed_out"])

        # Timed-out checks terminate their whole process group, including descendants.
        run_orphan_timeout = run_scenario(action_clean, checks=('orphan_timeout_check',))
        self.assertEqual(run_orphan_timeout.returncode, 5, run_orphan_timeout.stderr)
        time.sleep(0.5)
        self.assertFalse((self.workspace / 'orphan-after-timeout.txt').exists())

        # Failed check that also creates an out-of-scope change reports scope_violation
        run_side_effect = run_scenario(action_clean, checks=('side_effect_fail',))
        self.assertEqual(run_side_effect.returncode, 5, run_side_effect.stderr)
        self.assertIn('"status": "scope_violation"', run_side_effect.stderr)
        self.assertIn('"failed_check": "side_effect_fail"', run_side_effect.stderr)

    def test_matches_path_rule_literal_backslash(self):
        from antigravity_mission_control.cli import matches_path_rule
        # On Unix, literal backslash in a filename must not match directory rules
        if os.name != 'nt':
            self.assertFalse(matches_path_rule("src\\secret.txt", "src/"))
            self.assertFalse(matches_path_rule("src\\secret.txt", "src/secret.txt"))
            self.assertTrue(matches_path_rule("src/file.txt", "src/"))
            self.assertTrue(matches_path_rule("src", "src/"))
            self.assertTrue(matches_path_rule("src/file.txt", "src/file.txt"))

    def test_required_checks_rejects_null_bytes(self):
        self.init_repo()
        checks_dir = self.workspace / '.agy-mc'
        checks_dir.mkdir(exist_ok=True)
        (checks_dir / 'checks.json').write_text(json.dumps({
            'schema': 'agy-mc-checks.v1',
            'checks': {
                'nul_check': {'argv': ['echo', 'hello\0world'], 'timeout_seconds': 30}
            }
        }))
        denied = self.approval('--policy', 'balanced', '--allowed-path', 'user.txt', '--required-check', 'nul_check')
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('null bytes', denied.stderr)

    def test_scope_lineage_inheritance_and_validation(self):
        self.init_repo()
        checks_dir = self.workspace / '.agy-mc'
        checks_dir.mkdir(exist_ok=True)
        (checks_dir / 'checks.json').write_text(json.dumps({
            'schema': 'agy-mc-checks.v1',
            'checks': {
                'ok_check': {'argv': ['true'], 'timeout_seconds': 60}
            }
        }))
        self.git('add', '.')
        self.git('commit', '-qm', 'add checks')

        # 1. Create a scoped background job
        # fake_agy returns conversation_id="fake-conversation"
        parent_conv = "fake-conversation"
        app = self.approval('--policy', 'balanced', '--allowed-path', 'user.txt',
                            '--required-check', 'ok_check', '--conversation', parent_conv)
        self.assertEqual(app.returncode, 0, app.stderr)
        app_file = json.loads(app.stdout)['approval_file']
        start = self.call('run', '--strategy', 'A', '--role', 'implementer', '--model', 'gemini-3.7-flash-high',
                          '--cwd', str(self.workspace), '--mode', 'accept-edits', '--prompt-file', str(self.prompt),
                          '--approval-file', app_file, '--background', '--conversation', parent_conv)
        self.assertEqual(start.returncode, 0, start.stderr)
        job_id = json.loads(start.stdout)['job_id']
        wait = self.call('wait', job_id, '--timeout', '60s')
        self.assertEqual(wait.returncode, 0, wait.stderr)

        # Verify job metadata contains scope and exact recorded conversation_id
        status = self.call('status', job_id)
        job_meta = json.loads(status.stdout)
        self.assertEqual(job_meta['conversation_id'], parent_conv)
        self.assertIn('scope', job_meta)
        self.assertEqual(job_meta['scope']['allowed_paths'], ['user.txt'])
        self.assertEqual(job_meta['scope']['required_checks'][0]['id'], 'ok_check')

        # 2. Correction approval inherits exact scope when flags omitted
        corr_inherit = self.approval('--policy', 'balanced', '--correction-of', job_id,
                                     '--conversation', parent_conv)
        self.assertEqual(corr_inherit.returncode, 0, corr_inherit.stderr)
        inherit_data = json.loads(corr_inherit.stdout)['binding']
        self.assertEqual(inherit_data['allowed_paths'], ['user.txt'])
        self.assertEqual(inherit_data['required_checks'][0]['id'], 'ok_check')

        # 3. Supplying matching flags succeeds
        corr_matching = self.approval('--policy', 'balanced', '--correction-of', job_id,
                                      '--conversation', parent_conv,
                                      '--allowed-path', 'user.txt', '--required-check', 'ok_check')
        self.assertEqual(corr_matching.returncode, 0, corr_matching.stderr)

        # 4. Attempting to widen or change scope fails
        widen = self.approval('--policy', 'balanced', '--correction-of', job_id,
                              '--conversation', parent_conv,
                              '--allowed-path', 'user.txt', '--allowed-path', 'other.txt')
        self.assertNotEqual(widen.returncode, 0)
        self.assertIn('Correction cannot widen or change', widen.stderr)

        # 5. Tampered job metadata scope is rejected against signed approval authority
        job_meta_file = self.root / 'state/jobs' / job_id / 'job.json'
        meta = json.loads(job_meta_file.read_text(encoding='utf-8'))
        meta['scope']['allowed_paths'].append('forged_dir/')
        job_meta_file.write_text(json.dumps(meta), encoding='utf-8')
        tampered_corr = self.approval('--policy', 'balanced', '--correction-of', job_id,
                                      '--conversation', parent_conv)
        self.assertNotEqual(tampered_corr.returncode, 0)
        self.assertIn('Parent job metadata scope does not match its signed approval manifest', tampered_corr.stderr)

        # 6. Create an unscoped background job
        self.git('reset', '--hard', 'HEAD')
        self.git('clean', '-fdx')
        unscoped_conv = "fake-conversation"
        app_unscoped = self.approval('--policy', 'balanced', '--conversation', unscoped_conv)
        self.assertEqual(app_unscoped.returncode, 0, app_unscoped.stderr)
        app_unscoped_file = json.loads(app_unscoped.stdout)['approval_file']
        start_unscoped = self.call('run', '--strategy', 'A', '--role', 'implementer', '--model', 'gemini-3.7-flash-high',
                                   '--cwd', str(self.workspace), '--mode', 'accept-edits', '--prompt-file', str(self.prompt),
                                   '--approval-file', app_unscoped_file, '--background', '--conversation', unscoped_conv)
        self.assertEqual(start_unscoped.returncode, 0, start_unscoped.stderr)
        unscoped_job_id = json.loads(start_unscoped.stdout)['job_id']
        self.call('wait', unscoped_job_id, '--timeout', '60s')

        # 7. Attempting to add scope to unscoped job fails
        add_scope = self.approval('--policy', 'balanced', '--correction-of', unscoped_job_id,
                                  '--conversation', unscoped_conv, '--allowed-path', 'user.txt')
        self.assertNotEqual(add_scope.returncode, 0)
        self.assertIn('Correction of an unscoped job cannot add scoped rules', add_scope.stderr)


if __name__ == '__main__':
    unittest.main()
