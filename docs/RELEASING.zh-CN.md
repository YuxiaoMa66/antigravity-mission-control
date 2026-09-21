# 发布流程

[English](RELEASING.md) · [简体中文](RELEASING.zh-CN.md)

Mission Control 在各生态中使用同一套协调发布版本：

- Python 与 Git tag：`0.4.2rc1` / `v0.4.2rc1`
- npm SemVer：`0.4.2-rc.1`

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

## 发布顺序

1. 将审查后的 `main` 提交推送到 GitHub。
2. 在同一提交创建 `v0.4.2rc1` tag。
3. 使用双语说明创建 GitHub Release。
4. 在隔离环境验证从该 tag 安装。
5. 执行 `npm publish --tag latest --access public`。
6. 验证 `npm view antigravity-mission-control dist-tags` 和 `npx antigravity-mission-control status`。

npm bootstrap 默认安装 Git tag，因此必须先确保 GitHub tag 可访问，再发布 npm。Trusted Publisher/OIDC 不是必需项；没有发布工作流时，使用维护者的 2FA 交互发布即可。目前暂不发布 PyPI；Python 直接安装从 GitHub 获取。

## 预发布

预发布版本在 Python 与 Git tag 中写作 `X.Y.ZrcN`，在 npm SemVer 中写作 `X.Y.Z-rc.N`。在其所在分支的已审查提交上打 tag，并把 GitHub Release 标记为预发布；只有发布稳定版时才更新 `main`。npm 使用 `npm publish --tag next --access public` 发布，使 `latest`、稳定版 npm 包和稳定版安装说明保持在最近一个稳定版本。要转为正式版，需按上面的门禁发布稳定版本。

## 回滚

不要移动或覆盖已发布 Git tag。npm 版本有问题时应说明原因并 deprecate，再发布修复版本并更新 `latest` 标签。GitHub Release 可以标记撤回，但证据和不利发布说明必须保留。
