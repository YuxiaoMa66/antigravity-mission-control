# 发布流程

[English](RELEASING.md) · [简体中文](RELEASING.zh-CN.md)

Mission Control 在各生态中使用同一套协调发布版本：

- Python 与 Git tag：`0.4.2rc3` / `v0.4.2rc3`
- npm SemVer：`0.4.2-rc.3`

它们代表同一个版本。每次发布必须同步更新 `__version__`、`pyproject.toml`、`package.json`、npm bootstrap 常量、CHANGELOG 和中英文发布说明。历史发布说明和资产保持不可变。

## 发布门禁

```bash
python3 scripts/sync_skill_bundle.py
python3 -m unittest discover -s tests -v
npm test
python3 -m compileall -q antigravity_mission_control scripts tests
npm pack --dry-run
python3 scripts/agy_delegate.py doctor
python3 scripts/agy_delegate.py usage --format json
git diff --check
git status --short
```

还需要运行 Skill Creator 的 `quick_validate.py`，检查 wheel 内容，在隔离 HOME 中完成 npm 安装/更新/卸载，并扫描 tracked tree 中的凭据和运行产物。

## 真实 AGY 验收

单元测试驱动的是假 AGY，只能证明包装器与自身假设一致。发布稳定版前，在发布提交上针对本机安装的 `agy` 运行验收套件：

```bash
python3 scripts/real_agy_check.py --report real-agy-report.json
```

它覆盖离线守卫（doctor、不可用模型、非 high 的 Gemini、审批绑定、宽泛工作区、额度快照），并在最新的 Gemini Flash High 上各用一轮 AGY 覆盖：前台运行、后台收集、`continue`、取消、worker 被杀、取消中断、wait 超时、并行只读任务、`--json-schema`、AGY 的 print timeout、只读的 `plan` 模式、编辑锁与工作区证据。所有场景都必须通过。任务状态放在临时目录；编辑类场景会信任仓库旁边的一个临时工作区，结束后移除该信任条目。如果运行被强行终止，下一次运行（或 `--cleanup-only`）会清理残留。用 `--offline-only` 可在不消耗额度的情况下检查守卫，用 `-k <name>` 可单独重跑某个场景。AGY 输出格式变化时，先修复包装器，再把 `tests/fake_agy.py` 更新为新格式，让单元测试持续跟随真实 CLI。

## 发布顺序

1. 将审查后的 `main` 提交推送到 GitHub。
2. 在同一提交创建 `v0.4.2rc3` tag。
3. 使用双语说明创建 GitHub Release。
4. 在隔离环境验证从该 tag 安装。
5. 执行 `npm publish --tag latest --access public`。
6. 验证 `npm view antigravity-mission-control dist-tags` 和 `npx antigravity-mission-control status`。

npm bootstrap 默认安装 Git tag，因此必须先确保 GitHub tag 可访问，再发布 npm。Trusted Publisher/OIDC 不是必需项；没有发布工作流时，使用维护者的 2FA 交互发布即可。目前暂不发布 PyPI；Python 直接安装从 GitHub 获取。

## 预发布

预发布版本在 Python 与 Git tag 中写作 `X.Y.ZrcN`，在 npm SemVer 中写作 `X.Y.Z-rc.N`。在其所在分支的已审查提交上打 tag，并把 GitHub Release 标记为预发布；只有发布稳定版时才更新 `main`。npm 使用 `npm publish --tag next --access public` 发布，使 `latest`、稳定版 npm 包和稳定版安装说明保持在最近一个稳定版本。要转为正式版，需按上面的门禁发布稳定版本。

## 回滚

不要移动或覆盖已发布 Git tag。npm 版本有问题时应说明原因并 deprecate，再发布修复版本并更新 `latest` 标签。GitHub Release 可以标记撤回，但证据和不利发布说明必须保留。
