# Antigravity Mission Control（反重力任务控制台）

这是一个面向 Antigravity CLI（`agy`）的策略化编排层：Codex 负责拆解、权限边界、冲突管理和最终验收，AGY 模型作为受限 worker 执行规划、实现或审查。当前为 Alpha 版本，并非 Google 或 Antigravity 官方产品。

## 主要能力

- 实时发现可用模型，并按 A（性价比）、B（最佳效果）、C（最新 Gemini Flash High）组织阵容。
- 精确工作区信任与 unrestricted 权限分开确认。
- 支持同步、后台、状态查询、等待、结果收集、取消和会话续接。
- 普通任务 prompt 通过 `stream-json` 标准输入发送，不出现在进程参数中。
- 本地任务目录权限为 `0700`，证据文件为 `0600`。
- 实时显示 AGY 剩余额度。

## 实时额度

```bash
agy-mc usage                         # 查看一次
agy-mc usage --watch                 # 默认每 60 秒刷新
agy-mc usage --watch --interval 30   # 自定义刷新间隔
agy-mc usage --format json           # 供脚本或面板读取
```

显示内容包括模型组、五小时/周等额度窗口、剩余百分比、重置时间和禁用状态。缺失或失败的数据会显示为 `unknown`，不会伪装成 0。输出不包含 OAuth、邮箱或原始账户载荷。

## 本地安装与验证

需要 Python 3.10+ 和可用的 `agy`。当前 Alpha 基于 macOS 与 AGY 1.1.19 开发。

```bash
python3 -m pip install -e .
agy-mc doctor
python3 -m unittest discover -s tests -v
```

不安装包也可运行兼容入口：`python3 scripts/agy_delegate.py usage --watch`。

远程 GitHub 仓库创建、推送和包发布不包含在本地构建授权中，需要另行明确授权。
