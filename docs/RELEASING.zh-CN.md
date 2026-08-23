# 发布流程

[English](RELEASING.md) · [简体中文](RELEASING.zh-CN.md)

Mission Control 在两个生态中使用不同的合法版本格式：

- Python 与 Git tag：`0.1.0a2` / `v0.1.0a2`
- npm SemVer：`0.1.0-alpha.2`

它们代表同一个版本。每次发布必须同步更新 `VERSION`、`__version__`、`pyproject.toml`、`package.json`、npm bootstrap 常量、CHANGELOG 和发布说明。

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
2. 在同一提交创建 `v0.1.0a2` tag。
3. 使用双语说明创建 GitHub Pre-release。
4. 在隔离环境验证从该 tag 安装。
5. 执行 `npm publish --tag next --access public`。
6. 验证 `npm view antigravity-mission-control dist-tags` 和 `npx antigravity-mission-control status`。

npm bootstrap 默认安装 Git tag，因此必须先确保 GitHub tag 可访问，再发布 npm。Alpha 阶段暂不发布 PyPI；Python 直接安装从 GitHub 获取。

## 回滚

不要移动或覆盖已发布 Git tag。npm 版本有问题时应说明原因并 deprecate，再发布修复版本并更新 `next` 标签。GitHub Release 可以标记撤回，但证据和不利发布说明必须保留。
