# 完整参考

[English](REFERENCE.md) · [简体中文](REFERENCE.zh-CN.md)

## 命令表

| 命令 | 用途 |
|---|---|
| `doctor` | 验证 AGY 版本、headless 参数、登录后的模型访问和私有状态目录 |
| `models` | 发现当前精确模型 ID |
| `usage [--watch]` | 脱敏额度快照或实时终端视图 |
| `workspace` | 检查或单独授予精确工作区信任 |
| `approve` | 创建带签名、会过期且可选工作区范围强制的运行批准 |
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
| `scope_violation`、`check_failed`、`incomplete_evidence` | 5 | 策略或工作区范围强制失败 |

任务证据存放在目标仓库之外。结果会保留 provider 输出和诊断，可能包含敏感项目内容。

## 工作区串行保护

前台和后台 `accept-edits` 使用规范工作区 SHA-256 对应的非阻塞操作系统 `flock`。后台启动器会把锁文件描述符继承给 worker，worker 退出时自动释放。只读 `plan` 任务不获取编辑锁。

## 批准清单

`approve` 创建带本机 HMAC-SHA256 的 `agy-mc-approval.v1`，绑定策略、角色、精确模型、规范工作区、prompt SHA-256、AGY 模式、权限配置、非 high Gemini 例外、会话和过期时间。最长有效期为 24 小时。

在 `accept-edits` 模式提供 `--allowed-path` 后，清单还会绑定 `allowed_paths`、`forbidden_paths`、`required_checks`、`base_commit` 和 `preflight_sha256`。scoped approval 要求 `--cwd` 是 Git 仓库根目录。路径规则使用仓库根目录相对的 POSIX 字符串，目录前缀必须以 `/` 结尾；`.git` 与 `.git/` 始终禁止。必跑检查从 `.agy-mc/checks.json`（`agy-mc-checks.v1`）解析，并自动禁止 worker 修改该文件。

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

## 策略、续接与工作区证据

`policy [strict|balanced]` 无需调用 AGY 即可显示当前策略。新 `approve` 清单绑定策略；严格策略的新任务需要 `--three-rosters-presented`，balanced 仍需要 `--confirmed`、精确模型和单独的 unrestricted 授权。仅在用户选择轻量流程后使用 balanced。

纠错用 `approve --correction-of <job-id>`，普通范围内追问用 `--follow-up-of <job-id>`；两者保留父任务的分工、策略及会话。policy-bound `continue` 必须提供该签名 approval，旧 `--roster-approved` 不能把记录链降级成无范围运行。scoped 父任务还会把精确的允许/禁止路径和冻结检查传给后续链；权威范围来自父任务的签名 approval，篡改 `job.json` 会被拒绝。每次后续运行重新采集 base commit 和 preflight 摘要。纠错沿已记录链递增，第三次被拒绝；普通追问保留计数。改变范围需要新的批准任务。确认参数是调用者的声明，不能证明人类真实批准；链计数不是全局调用预算。旧清单和布尔参数保留迁移兼容，未记录纠错计数。

运行在项目外保存私有 Git 前后快照、变更路径指纹及暂存/未暂存 diff 哈希，后台结果和前台 stderr 均提供证据路径。原始签名提示词保持完整，程序追加观测上下文并记录两个提示词哈希。证据缺失、超大文件及快照超时都会标明；被终止的任务可能缺少后快照。这些证据不构成逐文件沙箱、改动归属证明或自动验收。后台结果即使执行成功也保留 `acceptance: not_evaluated`。

可选的签名工作区范围把 `--allowed-path`、`--forbidden-path` 和仓库目录中的 `--required-check` 绑定到 approval。运行前拒绝 commit、dirty 文件或未跟踪文件相对签名快照发生漂移；运行后审计实际变更路径。检查以冻结的 argv、`shell=False` 和 `DEVNULL` 标准输入在独立进程组中执行，超时会终止后代进程；缺失命令、权限错误、超时和非法参数都会形成确定性证据。provider 失败不会掩盖越界修改。结构化结果写入 `enforcement.json`，状态包括 `not_configured`、`scope_passed`、`passed`、`scope_violation`、`check_failed`、`incomplete_evidence`、`provider_error` 或 `canceled`。范围失败返回退出码 5，但 `acceptance` 始终保持 `not_evaluated`，最终验收仍由 Codex 完成。

具体命令和证据限制见[审批流程](../references/approvals.md)及[任务生命周期](../references/job-lifecycle.md)。
