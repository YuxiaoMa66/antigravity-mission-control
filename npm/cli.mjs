#!/usr/bin/env node

import { spawnSync } from 'node:child_process';
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readlinkSync, realpathSync, renameSync, rmdirSync, symlinkSync, unlinkSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { basename, dirname, resolve, sep } from 'node:path';
import process from 'node:process';
import { createInterface } from 'node:readline/promises';
import { fileURLToPath } from 'node:url';

const VERSION = '0.1.0-alpha.3';
const PYTHON_VERSION = '0.1.0a3';
const REPOSITORY = 'https://github.com/YuxiaoMa66/antigravity-mission-control.git';
const DEFAULT_SOURCE = `git+${REPOSITORY}@v${PYTHON_VERSION}`;
const AGY_INSTALL_URL = 'https://antigravity.google/cli/install.sh';
const colorEnabled = process.stdout.isTTY && !process.env.NO_COLOR;

const c = {
  reset: colorEnabled ? '\u001b[0m' : '',
  violet: colorEnabled ? '\u001b[38;5;141m' : '',
  cyan: colorEnabled ? '\u001b[38;5;81m' : '',
  green: colorEnabled ? '\u001b[38;5;114m' : '',
  amber: colorEnabled ? '\u001b[38;5;221m' : '',
  muted: colorEnabled ? '\u001b[38;5;245m' : '',
  bold: colorEnabled ? '\u001b[1m' : '',
};

function parseArgs(argv) {
  const args = { command: 'help', lang: 'auto', yes: false, dryRun: false, force: false, installAgy: false, source: DEFAULT_SOURCE };
  const rest = [...argv];
  if (rest[0] && !rest[0].startsWith('-')) args.command = rest.shift();
  while (rest.length) {
    const flag = rest.shift();
    if (flag === '--yes' || flag === '-y') args.yes = true;
    else if (flag === '--dry-run') args.dryRun = true;
    else if (flag === '--force') args.force = true;
    else if (flag === '--install-agy') args.installAgy = true;
    else if (flag === '--lang') {
      if (!rest.length) throw new Error('--lang requires a value');
      args.lang = rest.shift();
    }
    else if (flag === '--source') {
      if (!rest.length) throw new Error('--source requires a value');
      args.source = rest.shift();
    }
    else if (flag === '--help' || flag === '-h') args.command = 'help';
    else if (flag === '--version' || flag === '-v') args.command = 'version';
    else throw new Error(`Unknown option: ${flag}`);
  }
  if (!['auto', 'en', 'zh'].includes(args.lang)) throw new Error('--lang must be auto, en, or zh');
  return args;
}

function language(requested) {
  if (requested !== 'auto') return requested;
  return /(^|[_.-])zh([_.-]|$)/i.test(process.env.LANG || '') ? 'zh' : 'en';
}

const messages = {
  en: {
    subtitle: 'Route / Guard / Verify', install: 'Install', update: 'Update', uninstall: 'Uninstall',
    status: 'Status', doctor: 'Doctor', target: 'Skill target', runtime: 'Managed runtime',
    source: 'Package source', confirm: 'Continue with these exact changes?', canceled: 'Canceled; nothing changed.',
    complete: 'Mission accomplished', missingPython: 'Python 3.10+ is required.', missingAgy: 'AGY was not found; install it before running workers.',
    pathWarning: 'Add this directory to PATH to call agy-mc directly', dryRun: 'Dry run — no files will change',
    installAgy: 'Official AGY installer', installAgyPrompt: 'AGY is missing. Install the official Antigravity CLI first?',
    installAgyRequired: 'AGY was not found. Install it first, or rerun with --install-agy to use Google’s official installer.',
    agyReady: 'AGY installed', agyLogin: 'First AGY setup: run `agy`, complete Google sign-in, then run `agy-mc doctor`.',
  },
  zh: {
    subtitle: '调度 / 守界 / 验收', install: '安装', update: '更新', uninstall: '卸载',
    status: '状态', doctor: '诊断', target: 'Skill 目标', runtime: '托管运行环境',
    source: '安装来源', confirm: '确认执行以上精确修改吗？', canceled: '已取消，未修改任何文件。',
    complete: '任务完成', missingPython: '需要 Python 3.10 或更高版本。', missingAgy: '未找到 AGY；运行 worker 前请先安装。',
    pathWarning: '请将此目录加入 PATH，以便直接调用 agy-mc', dryRun: '预演模式——不会修改文件',
    installAgy: 'AGY 官方安装器', installAgyPrompt: '没有检测到 AGY。先安装官方 Antigravity CLI 吗？',
    installAgyRequired: '没有检测到 AGY。请先安装，或增加 --install-agy 使用 Google 官方安装器。',
    agyReady: 'AGY 安装完成', agyLogin: '首次配置：运行 `agy` 完成 Google 登录，然后执行 `agy-mc doctor`。',
  },
};

function paths() {
  const home = resolve(process.env.HOME || homedir());
  const dataRoot = resolve(process.env.AGY_MC_INSTALL_ROOT || `${home}/.local/share/antigravity-mission-control`);
  const binRoot = resolve(process.env.AGY_MC_BIN_DIR || `${home}/.local/bin`);
  const skillTarget = resolve(process.env.AGY_MC_SKILL_TARGET || `${process.env.CODEX_HOME || `${home}/.codex`}/skills/antigravity-mission-control`);
  return { home, dataRoot, venv: `${dataRoot}/venv`, binRoot, shim: `${binRoot}/agy-mc`, skillTarget };
}

function assertSafePath(path, home) {
  const resolved = resolve(path);
  if (resolved === '/' || resolved === home || !resolved.startsWith(`${home}${sep}`)) {
    throw new Error(`Refusing unsafe managed path: ${resolved}`);
  }
  const realHome = realpathSync(home);
  let ancestor = resolved;
  const suffix = [];
  while (!lstatSafe(ancestor)) {
    suffix.unshift(basename(ancestor));
    const parent = dirname(ancestor);
    if (parent === ancestor) throw new Error(`Cannot resolve managed path: ${resolved}`);
    ancestor = parent;
  }
  const prospective = resolve(realpathSync(ancestor), ...suffix);
  if (prospective === realHome || !prospective.startsWith(`${realHome}${sep}`)) {
    throw new Error(`Refusing managed path that escapes HOME through a symlink: ${resolved}`);
  }
}

function banner() {
  console.log(`${c.violet}╭────────────────────────────────────────────────────────────╮${c.reset}`);
  console.log(`${c.violet}│${c.reset}  ${c.bold}ANTIGRAVITY MISSION CONTROL${c.reset}  ${c.cyan}◉${c.reset}  v${VERSION}             ${c.violet}│${c.reset}`);
  console.log(`${c.violet}│${c.reset}  ${c.muted}Route / Guard / Verify${c.reset}                                  ${c.violet}│${c.reset}`);
  console.log(`${c.violet}╰────────────────────────────────────────────────────────────╯${c.reset}`);
}

function row(icon, label, value, tone = c.cyan) {
  console.log(`  ${tone}${icon}${c.reset} ${c.bold}${label}${c.reset}`);
  console.log(`    ${c.muted}${value}${c.reset}`);
}

function commandExists(command, args = ['--version']) {
  const result = spawnSync(command, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
  return result.status === 0 ? (result.stdout || '').trim() : null;
}

function pythonCommand() {
  for (const candidate of ['python3', 'python']) {
    const output = commandExists(candidate, ['-c', 'import sys; print(".".join(map(str, sys.version_info[:3])))']);
    if (output) {
      const [major, minor] = output.split('.').map(Number);
      if (major > 3 || (major === 3 && minor >= 10)) return { command: candidate, version: output };
    }
  }
  return null;
}

function run(file, args, options = {}) {
  const result = spawnSync(file, args, { encoding: 'utf8', stdio: options.capture ? ['ignore', 'pipe', 'pipe'] : 'inherit', ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    const detail = options.capture ? (result.stderr || result.stdout || '').trim() : '';
    throw new Error(`${basename(file)} exited ${result.status}${detail ? `: ${detail}` : ''}`);
  }
  return result;
}

async function confirmChange(args, text) {
  if (args.dryRun || args.yes) return true;
  if (!process.stdin.isTTY) throw new Error('Non-interactive installation requires --yes');
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  const answer = await rl.question(`${c.amber}?${c.reset} ${text} [y/N] `);
  rl.close();
  return /^y(es)?$/i.test(answer.trim());
}

function managedAgyMc(p) {
  return process.platform === 'win32' ? `${p.venv}/Scripts/agy-mc.exe` : `${p.venv}/bin/agy-mc`;
}

function showPlan(args, p, msg) {
  banner();
  const action = msg[args.command] || args.command;
  row('◆', action, args.dryRun ? msg.dryRun : `v${VERSION}`, c.violet);
  row('◇', msg.target, p.skillTarget);
  row('◇', msg.runtime, p.venv);
  if (['install', 'update'].includes(args.command)) row('◇', msg.source, args.source);
  if (args.installAgy) row('◇', msg.installAgy, AGY_INSTALL_URL);
}

function managedShim(p) {
  const stat = lstatSafe(p.shim);
  if (!stat?.isSymbolicLink()) return false;
  try { return resolve(dirname(p.shim), readlinkSync(p.shim)) === resolve(managedAgyMc(p)); } catch { return false; }
}

function ensureShim(p, force) {
  mkdirSync(p.binRoot, { recursive: true, mode: 0o700 });
  if (lstatSafe(p.shim)) {
    if (managedShim(p)) unlinkSync(p.shim);
    else if (force) renameSync(p.shim, `${p.shim}.backup-${Date.now()}`);
    else throw new Error(`Refusing to replace unmanaged CLI path: ${p.shim}; inspect it or rerun with --force`);
  }
  symlinkSync(managedAgyMc(p), p.shim);
}

function lstatSafe(path) {
  try { return lstatSync(path); } catch { return null; }
}

function locateAgy(p) {
  const pathVersion = commandExists('agy');
  if (pathVersion) return { command: 'agy', version: pathVersion };
  const managedCandidate = `${p.home}/.local/bin/agy`;
  if (existsSync(managedCandidate)) {
    const version = commandExists(managedCandidate);
    if (version) {
      process.env.PATH = `${dirname(managedCandidate)}:${process.env.PATH || ''}`;
      return { command: managedCandidate, version };
    }
  }
  return null;
}

async function installOfficialAgy(p) {
  const response = await fetch(AGY_INSTALL_URL, { redirect: 'follow', signal: AbortSignal.timeout(30_000) });
  if (!response.ok) throw new Error(`Official AGY installer download failed: HTTP ${response.status}`);
  const finalUrl = new URL(response.url);
  if (finalUrl.protocol !== 'https:' || !['antigravity.google', 'www.antigravity.google'].includes(finalUrl.hostname)) {
    throw new Error(`Official AGY installer redirected to an unapproved host: ${finalUrl.hostname}`);
  }
  const payload = Buffer.from(await response.arrayBuffer());
  if (payload.length === 0 || payload.length > 2 * 1024 * 1024 || !payload.toString('utf8', 0, 2).startsWith('#!')) {
    throw new Error('Official AGY installer response failed safety checks');
  }
  const temporary = mkdtempSync(resolve(tmpdir(), 'agy-mc-agy-installer-'));
  const script = `${temporary}/install.sh`;
  try {
    writeFileSync(script, payload, { mode: 0o700 });
    run('bash', [script]);
  } finally {
    if (existsSync(script)) unlinkSync(script);
    rmdirSync(temporary);
  }
  const installed = locateAgy(p);
  if (!installed) throw new Error('The official installer finished, but `agy --version` is still unavailable');
  return installed;
}

function resolveSkillAction(args, p) {
  const targetExists = existsSync(p.skillTarget);
  const managedMarker = `${p.skillTarget}/.agy-mc-install.json`;
  if (args.command === 'update' && !targetExists) {
    throw new Error(`Skill is not installed: ${p.skillTarget}; use install`);
  }
  if (targetExists && !existsSync(managedMarker) && !args.force) {
    throw new Error(`Existing Skill is not managed by agy-mc: ${p.skillTarget}; inspect it or rerun with --force`);
  }
  if (args.command === 'install' && targetExists && existsSync(managedMarker)) return 'update';
  return args.command === 'install' ? 'install' : 'update';
}

async function installOrUpdate(args, p, msg) {
  let agy = locateAgy(p);
  if (agy) args.installAgy = false;
  if (!agy && !args.installAgy && !args.dryRun) {
    if (!args.yes && process.stdin.isTTY) {
      banner();
      row('!', 'AGY', msg.missingAgy, c.amber);
      args.installAgy = await confirmChange(args, msg.installAgyPrompt);
    }
    if (!args.installAgy) throw new Error(msg.installAgyRequired);
  }
  showPlan(args, p, msg);
  const python = pythonCommand();
  if (!python) throw new Error(msg.missingPython);
  row('✓', 'Python', `${python.command} ${python.version}`, c.green);
  row(agy ? '✓' : '!', 'AGY', agy?.version || msg.missingAgy, agy ? c.green : c.amber);
  if (!(await confirmChange(args, msg.confirm))) {
    console.log(msg.canceled);
    return;
  }
  if (args.dryRun) return;
  // Resolve target compatibility before installing AGY or mutating the managed
  // Python runtime. A pre-existing managed Skill makes `install` idempotent and
  // follows the recoverable update path; an unmanaged collision fails cleanly.
  const skillAction = resolveSkillAction(args, p);
  let installedAgy = false;
  if (!agy && args.installAgy) {
    agy = await installOfficialAgy(p);
    installedAgy = true;
    row('✓', msg.agyReady, agy.version, c.green);
  }
  mkdirSync(p.dataRoot, { recursive: true, mode: 0o700 });
  if (!existsSync(p.venv)) run(python.command, ['-m', 'venv', p.venv]);
  const venvPython = process.platform === 'win32' ? `${p.venv}/Scripts/python.exe` : `${p.venv}/bin/python`;
  run(venvPython, ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps', '--upgrade', '--force-reinstall', args.source]);
  const skillArgs = ['skill', skillAction, '--target', p.skillTarget, '--lang', args.lang, '--format', 'pretty'];
  if (args.force) skillArgs.push('--force');
  run(managedAgyMc(p), skillArgs);
  ensureShim(p, args.force);
  console.log(`\n${c.green}✓ ${msg.complete}${c.reset}`);
  if (!(process.env.PATH || '').split(':').includes(p.binRoot)) console.log(`${c.amber}! ${msg.pathWarning}: ${p.binRoot}${c.reset}`);
  if (installedAgy) console.log(`${c.amber}! ${msg.agyLogin}${c.reset}`);
}

function showStatus(p, msg) {
  banner();
  row(existsSync(managedAgyMc(p)) ? '✓' : '○', msg.runtime, existsSync(managedAgyMc(p)) ? managedAgyMc(p) : 'not installed', existsSync(managedAgyMc(p)) ? c.green : c.muted);
  row(existsSync(`${p.skillTarget}/SKILL.md`) ? '✓' : '○', msg.target, p.skillTarget, existsSync(`${p.skillTarget}/SKILL.md`) ? c.green : c.muted);
  const agy = commandExists('agy');
  row(agy ? '✓' : '!', 'AGY', agy || msg.missingAgy, agy ? c.green : c.amber);
}

async function uninstall(args, p, msg) {
  showPlan(args, p, msg);
  if (!(await confirmChange(args, msg.confirm))) {
    console.log(msg.canceled);
    return;
  }
  if (args.dryRun) return;
  const executable = managedAgyMc(p);
  if (existsSync(executable) && existsSync(p.skillTarget)) run(executable, ['skill', 'uninstall', '--target', p.skillTarget, '--lang', args.lang]);
  if (managedShim(p)) unlinkSync(p.shim);
  if (existsSync(p.dataRoot)) {
    const backup = `${p.dataRoot}.backup-${new Date().toISOString().replace(/[:.]/g, '-')}`;
    renameSync(p.dataRoot, backup);
    row('↪', 'Backup', backup, c.green);
  }
  console.log(`\n${c.green}✓ ${msg.complete}${c.reset}`);
}

function help() {
  banner();
  console.log(`\n${c.bold}Usage${c.reset}\n  npx antigravity-mission-control <command> [options]\n`);
  console.log(`${c.bold}Commands${c.reset}\n  install      Install the managed Python CLI and Codex Skill\n  update       Upgrade both layers and preserve a backup\n  status       Show AGY, runtime, and Skill status\n  doctor       Run the installed Mission Control doctor\n  uninstall    Recoverably remove managed files\n`);
  console.log(`${c.bold}Options${c.reset}\n  --lang auto|en|zh   Interface language\n  --source PATH|URL   Python package source\n  --install-agy       Install AGY from Google’s official installer when missing\n  --dry-run           Show exact targets without writing\n  --yes, -y           Confirm non-interactively\n  --force             Back up and replace an unmanaged Skill target\n  --version, -v       Print version\n`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.command === 'help') return help();
  if (args.command === 'version') return console.log(VERSION);
  if (!['install', 'update', 'status', 'doctor', 'uninstall'].includes(args.command)) throw new Error(`Unknown command: ${args.command}`);
  const p = paths();
  assertSafePath(p.dataRoot, p.home);
  assertSafePath(p.binRoot, p.home);
  assertSafePath(p.skillTarget, p.home);
  const msg = messages[language(args.lang)];
  if (args.command === 'status') return showStatus(p, msg);
  if (args.command === 'doctor') {
    if (!existsSync(managedAgyMc(p))) throw new Error('Mission Control is not installed');
    return run(managedAgyMc(p), ['doctor']);
  }
  if (args.command === 'uninstall') return uninstall(args, p, msg);
  return installOrUpdate(args, p, msg);
}

main().catch((error) => {
  console.error(`\n${c.amber}✗ ${error.message}${c.reset}`);
  process.exitCode = 1;
});
