# 训练版本代码推送（GitHub）

## 固定配置

- GitHub：继续使用当前仓库的 `origin`，开发过程中可以按需要随时推送。

## 推送规则

1. GitHub 推送不受限制，普通修改、调试和回放修复可以正常推送。
2. 训练任务使用的 `codeUrl` 指向 GitHub 仓库；新训练版本启动前，确认 `origin` 上已包含训练要用的 commit。
3. 在实验记录中记录训练任务、分支和 commit SHA，但不要记录 Token 或完整凭据。

## 训练版本启动前的确认流程

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
git ls-remote --heads origin <branch>
```

若远端不是预期 commit、出现非 fast-forward 或需要强制推送，停止并请求用户确认；禁止默认 `--force`。

## 安全边界

- 不打印 Token、完整凭据、凭据管理器内容或包含凭据的远程 URL。
- 不把代码推送放进 15 分钟监控循环、回放流程或每次修改的自动钩子。

> 历史：本文件原含 GitLab 镜像（itools.weichai.com）同步流程，已于 2026-08-20 按用户要求删除；仅保留 GitHub 推送规则。
