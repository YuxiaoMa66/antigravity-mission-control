# 安装指南

[English](INSTALL.md) · [简体中文](INSTALL.zh-CN.md)

## 环境要求

- macOS 或 Linux
- npm 启动安装器需要 Node.js 18+
- Python 3.10+
- 已通过正常交互流程认证的 Antigravity CLI（`agy`）
- 使用内置 Skill 时需要 Codex

Mission Control 不读取、不复制 AGY OAuth 材料。

## 推荐方式：npm 一键安装

先查看精确路径，不写入文件：

```bash
npx antigravity-mission-control install --dry-run --lang zh
```

交互式安装：

```bash
npx antigravity-mission-control install --lang zh
```

非交互安装：

```bash
npx antigravity-mission-control install --yes --lang zh
```

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
npx antigravity-mission-control status --lang zh
npx antigravity-mission-control update --lang zh
npx antigravity-mission-control doctor
```

`update` 会先更新托管 Python 包，再原子部署内置 Skill，并把旧 Skill 保存为带时间戳的备份。

## 可恢复卸载

```bash
npx antigravity-mission-control uninstall --lang zh
```

Skill 会移动到 Codex 备份目录；托管 Python 环境会在原位置旁改名为时间戳备份。用户自己的 AGY 设置、信任项、OAuth 状态和 Mission Control 任务证据都不会删除。

## 直接使用 Python

```bash
python3 -m pip install "git+https://github.com/YuxiaoMa66/antigravity-mission-control.git@v0.1.0a1"
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
