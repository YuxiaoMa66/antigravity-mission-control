import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('.', import.meta.url)), '..');
const cli = resolve(root, 'npm/cli.mjs');

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
});

test('status is read-only and reports missing managed components', () => {
  const home = mkdtempSync(resolve(tmpdir(), 'agy-mc-npm-status-'));
  const result = run(['status', '--lang', 'en'], { HOME: home });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /not installed/);
});

test('dry-run shows exact bilingual installation targets without writes', () => {
  const home = mkdtempSync(resolve(tmpdir(), 'agy-mc-npm-dry-'));
  const result = run(['install', '--dry-run', '--lang', 'zh', '--source', root], { HOME: home });
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
