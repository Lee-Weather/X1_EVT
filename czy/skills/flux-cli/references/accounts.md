# Flux 多账号额度管理

## 安全边界

仅在用户要求自动切换账号，或当前账号明确出现余额/额度不足时使用。切换账号会改变本机 Flux 认证状态，但不能扩大用户对任务、项目或计费操作的授权。

优先使用系统 Keychain。当前项目若使用账号池文件，以以下位置为准：

- 正式账号池：`czy/skills/flux-cli/api_key.json`；
- 旧 gm-cli 账号池已移动到 `czy/diff/gm-cli/api_key.json`，仅作备份，不作为运行时回退来源；
- 不复制、打印、提交或写入实验记录中的 API Key；
- 确保账号池文件被 Git 忽略。

账号池最小结构：

```json
{
  "accounts": [
    {
      "email": "user@example.com",
      "api_key": "<secret>",
      "budget": 50.0,
      "used": 0.0,
      "exhausted": false
    }
  ]
}
```

## 选择与登录

1. 读取账号池，但只输出账号索引或脱敏邮箱。
2. 选择第一个 `exhausted == false` 的账号。
3. 用 `flux auth login --api-key <secret>` 登录，捕获输出且不回显。
4. 用 `flux auth status` 检查本地配置。
5. 如需 `flux auth whoami`，只投影账号、权限和余额等必要字段；不要打印完整响应。

不要通过命令行调试日志、shell 历史或临时 JSON 持久化 API Key。

## 判断额度耗尽

以下信号可判定当前账号不可继续计费：

- `task create` 或 `task run` 返回余额不足；
- 错误包含 `insufficient balance`、`余额不足` 或明确额度字段；
- `whoami` 的结构化余额字段为零；
- 任务因平台计费失败终止，且日志明确指向额度问题。

网络失败、任务代码报错、资源不足或普通权限错误不能自动标记为额度耗尽。

## 标记与切换

确认额度耗尽后：

1. 将当前账号的 `exhausted` 设为 `true`；
2. 在可确认已完全消耗时再把 `used` 设为 `budget`；
3. 登录下一个可用账号；
4. 重新执行尚未成功的创建或启动动作，不要重复已经成功的动作；
5. 记录账号切换发生，但不要记录密钥。

所有账号均耗尽时停止新的计费操作并报告账号数量。不要自动创建新账号、充值或借用未授权凭据。

## 与任务的关系

- 切换账号后先确认目标项目和任务对新账号可见。
- 不假设不同账号共享项目、私有 Git 凭据或对象存储权限。
- 任务已经运行时不要因账号切换而停止或复制任务。
- 下载已有公开授权产物时，可继续使用任务返回的临时下载链接；不要跨账号保存链接。

## 跨账号续训（git 内置 checkpoint 路线）

### 背景

- 平台的 checkpoint（OSS `policUrl`）、项目、个人存储都是**账号内资源**，跨账号不可访问；`resumeFromTaskId` / `resumeFromCheckPoint` 只能引用**同账号**下的任务。
- 因此换账号续训**不能**用「恢复训练任务」模板（`checkPointFilePath` + `resumeFrom*`），改用 **git 内置 checkpoint**：把 `.pt` 用 `git add -f` 提交进训练仓库，云端 clone 时自动到位，与账号无关。
- 前提：训练脚本支持从仓库内路径加载权重（本项目为 `--resume --ckpt_path=<repo>/<file>.pt`）。
- 本项目先例 commit：`4dca161` / `44ef417` / `d75b9b9` / `e0e4036`（均在 X1_29_amp）。

### 标准流程

1. **迁出 checkpoint（旧账号仍持登录态时执行）**：
   ```bash
   flux task model list --task-id "<旧任务ID>" --page 1 --limit 20
   # 取目标 checkpoint 行的 policUrlDown（不要跨账号保存该临时链接）
   curl -L -o model_XXXXX.pt "<policUrlDown>"
   ```
2. **内置入 git**：
   ```bash
   cp model_XXXXX.pt <repo_root>/        # 放仓库根或任意 git 跟踪路径
   git add -f model_XXXXX.pt             # *.pt 通常被 .gitignore 忽略，-f 必不可少
   git commit -m "..." && git push origin <branch>
   ```
   确认 push 输出/`git ls-remote` 显示远端已包含该 commit。
3. **切换账号**：按上文「标记与切换」登录新账号。
4. **准备新账号侧资源**：项目同样是账号内资源，旧 projectId 不可复用；用新账号下的模板项目或 `flux project create` 新建，记录新 projectId。
5. **创建任务（与恢复模板的关键差异）**：
   - `personalDataPath` 留空；`checkPointFilePath` / `checkPointMountPath` / `resumeFrom*` **全部不传**（不走 OSS resume 路线）。
   - `startScript` 以 `gm-run` 开头，resume 走仓库内路径：
     `gm-run <repo>/<train.py> --task=<task> --headless --resume --ckpt_path=<repo>/model_XXXXX.pt --max_iterations=N`
   - 确认训练脚本的轮次语义（`--max_iterations` 是绝对步数还是从断点续训的增量）。
   - `create --dry-run`（exit 10 通过）→ 去掉 `--dry-run` 正式创建 → `flux task run --task-id "<新任务ID>"`。
6. **记录**：新任务与旧任务在平台上无 resumeFrom 关联，实验记录中必须手动注明「续自哪个任务 / 哪个 checkpoint / 哪个 commit」。

### 注意事项

- **体积**：GitHub 单文件硬限 100MB（>50MB 有警告）。只内置**一个**续训起点 checkpoint；训练产出仍从云端任务下载（`policUrlDown`），不要把整条 checkpoint 链入库。
- **不要误伤已有内置 checkpoint**：仓库内可能有先前入库的 checkpoint 供回滚；清理时不要 `git rm` 掉它们（先例：`model_29998.pt` 被误移出暂存，用 `git restore --staged` 恢复）。
- **私有仓库**：新账号需在 Web 平台「个人设置 → Git 信息」配好对应 Git 凭证（见 SKILL.md「私有 Git 仓库需要配置账号和 Token」），否则云端 clone 失败。
- **成本时点**：账号切换只影响"下一个任务在哪创建"；已在运行的任务不受影响，也不要因切换而停止或复制它。
