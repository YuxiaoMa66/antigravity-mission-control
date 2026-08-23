<p align="center"><img src="assets/logo/mission-control.svg" width="720" alt="Antigravity Mission Control"></p>

<p align="center"><a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a></p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-7c3aed" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Node.js-18%2B-0891b2" alt="Node.js 18+">
  <img src="https://img.shields.io/badge/AGY-tested_1.1.19-22d3ee" alt="AGY tested 1.1.19">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-a78bfa" alt="MIT License"></a>
</p>

面向 Antigravity CLI（`agy`）的策略化任务控制层：将工作路由到精确模型，把批准绑定到具体任务，串行保护编辑 worker，确认取消结果并实时查看额度；最终验收始终由 Codex 负责。

<p align="center"><img src="assets/terminal-preview.svg" width="920" alt="Mission Control 终端界面预览"></p>

> **Alpha：** 已适合公开预发布测试，但还不是稳定安全边界。本项目为独立社区项目，与 Google 或 Antigravity 无官方隶属关系。

## 别让已经薅到的 Gemini 在账号里吃灰

如果你手里正好有 Google One AI 订阅，或者拿到了符合条件的学生一年福利，账号里可能已经躺着一批 Gemini 额度。Antigravity 客户端像写到一半换键盘，CLI 也未必顺手；Codex 倒是已经用出肌肉记忆，可额度常常午饭前就见底，模型偶尔还爱走观光路线。Gemini Flash 跑得快，这份速度值得派上用场。

把 Mission Control 装进你熟悉的 Codex harness。让 Codex 当产品经理、总监和爱挑刺的验收官，把实现工单交给 Antigravity。Codex 定范围、批权限、看 diff、跑测试；AGY worker 负责干活。

Google 账号资格和额度由你自己提供。Mission Control 不送订阅，也不会把提供商额度凭空变多。

### 用结构和审核把任务拉回正轨

| 阶段 | 谁负责 | 防偏离设计 |
|---|---|---|
| 结构设计 | Codex | 把需求整理成范围、约束、验收标准和有边界的角色 |
| 方案选择 | Codex + 你 | 提供 A/B/C 模型阵容和有实际差异的设计选项；关键选择由你确认或修改 |
| 执行 | AGY worker | 在已批准目标内自己制定步骤并完成工作，不为每个无害动作反复请示 |
| 监督验收 | reviewer + Codex | 检查范围漂移、证据、测试和交付质量；Codex 决定接受、纠正或退回 |

planner 可以在批准目标内自己决定路线。某个选择会改变范围、成本、可逆性或产品行为时，它必须把可选方案摆出来。reviewer 会同时拿到原始任务书和真实产物，专门识别“答案写得很漂亮，完成的却是另一件事”。

## 安装

已经有 AGY：先确认版本，运行一次 `agy` 完成 Google 登录，再安装 Mission Control：

```bash
agy --version
agy
npx antigravity-mission-control@next install --lang zh
```

还没有 AGY：让安装器先调用 Google 官方安装器：

```bash
npx antigravity-mission-control@next install --install-agy --lang zh
```

交互安装检测不到 AGY 时会先询问；非交互安装必须明确增加 `--install-agy`。新装 AGY 后运行 `agy` 完成 Google 登录。Mission Control 不读取、不复制登录材料。

安装器会先展示所有目标，再创建私有 Python 运行环境、安装 `agy-mc`、部署 Codex Skill。全程使用参数数组，不使用 shell 拼接。CI 或 agent 环境需要加 `--yes`；可以先用 `--dry-run` 查看影响。

```bash
npx antigravity-mission-control@next install --dry-run --lang zh
npx antigravity-mission-control@next install --yes --lang zh
npx antigravity-mission-control@next status --lang zh
```

也支持直接使用 Python：

```bash
python3 -m pip install "git+https://github.com/YuxiaoMa66/antigravity-mission-control.git@v0.1.0a2"
agy-mc skill install --lang zh
agy-mc doctor
```

完整安装、更新、卸载、本地来源和 PATH 说明见[安装指南](docs/INSTALL.zh-CN.md)。

## 分层结构

| 层 | 职责 |
|---|---|
| Codex Skill | 阵容选择、范围、权限边界和独立验收 |
| `agy-mc` 核心 | 模型发现、签名批准、AGY 传输、任务、锁、证据和额度 |
| npm bootstrap | 托管 Python 环境、Skill 部署、更新与可恢复卸载 |
| AGY | 执行精确且有边界的 worker 任务 |

npm 层刻意保持轻量。全部行为规则只在 Python companion 中实现，避免 npm 与 Python 安装方式产生两套逻辑。

## 实时额度

```bash
agy-mc usage
agy-mc usage --watch --interval 60
agy-mc usage --format json
```

规范化的 `agy-mc-usage.v1` 会显示模型组、额度窗口、剩余百分比、重置时间和禁用状态。缺失值保持 `unknown`，绝不会改写成误导性的 `0%`；输出不包含 OAuth、原始账户载荷或账户身份。

## 绑定批准

用户确认精确阵容和权限后，生成短期有效的批准清单：

```bash
agy-mc approve \
  --strategy A --role implementer --model gemini-3.7-flash-high \
  --cwd /absolute/project --prompt-file /private/prompt.txt \
  --mode accept-edits --expires-minutes 60 --confirmed
```

将返回的文件传给 `run`。本机 HMAC 会绑定策略、角色、模型、规范工作区、prompt 哈希、模式、权限配置、会话和过期时间；任何字段变化都会拒绝执行。

```bash
agy-mc run \
  --strategy A --role implementer --model gemini-3.7-flash-high \
  --cwd /absolute/project --prompt-file /private/prompt.txt \
  --mode accept-edits --approval-file ~/.local/state/antigravity-mission-control/approvals/<id>.json
```

旧的布尔批准参数仅用于 Alpha 迁移兼容，已经弃用。

## 后台任务

运行时增加 `--background`，然后使用：

```bash
agy-mc status [job-id]
agy-mc wait <job-id> --timeout 10m
agy-mc result <job-id>
agy-mc cancel <job-id>
agy-mc continue <job-id> --prompt-file /private/follow-up.txt
```

编辑任务按规范工作区使用操作系统级非阻塞锁。`cancel` 会先写入 `canceling`，发送 TERM 并等待，必要时升级到 KILL；只有确认进程退出后才报告 `canceled`。

## 核心原则

- 每次从当前 AGY 会话发现精确模型，不把历史 slug 当成事实。
- 工作区信任与 unrestricted 执行是两项独立授权。
- worker 成功不等于任务通过；Codex 必须检查真实 diff、诊断和测试。
- prompt 通过 `stream-json` stdin 发送，不进入进程参数。
- 状态目录权限为 `0700`，prompt、批准、锁和结果为 `0600`。
- 安装、更新和卸载均保留可恢复备份。

继续阅读：[完整参考](docs/REFERENCE.zh-CN.md)、[安全说明](SECURITY.md)、[贡献指南](CONTRIBUTING.md)和[发布流程](docs/RELEASING.zh-CN.md)。

## 验证

```bash
python3 -m unittest discover -s tests -v
npm test
npm pack --dry-run
python3 -m compileall -q antigravity_mission_control scripts tests
```

## 许可证

MIT。角色合同模式基于 MIT 许可参考了 [keli-wen/agy-staff](https://github.com/keli-wen/agy-staff)，详见 [NOTICE](NOTICE)。
