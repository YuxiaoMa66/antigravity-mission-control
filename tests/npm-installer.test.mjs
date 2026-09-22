import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, lstatSync, mkdirSync, mkdtempSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('.', import.meta.url)), '..');
const cli = resolve(root, 'npm/cli.mjs');
const python3 = spawnSync('which', ['python3'], { encoding: 'utf8' }).stdout.trim();
const fakeAgy = resolve(root, 'tests/fake_agy.py');

function run(args, env = {}) {
  return spawnSync(process.execPath, [cli, ...args], {
    cwd: root,
    env: { ...process.env, NO_COLOR: '1', ...env },
    encoding: 'utf8',
  });
}

test('help presents the product and command surface', () => {
  const result = run(['help']);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /ANTIGRAVITY MISSION CONTROL/);
  assert.match(result.stdout, /install/);
  assert.match(result.stdout, /uninstall/);
  assert.match(result.stdout, /--install-agy/);
});

test('AGY installation is a separate explicit non-interactive choice', () => {
  const home = mkdtempSync(resolve(tmpdir(), 'agy-mc-npm-no-agy-'));
  const result = run(['install', '--yes', '--host', 'codex', '--source', root], {
    HOME: home,
    PATH: dirname(process.execPath),
  });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /--install-agy/);
});

test('AGY install dry-run names the official source without executing it', () => {
  const home = mkdtempSync(resolve(tmpdir(), 'agy-mc-npm-agy-dry-'));
  const bin = resolve(home, 'bin');
  mkdirSync(bin);
  symlinkSync(python3, resolve(bin, 'python3'));
  const result = run(['install', '--dry-run', '--install-agy', '--host', 'codex', '--lang', 'en', '--source', root], { HOME: home, PATH: bin });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /https:\/\/antigravity\.google\/cli\/install\.sh/);
});

test('status is read-only and reports missing managed components', () => {
  const home = mkdtempSync(resolve(tmpdir(), 'agy-mc-npm-status-'));
  const result = run(['status', '--lang', 'en'], { HOME: home });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /not installed/);
});

test('dry-run shows exact bilingual installation targets without writes', () => {
  const home = mkdtempSync(resolve(tmpdir(), 'agy-mc-npm-dry-'));
  const result = run(['install', '--dry-run', '--host', 'codex', '--lang', 'zh', '--source', root], { HOME: home });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /预演模式/);
  assert.match(result.stdout, new RegExp(home.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
});

test('managed paths cannot escape HOME through an existing symlink', () => {
  const home = mkdtempSync(resolve(tmpdir(), 'agy-mc-npm-link-home-'));
  const outside = mkdtempSync(resolve(tmpdir(), 'agy-mc-npm-link-outside-'));
  mkdirSync(resolve(home, '.local'));
  symlinkSync(outside, resolve(home, '.local/share'));
  const result = run(['status'], { HOME: home });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /escapes HOME through a symlink/);
});

test('install is idempotent when the managed Skill already exists', () => {
  const home = mkdtempSync(resolve(tmpdir(), 'agy-mc-npm-idempotent-'));
  const bin = resolve(home, 'bin');
  const target = resolve(home, '.codex/skills/antigravity-mission-control');
  mkdirSync(bin, { recursive: true });
  mkdirSync(target, { recursive: true });
  symlinkSync(fakeAgy, resolve(bin, 'agy'));
  writeFileSync(resolve(target, '.agy-mc-install.json'), JSON.stringify({ schema: 'agy-mc-skill-install.v1', version: '0.1.0a2' }));

  const result = run(['install', '--yes', '--lang', 'en', '--source', root], {
    HOME: home,
    PATH: `${bin}:${process.env.PATH}`,
  });

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Updated/);
  assert.equal(lstatSync(resolve(home, '.local/bin/agy-mc')).isSymbolicLink(), true);
});

test('unmanaged Skill collision fails before creating the Python runtime', () => {
  const home = mkdtempSync(resolve(tmpdir(), 'agy-mc-npm-unmanaged-'));
  const bin = resolve(home, 'bin');
  const target = resolve(home, '.codex/skills/antigravity-mission-control');
  mkdirSync(bin, { recursive: true });
  mkdirSync(target, { recursive: true });
  symlinkSync(fakeAgy, resolve(bin, 'agy'));

  const result = run(['install', '--yes', '--lang', 'en', '--source', root], {
    HOME: home,
    PATH: `${bin}:${process.env.PATH}`,
  });

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /not managed by agy-mc/);
  assert.equal(existsSync(resolve(home, '.local/share/antigravity-mission-control/venv')), false);
});

test('auto host detection installs to Claude when only ~/.claude exists', () => {
  const home = mkdtempSync(resolve(tmpdir(), 'agy-mc-npm-claude-'));
  const bin = resolve(home, 'bin');
  mkdirSync(bin, { recursive: true });
  mkdirSync(resolve(home, '.claude'));
  symlinkSync(fakeAgy, resolve(bin, 'agy'));

  const result = run(['install', '--yes', '--lang', 'en', '--source', root], { HOME: home, PATH: `${bin}:${process.env.PATH}` });

  assert.equal(result.status, 0, result.stderr);
  const skill = resolve(home, '.claude/skills/antigravity-mission-control');
  assert.equal(existsSync(resolve(skill, 'SKILL.md')), true);
  assert.equal(existsSync(resolve(skill, 'agents')), false);
  assert.equal(existsSync(resolve(home, '.codex')), false);
});

test('all shows both host targets in the plan and no host detected is an error', () => {
  const home = mkdtempSync(resolve(tmpdir(), 'agy-mc-npm-hosts-'));
  const dry = run(['install', '--dry-run', '--host', 'all', '--lang', 'en', '--source', root], { HOME: home });
  assert.equal(dry.status, 0, dry.stderr);
  assert.match(dry.stdout, /\.codex\/skills\/antigravity-mission-control/);
  assert.match(dry.stdout, /\.claude\/skills\/antigravity-mission-control/);
  const none = run(['install', '--dry-run', '--source', root], { HOME: home });
  assert.notEqual(none.status, 0);
  assert.match(none.stderr, /--host codex\|claude/);
});

test('uninstall still removes the runtime when no managed Skill is found', () => {
  const home = mkdtempSync(resolve(tmpdir(), 'agy-mc-npm-uninstall-runtime-'));
  const data = resolve(home, '.local/share/antigravity-mission-control');
  mkdirSync(resolve(data, 'venv'), { recursive: true });

  const result = run(['uninstall', '--yes', '--lang', 'en'], { HOME: home });

  assert.equal(result.status, 0, result.stderr);
  assert.equal(existsSync(data), false);
});

test('status is not blocked by an unrelated host config symlinked outside HOME', () => {
  const home = mkdtempSync(resolve(tmpdir(), 'agy-mc-npm-status-link-'));
  const outside = mkdtempSync(resolve(tmpdir(), 'agy-mc-npm-status-outside-'));
  symlinkSync(outside, resolve(home, '.claude'));

  const result = run(['status', '--lang', 'en'], { HOME: home });

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Skill target \(codex\)/);
});

test('uninstall with an unmanaged Skill target changes nothing without --force', () => {
  const home = mkdtempSync(resolve(tmpdir(), 'agy-mc-npm-uninstall-unmanaged-'));
  const data = resolve(home, '.local/share/antigravity-mission-control');
  const runtime = resolve(data, 'venv/bin/agy-mc');
  mkdirSync(dirname(runtime), { recursive: true });
  writeFileSync(runtime, `#!/bin/sh\nexec "${python3}" "${root}/antigravity_mission_control/cli.py" "$@"\n`, { mode: 0o755 });
  const managed = resolve(home, '.codex/skills/antigravity-mission-control');
  const unmanaged = resolve(home, '.claude/skills/antigravity-mission-control');
  mkdirSync(managed, { recursive: true });
  writeFileSync(resolve(managed, '.agy-mc-install.json'), '{"version": "0.0.0"}\n');
  mkdirSync(unmanaged, { recursive: true });
  writeFileSync(resolve(unmanaged, 'SKILL.md'), 'someone else\n');

  const result = run(['uninstall', '--yes', '--host', 'all', '--lang', 'en'], { HOME: home });

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /not managed by agy-mc/);
  assert.equal(existsSync(managed), true);
  assert.equal(existsSync(unmanaged), true);
  assert.equal(existsSync(runtime), true);

  const forced = run(['uninstall', '--yes', '--host', 'all', '--force', '--lang', 'en'], { HOME: home });

  assert.equal(forced.status, 0, forced.stderr);
  assert.equal(existsSync(managed), false);
  assert.equal(existsSync(unmanaged), false);
  assert.equal(existsSync(data), false);
});
