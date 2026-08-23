# 安装指南

[English](INSTALL.md) · [简体中文](INSTALL.zh-CN.md)

## 环境要求

- macOS 或 Linux
- npm 启动安装器需要 Node.js 18+
- Python 3.10+
- Antigravity CLI（`agy`）；缺少时可由启动安装器调用 Google 官方脚本安装
- 使用内置 Skill 时需要 Codex

Mission Control 不读取、不复制 AGY OAuth 材料。首次安装 AGY 后仍需运行 `agy`，在 Google 的交互流程中完成登录。

## 推荐方式：npm 一键安装

先查看精确路径，不写入文件：

```bash
npx antigravity-mission-control@next install --dry-run --lang zh
```

交互式安装：

```bash
npx antigravity-mission-control@next install --lang zh
```

已有 AGY 时，启动安装器会直接使用。没有 AGY 时，交互模式会询问是否运行 `https://antigravity.google/cli/install.sh` 提供的 Google 官方安装器。

同时安装 AGY 与 Mission Control：

```bash
npx antigravity-mission-control@next install --install-agy --lang zh
agy
agy-mc doctor
```

启动安装器会把官方脚本下载到私有临时文件，完成基础响应检查后通过参数数组调用 `bash`，不会把网络响应直接管道给 shell。Google 安装器可能更新 shell PATH；Mission Control 随后删除自己的临时副本。

非交互安装需要分别确认 Mission Control 修改和 AGY 安装：

```bash
npx antigravity-mission-control@next install --yes --install-agy --lang zh
```

如果自动化环境已经准备并登录 AGY，请省略 `--install-agy`。

默认托管路径：

| 内容 | 路径 |
|---|---|
| Python 环境 | `~/.local/share/antigravity-mission-control/venv` |
| CLI 符号链接 | `~/.local/bin/agy-mc` |
| Codex Skill | `${CODEX_HOME:-~/.codex}/skills/antigravity-mission-control` |
| 运行状态 | `${XDG_STATE_HOME:-~/.local/state}/antigravity-mission-control` |
| Skill 可恢复备份 | `${CODEX_HOME:-~/.codex}/skill-backups/` |

如果安装器提示 PATH 缺少目录，请将 `~/.local/bin` 加入 PATH。

## 更新与状态

```bash
npx antigravity-mission-control@next status --lang zh
npx antigravity-mission-control@next update --lang zh
npx antigravity-mission-control@next doctor
```

`update` 会先更新托管 Python 包，再原子部署内置 Skill，并把旧 Skill 保存为带时间戳的备份。

## 可恢复卸载

```bash
npx antigravity-mission-control@next uninstall --lang zh
```

Skill 会移动到 Codex 备份目录；托管 Python 环境会在原位置旁改名为时间戳备份。用户自己的 AGY 设置、信任项、OAuth 状态和 Mission Control 任务证据都不会删除。

## 直接使用 Python

```bash
python3 -m pip install "git+https://github.com/YuxiaoMa66/antigravity-mission-control.git@v0.1.0a3"
agy-mc skill install --lang zh
```

可使用 `agy-mc skill install --dry-run`、`status`、`update` 和 `uninstall`。Python 安装器只管理 Skill，不创建 npm 托管的虚拟环境或 CLI 链接。

## 本地开发来源

```bash
npx antigravity-mission-control install \
  --source "/absolute/path/to/antigravity-mission-control" --lang zh
```

自动化测试时增加 `--yes`，并把 `HOME`、`CODEX_HOME`、`AGY_MC_INSTALL_ROOT`、`AGY_MC_BIN_DIR` 或 `AGY_MC_SKILL_TARGET` 指向隔离目录。

## 已存在的非托管 Skill

如果现有目录没有 `.agy-mc-install.json`，安装器默认拒绝覆盖。请先检查；确实要替换时才使用 `--force`。替换前仍会备份旧目录。

安装或更新后需要重启或刷新 Codex，让技能发现机制重新加载文件。
