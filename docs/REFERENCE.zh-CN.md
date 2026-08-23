# 完整参考

[English](REFERENCE.md) · [简体中文](REFERENCE.zh-CN.md)

## 命令表

| 命令 | 用途 |
|---|---|
| `doctor` | 验证 AGY 版本、headless 参数和私有状态目录 |
| `models` | 发现当前精确模型 ID |
| `usage [--watch]` | 脱敏额度快照或实时终端视图 |
| `workspace` | 检查或单独授予精确工作区信任 |
| `approve` | 创建带签名、会过期的运行批准 |
| `select` | 为 A/B/C 阵容生成候选模型 |
| `run` | 执行前台或后台 worker |
| `status`、`wait`、`result` | 观察并收集任务 |
| `cancel` | 经确认的 TERM/KILL 取消流程 |
| `continue` | 续接一个精确记录的会话 |
| `skill` | 安装、更新、检查或可恢复卸载 Codex Skill |

## 任务状态与退出码

| 状态 | 退出码 | 含义 |
|---|---:|---|
| `starting`、`running`、`canceling` | 2 | 尚未完成，需要继续观察 |
| `done`、`done_with_warnings` | 0 | provider 执行结束；是否验收仍由 Codex 决定 |
| `error`、`crashed`、`cancel_failed` | 3 | 基础设施或执行失败 |
| `canceled` | 4 | 调用方取消后已经确认进程退出 |

任务证据存放在目标仓库之外。结果会保留 provider 输出和诊断，可能包含敏感项目内容。

## 工作区串行保护

前台和后台 `accept-edits` 使用规范工作区 SHA-256 对应的非阻塞操作系统 `flock`。后台启动器会把锁文件描述符继承给 worker，worker 退出时自动释放。只读 `plan` 任务不获取编辑锁。

## 批准清单

`approve` 创建带本机 HMAC-SHA256 的 `agy-mc-approval.v1`，绑定策略、角色、精确模型、规范工作区、prompt SHA-256、AGY 模式、权限配置、非 high Gemini 例外、会话和过期时间。最长有效期为 24 小时。

签名密钥位于 `${XDG_STATE_HOME:-~/.local/state}/antigravity-mission-control/approval.key`，权限为 `0600`。复制到另一台机器的清单无法通过验证。签名证明创建后的本地完整性，但不能证明真人确实授权，因此项目持久决策日志仍然是最终授权证据。

## 环境变量

| 变量 | 用途 |
|---|---|
| `AGY_MC_BIN` | 精确 AGY 可执行文件 |
| `AGY_MC_SETTINGS_PATH` | AGY 设置 JSON |
| `AGY_MC_STATE_ROOT` | Mission Control 状态根目录 |
| `AGY_MC_JOB_ROOT` | 任务证据目录 |
| `CODEX_HOME` | Skill 部署使用的 Codex 主目录 |
| `XDG_STATE_HOME` | 标准状态父目录 |
| `NO_COLOR` | 关闭 npm 终端颜色 |

旧的 `AGY_ORCHESTRATOR_BIN` 和 `AGY_ORCHESTRATOR_JOB_ROOT` 仅作为迁移兼容别名保留。

## 额度 Schema

`agy-mc-usage.v1` 返回 `status`、`source`、`fetched_at`、规范化 `groups` 和安全 `errors`。每个 bucket 包含 `id`、`name`、`window`、`remaining_fraction`、`remaining_percent`、`reset_time` 和 `disabled`。错误不会泄露 AGY 原始 stderr。

## 权限边界

精确工作区信任必须单独执行 `workspace --grant --trust-approved`。它拒绝文件系统根目录、用户主目录以及匹配的 `deny` 或 `ask` 规则。unrestricted 执行需要自己的批准配置，绝不会从 workspace trust 推导。
