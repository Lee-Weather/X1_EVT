# Flux CLI 快速上手教程

> 本教程覆盖从 API Key 创建、CLI 本地安装，到在 Cursor Agent 中配置 CLI Skill 的完整流程。

---
## 最简流程：从 API Key 到 Skill 使用（约 5 分钟）

按下面顺序做完即可在 Cursor 里用自然语言操作 Flux 任务。

| 步骤 | 操作 |
|------|------|
| **1. 创建 API Key** | 登录 Flux → 左下角头像 → **API Key 管理** → **新建** → 填写名称并**立即复制**生成的 Key（格式 `gm_sk_xxxxxxxx`，仅显示一次）。 |
| **2. 安装 CLI** | 执行 `npm install -g @limxdynamics/flux-cli`（需 Node.js >= 16）。安装后执行 `flux --version` 确认。 |
| **3. 配置** | `flux config set base_url "https://internal.limxdynamics.com/dev-api"`<br>`flux auth login --api-key "gm_sk_你的Key"` |
| **4. 验证** | `flux auth status`（本地）→ `flux auth whoami`（服务端）。 |
| **5. 安装 Skill** | `mkdir -p ~/.cursor/skills/flux-cli`，将 [SKILL.md](../npm/skills/flux-cli/SKILL.md) 放到该目录；或在 Cursor **Settings → Features → Agent Skills** 确认 Skills 路径为 `~/.cursor/skills/`。 |
| **6. 使用** | 在 Cursor Agent 里直接说「帮我列出任务」「查看任务 task_xxx 详情」「下载任务某个 checkpoint 的模型文件」等，或输入 `flux task list`；提到 `flux`、Flux、任务、项目、checkpoint、模型文件下载时 Agent 会自动使用 flux-cli Skill。 |

详细说明与常见问题见下文各章节。

---


## 目录

1. [创建 API Key](#1-创建-api-key)
2. [安装 CLI](#2-安装-cli)
3. [配置 CLI](#3-配置-cli)
4. [验证连接](#4-验证连接)
5. [退出码与输出行为](#5-退出码与输出行为)
6. [在 Cursor Agent 中安装 CLI Skill](#6-在-cursor-agent-中安装-cli-skill)
7. [通过 Agent 使用 CLI](#7-通过-agent-使用-cli)
8. [常见问题](#8-常见问题)

---

## 1. 创建 API Key

### 1.1 登录 Flux 平台

打开浏览器，访问 Flux 平台并登录你的账号。

### 1.2 进入 API Key 管理页面

登录后，点击左下角用户头像 → **API Key 管理**。

### 1.3 创建新的 API Key

1. 点击 **新建** 按钮。
2. 填写 Key 的名称（如 `local-dev`、`cursor-agent`），便于区分用途。
3. 点击 **确认**。
4. **立即复制并妥善保存生成的 Key**（格式为 `gm_sk_xxxxxxxxxxxxxxxx`），该 Key 仅在创建时完整显示一次。

> **安全提示**：API Key 具有账号级别的操作权限，请勿提交到代码仓库、分享给他人，或在公开场合展示。

---

## 2. 安装 CLI

推荐通过 npm 一行命令安装，自动匹配当前系统和架构（macOS / Linux / Windows，x64 / arm64）。

### 2.1 通过 npm 安装（推荐）

```bash
npm install -g @limxdynamics/flux-cli
```

> 需要 Node.js >= 16，安装后会自动选择对应平台的二进制。

### 2.2 验证安装

```bash
flux --version
```

输出示例：

```
flux-cli v1.1.0（实际输出为结构化 JSON，并包含 version/commit/date）
```

---

## 3. 配置 CLI

### 3.1 设置服务地址（base_url）

```bash
flux config set base_url "https://internal.limxdynamics.com/dev-api"
```

> `base_url` 为 Flux 后端服务地址，CLI 会在此基础上拼接 `/api` 前缀发起请求。

### 3.2 保存 API Key

```bash
flux auth login --api-key "gm_sk_xxxxxxxxxxxxxxxx"
```

CLI 会优先将 Key 存入系统 Keychain（macOS Keychain / Windows Credential Manager / Linux Secret Service），若 Keychain 不可用则回退存储到本地配置文件 `~/.config/gradmotion/config.yaml`。

成功输出示例：

```json
{
  "success": true,
  "data": {
    "profile": "default",
    "saved_to": "keychain"
  }
}
```

### 3.3 配置文件说明

配置文件默认路径：

- **macOS / Linux**：`~/.config/gradmotion/config.yaml`
- **Windows**：`%APPDATA%\gradmotion\config.yaml`

配置结构示例：

```yaml
profiles:
  default:
    base_url: https://internal.limxdynamics.com/dev-api
    timeout: 30s
    retry: 3
    concurrency: 4
current: default
```

### 3.4 多环境 Profile（可选）

如果你需要同时管理多个环境（如开发、测试、生产），可以使用 Profile：

```bash
# 创建 dev profile
flux config profile set dev \
  --base-url "https://internal.limxdynamics.com/dev-api" \
  --timeout 30s \
  --retry 3

# 切换到 dev profile
flux config profile use dev

# 查看所有 profile
flux config profile list

# 临时使用某个 profile（不切换默认）
flux --profile dev task list
```

---

## 4. 验证连接

### 4.1 检查本地认证状态

```bash
flux auth status
```

输出示例：

```json
{
  "success": true,
  "data": {
    "profile": "default",
    "base_url": "https://internal.limxdynamics.com/dev-api",
    "has_api_key": true,
    "key_source": "keychain"
  }
}
```

### 4.2 验证服务端连接

```bash
flux auth whoami
```

成功后会返回当前账号的用户信息，确认 CLI 与 Flux 服务端通信正常。

### 4.3 快速任务列表测试

```bash
flux task list
```

### 4.4 执行前快速探测（推荐）

在执行创建/编辑/删除前，建议先确认当前 CLI 具备完整命令：

```bash
flux --help
flux task --help
flux project --help
```

---

## 5. 退出码与输出行为

### 5.1 语义退出码

CLI 通过退出码精确表达命令执行结果，Agent 或脚本可据此决定下一步操作：

| 退出码 | 含义 | Agent 建议行为 |
|--------|------|---------------|
| `0` | 成功 | 继续执行 |
| `1` | 一般错误（网络、服务端 5xx） | 读取 stderr，可重试 |
| `2` | 参数无效（缺少必填、枚举错误） | 修正参数后重试 |
| `3` | 资源未找到（404） | 跳过或创建 |
| `4` | 权限不足（401/403） | 检查 API Key 或权限 |
| `5` | 冲突/已存在（409） | 跳过或更新 |
| `10` | dry-run 预览通过 | 去掉 `--dry-run` 正式执行 |

执行 `flux --help` 可查看完整退出码列表。

### 5.2 stdout / stderr 分离

- **成功时**：结构化 JSON 数据输出到 **stdout**
- **失败时**：结构化 JSON 错误输出到 **stderr**，stdout 无内容

这意味着 Agent 或脚本可以安全地用管道处理 stdout 数据，而不会被错误信息干扰：

```bash
# stdout 只有数据，可安全传给 jq
flux task info --task-id "task_xxx" 2>/dev/null | jq '.data.taskBaseInfo.taskStatus'

# 错误信息在 stderr，可单独捕获
flux task info --task-id "bad_id" 2>error.json 1>/dev/null
```

### 5.3 错误信息结构

失败时 stderr 输出的 JSON 包含可操作的错误信息：

```json
{
  "success": false,
  "data": null,
  "meta": { "command": "flux task info", "profile": "prod" },
  "error": {
    "code": "INVALID_ARGUMENT",
    "message": "task-id is required",
    "hint": "",
    "retryable": false,
    "input": { "task-id": "" }
  }
}
```

- `code`：机器可读的错误类型
- `retryable`：是否可重试（`true` 表示网络/服务端临时故障，`false` 表示参数错误等永久故障）
- `input`：导致失败的输入值回显，便于定位问题

### 5.4 `--dry-run` 预览模式

所有写操作（create / edit / run / stop / delete 等）支持 `--dry-run`，预览将要发送的请求而不实际执行：

```bash
flux task create --file ./create.json --dry-run
```

输出示例：

```json
{
  "success": true,
  "data": {
    "dry_run": true,
    "action": "flux task create",
    "method": "POST",
    "endpoint": "/task/create",
    "body": { "taskBaseInfo": { "projectId": "proj_xxx" } },
    "query": null
  }
}
```

- dry-run 通过时退出码为 **10**（非 0），Agent 可据此区分"预览通过"和"实际执行成功"
- dry-run 也会先校验参数，参数错误仍返回退出码 2
- 推荐工作流：先 `--dry-run` 确认 → 再去掉 `--dry-run` 正式执行

---

## 6. 在 Cursor Agent 中安装 CLI Skill

CLI Skill 让 Cursor 中的 AI Agent 能够理解并正确调用 `flux` 命令，包括参数校验、安全约束和最佳实践。

### 6.1 找到 Skills 存放目录

Cursor 的 Skills 通常存放在 `~/.cursor/skills/` 目录下。

```bash
# 查看当前 skills 目录
ls ~/.cursor/skills/
```

### 6.2 创建 flux-cli Skill 目录

```bash
mkdir -p ~/.cursor/skills/flux-cli
```

### 6.3 下载 SKILL.md 文件

点击下方链接下载 flux-cli Skill 文件：

**[下载 SKILL.md](../npm/skills/flux-cli/SKILL.md)**

将下载的 `SKILL.md` 放到 `~/.cursor/skills/flux-cli/` 目录下：

```bash
mkdir -p ~/.cursor/skills/flux-cli
mv ~/Downloads/SKILL.md ~/.cursor/skills/flux-cli/SKILL.md
```

> 该 Skill 文件包含 `flux` 命令的完整操作规范、参数校验规则和安全约束，供 Cursor Agent 在执行 CLI 操作时自动参考。

### 6.4 在 Cursor 中注册 Skill

打开 Cursor，进入 **Settings（齿轮图标）→ Features → Agent Skills**，确认 Skills 目录路径已正确配置为 `~/.cursor/skills/`。

或者，直接在对话框中 `@` 引用该 Skill 即可激活。

> **确认 Skill 已生效**：在 Cursor 的 Agent 对话框中输入 `flux task list`，Agent 会自动识别 flux-cli 上下文并给出正确的操作建议。

---

## 7. 通过 Agent 使用 CLI

安装 CLI Skill 后，你可以直接用自然语言让 Cursor Agent 帮你操作 `flux` 命令。

### 7.1 典型工作流示例

**场景一：查看任务列表**

在 Cursor Agent 中输入：

```
帮我查看所有任务列表
```

Agent 会执行：

```bash
flux task list --page 1 --limit 50
```

---

**场景二：查看指定任务详情**

```
查看任务 task_123 的详情和当前状态
```

Agent 会执行：

```bash
flux task info --task-id "task_123"
```

---

**场景三：创建并运行任务**

```
帮我创建一个训练任务，项目 ID 是 proj_001，任务名称是 test-run
```

Agent 会先提示你补充必要参数（如 `codeType`、`goodsId` 等），然后生成：

```bash
flux task create --file ./create.json
flux task run --task-id "task_xxx"
```

---

**场景四：实时查看任务日志**

```
追踪任务 task_123 的实时日志，最多等 5 分钟
```

Agent 会执行：

```bash
flux task logs --task-id "task_123" --follow --interval 2s --timeout 5m
```

---

**场景五：停止任务（高风险，推荐 dry-run → 确认 → 执行）**

```
停止任务 task_123
```

Agent 推荐工作流：

```bash
# 1. 查看任务状态
flux task info --task-id "task_123"

# 2. dry-run 预览（退出码 10 表示可以执行）
flux --yes task stop --task-id "task_123" --dry-run

# 3. 确认无误后正式执行
flux --yes task stop --task-id "task_123"
```

> **注意**：在非交互环境（Agent/CI/脚本）中，危险操作必须加 `--yes`，否则 CLI 会返回退出码 2 并报错 `NON_INTERACTIVE`，而不会挂起等待输入。

---

**场景六：先选项目，再创建任务**

```
先帮我列出项目，然后在 proj_001 下面创建一个训练任务
```

Agent 通常会按顺序执行：

```bash
flux project list --page 1 --limit 50
flux task create --file ./create.json
flux task run --task-id "task_xxx"
```

---

**场景七：下载某个 checkpoint 的模型文件**

```
帮我下载任务 TASK_20260317_129 的 6000 checkpoint 模型文件
```

Agent 通常会按顺序执行：

```bash
flux task model list --task-id "TASK_20260317_129" --checkpoint "6000" --limit 1 --quiet
curl -L "<返回结果中的 policUrlDown>" -o "./model_6000.pt"
```

说明：

- `flux task model list` 会返回目标 checkpoint 的模型信息
- 返回项中的 `policUrlDown` 是可直接下载的预签名 URL
- 当前推荐默认保存到当前项目根路径；若用户指定其他相对路径，优先使用用户路径

---

**场景八：分析训练结果并记录实验笔记（HPO 迭代）**

```
帮我分析任务 task_123 的训练结果，记录到实验笔记中
```

Agent 通常会按顺序执行：

```bash
# 1. 获取训练指标 keys
flux task data keys --task-id "task_123"

# 2. 拉取关键指标数据（如 reward、loss）
flux task data get --task-id "task_123" --data-key "Train/mean_reward" --sampling-mode "precise" --end-time "2026-04-03 12:00:00"
flux task data get --task-id "task_123" --data-key "Train/loss" --sampling-mode "precise" --end-time "2026-04-03 12:00:00"

# 3. 读取当前超参配置
flux task hp get --task-id "task_123"

# 4. Agent 分析数据后，将结论写入任务笔记
flux task note update --task-id "task_123" --note "<h3>Iter-1 实验记录</h3><p><strong>超参：</strong>lr=3e-4, batch_size=256</p><p><strong>结果：</strong>mean_reward=850, loss=0.12, converged at step 2000</p>"

# 5. 后续迭代时可回溯历史笔记
flux task note get --task-id "task_123"
```

> **说明**：在 HPO 迭代流程中，Agent 先通过 `data get` 拉取训练指标、`hp get` 获取超参配置，分析得出结论后，再通过 `note update` 将实验记录写入任务。后续迭代时可通过 `note get` 回溯历史数据进行对比。

---

**场景九：Agent 自动分析 + 调参 + 启动下一轮训练（HPO 自动化）**

```
分析任务 task_123 的训练结果，给出调参建议，直接帮我调参并启动下一轮训练
```

Agent 通常会按顺序执行：

```bash
# 1. 拉取当前超参和训练指标
flux task hp get --task-id "task_123"
flux task data keys --task-id "task_123"
flux task data get --task-id "task_123" --data-key "Train/mean_reward" --sampling-mode "precise" --end-time "2026-04-03 12:00:00"
flux task data get --task-id "task_123" --data-key "Train/loss" --sampling-mode "precise" --end-time "2026-04-03 12:00:00"

# 2. 回溯历史迭代笔记，对比前几轮结果
flux task note get --task-id "task_prev_xxx"

# 3. Agent 分析后记录本轮结论 + 下轮调参建议
flux task note update --task-id "task_123" --note "<h3>Iter-2 实验记录</h3><p><strong>超参：</strong>lr=3e-4, batch_size=256</p><p><strong>结果：</strong>reward=850 (plateau), loss=0.12</p><p><strong>调参建议：</strong>reduce lr to 1e-4, increase batch_size to 512</p>"

# 4. 获取源任务的 checkpoint，用于恢复训练
flux task model list --task-id "task_123" --page 1 --limit 1

# 5. 基于 checkpoint 创建恢复训练任务（trainType=2），JSON 中包含新超参
#    需填写 checkPointFilePath(policUrl)、resumeFromTaskId、resumeFromCheckPoint 等
#    参见「最小可运行 JSON 模版（恢复训练任务）」
flux task create --file ./create-resume-iter3.json

# 6. 如需单独更新超参配置
flux task params update --task-id "task_new_xxx" --file ./hp-iter3.json

# 7. 启动下一轮训练
flux task run --task-id "task_new_xxx"

# 8. 追踪日志
flux task logs --task-id "task_new_xxx" --follow --interval 5s --timeout 30m
```

> **说明**：这是完整的 Agent HPO 自动化闭环——分析指标 → 回溯历史 → 记录结论 → 调参 → 创建恢复训练任务 → 启动训练。Agent 可以根据用户授权程度决定是仅给出建议还是直接执行调参和启动。

---

**场景十：从 Git 仓库 URL 一键创建训练任务（自动发现超参文件和训练入口）**

```
这个仓库 https://github.com/limxdynamics/tron1-rl-isaacgym 帮我创建训练任务
```

Agent 通常会按顺序执行：

```bash
# 1. 浅克隆仓库，获取文件树（不拉取文件内容）
TEMP_DIR=$(mktemp -d)
git clone --depth 1 --branch master --no-checkout https://github.com/limxdynamics/tron1-rl-isaacgym.git "$TEMP_DIR"
cd "$TEMP_DIR" && git ls-tree -r --name-only HEAD
rm -rf "$TEMP_DIR"

# 2. 根据文件树自动识别：
#    - 超参文件（hparamsPath）：匹配 *config*.py / *hparam*.yaml 等规则
#    - 训练入口（mainCodeUri）：匹配 train.py / main.py 等
#    示例结果：
#    hparamsPath = "tron1-rl-isaacgym/legged_gym/envs/pointfoot_flat/pointfoot_flat_config.py"
#    mainCodeUri = "legged_gym/scripts/train.py"

# 3. 如需确认超参内容，checkout 并读取候选文件
cd "$TEMP_DIR" && git checkout HEAD -- legged_gym/envs/pointfoot_flat/pointfoot_flat_config.py

# 4. 查询可用算力资源和镜像
flux task resource list --goods-back-category 3 --page 1 --limit 10
flux task image official

# 5. 构建完整的 task create JSON，写入临时文件
#    - startScript 必须以 gm-run 开头
#    - hparamsPath 从仓库根目录开始（含 clone 目录名）
#    - codeUrl 为 JSON 字符串格式

# 6. 创建任务
flux task create --file ./create-train.json --yes

# 7. 清理临时 JSON 文件
rm ./create-train.json

# 8. 启动任务
flux task run --task-id "TASK_xxx" --yes
```

> **说明**：用户只需提供 Git 仓库地址，Agent 会自动扫描仓库文件树、识别超参文件和训练入口、查询平台可用资源和镜像、构建完整 JSON 并创建任务。整个过程无需用户手动填写 JSON。

---

**场景十一：排查任务启动失败并修复**

```
任务启动报错了，帮我看看怎么回事
```

Agent 通常会按顺序执行：

```bash
# 1. 查看任务当前状态和详情
flux task info --task-id "TASK_xxx"

# 2. 查看任务日志，定位错误原因
flux task logs --task-id "TASK_xxx" --raw --no-request-log

# 3. 根据错误信息诊断问题
#    例如："该算力资源无法挂载个人存储" → personalDataPath 不兼容
#    例如：代码路径错误 → startScript 中的路径需修正

# 4. 获取任务完整信息（edit 前必须先读取全量数据）
flux task info --task-id "TASK_xxx"

# 5. 基于完整数据修改问题字段，写入编辑 JSON
#    注意：edit 是全量覆盖，必须保留所有原有字段
#    taskCodeInfo 中必须包含 taskId

# 6. 提交修复
flux task edit --file ./edit-task.json --yes

# 7. 清理临时文件
rm ./edit-task.json

# 8. 重新启动
flux task run --task-id "TASK_xxx" --yes
```

> **说明**：排查流程的关键是先通过 `task info` 和 `task logs` 定位根因，再通过 `task edit` 修复。**edit 必须提交完整字段**（先读后改），否则未传字段会被后端置空导致数据损坏。

---

**场景十二：多轮训练效果对比分析（跨任务 side-by-side 对比）**

```
训练完了，对比一下调参前后的效果
```

Agent 通常会按顺序执行：

```bash
# 1. 获取两个任务的可用指标 keys
flux task data keys --task-id "TASK_baseline"
flux task data keys --task-id "TASK_tuned"

# 2. 并行拉取两个任务的全量训练指标（已完成任务可用 accelerate 或 precise）
flux task data get --task-id "TASK_baseline" --data-key "Train/mean_reward" --sampling-mode "precise"
flux task data get --task-id "TASK_tuned" --data-key "Train/mean_reward" --sampling-mode "precise"

# 3. 拉取各奖励分项做细粒度对比
flux task data get --task-id "TASK_baseline" --data-key "Episode/rew_tracking_lin_vel" --sampling-mode "precise"
flux task data get --task-id "TASK_tuned" --data-key "Episode/rew_tracking_lin_vel" --sampling-mode "precise"
# ... 其他关键指标（tracking_ang_vel, keep_balance, orientation, collision 等）

# 4. 获取两个任务的超参配置，明确调参差异
flux task hp get --task-id "TASK_baseline"
flux task hp get --task-id "TASK_tuned"

# 5. Agent 汇总分析，生成对比报告表格（各指标的最终值、变化幅度、变化趋势）

# 6. 将对比报告写入调参任务的笔记（HTML 格式）
flux task note update --task-id "TASK_tuned" --note "<h2>对比报告</h2><table>...</table>" --yes
```

> **说明**：跨任务对比的关键是同时拉取两个任务的同口径指标数据，取最终收敛值进行 side-by-side 对比。Agent 会自动计算变化幅度并给出每项指标的评价，最终以 HTML 表格形式写入任务笔记。

---

**场景十三：链式恢复训练（逐步推进 checkpoint 链路）**

```
基于上一轮的结果再训 5000 步看看效果
```

Agent 通常会按顺序执行：

```bash
# 1. 获取源任务的 checkpoint 列表，找到最终 checkpoint
flux task model list --task-id "TASK_prev" --page 1 --limit 20

# 2. 获取源任务完整信息，复用配置（算力、镜像、代码仓库等）
flux task info --task-id "TASK_prev"

# 3. 获取源任务的超参配置
flux task hp get --task-id "TASK_prev"

# 4. 构建恢复训练 JSON（trainType=2）
#    - checkPointFilePath: 使用 model list 返回的 policUrl
#    - checkPointMountPath: 与源任务一致
#    - resumeFromTaskId / resumeFromTaskName / resumeFromCheckPoint: 指向源任务
#    - startScript: 更新 --max_iterations 为新的步数
#    - goodsId / imageId / imageVersion: 复用源任务配置
flux task create --file ./create-resume.json --yes

# 5. 清理临时文件
rm ./create-resume.json

# 6. 如果之前有调参，需要重新应用超参更新（params update 只对当前任务生效）
flux task params update --task-id "TASK_new" --file ./params-update.json --yes
rm ./params-update.json

# 7. 启动新任务
flux task run --task-id "TASK_new" --yes

# 8. 记录训练链路到笔记
flux task note update --task-id "TASK_new" --note "<h2>训练链路</h2><p>TASK_A (baseline) → TASK_B (调参) → <strong>TASK_C (本轮, 继续训练)</strong></p>" --yes
```

> **说明**：链式恢复训练的关键点：(1) 优先复用源任务的 goodsId、imageId、codeUrl 等配置，避免环境不一致；(2) checkPointFilePath 必须使用 `flux task model list` 返回的 `policUrl`，不要手动拼路径；(3) 超参更新（`params update`）只对当前任务生效，每次新建恢复任务都需要重新应用调参配置。

---

**场景十四：实时监控运行中任务的训练进度**

```
看一下这个任务当前的训练效果怎么样
```

Agent 通常会按顺序执行：

```bash
# 1. 确认任务状态（运行中 / 已完成）
flux task info --task-id "TASK_xxx"

# 2. 获取可用的数据 keys
flux task data keys --task-id "TASK_xxx"

# 3. 拉取关键训练指标（运行中任务只能用 precise 模式）
flux task data get --task-id "TASK_xxx" --data-key "Train/mean_reward" --sampling-mode "precise"
flux task data get --task-id "TASK_xxx" --data-key "Train/mean_episode_length" --sampling-mode "precise"

# 4. 拉取各奖励分项，了解策略在各维度的表现
flux task data get --task-id "TASK_xxx" --data-key "Episode/rew_tracking_lin_vel" --sampling-mode "precise"
flux task data get --task-id "TASK_xxx" --data-key "Episode/rew_tracking_ang_vel" --sampling-mode "precise"
flux task data get --task-id "TASK_xxx" --data-key "Episode/rew_keep_balance" --sampling-mode "precise"

# 5. 可选：查看原始日志获取最新迭代信息
flux task logs --task-id "TASK_xxx" --raw --no-request-log

# 6. Agent 分析当前进度：
#    - 当前迭代数 / 总迭代数 → 完成百分比
#    - 曲线趋势（上升 / 收敛 / 震荡）
#    - 与上一轮同期对比
#    - 预估剩余时间
```

> **说明**：运行中的任务只能使用 `precise` 采样模式。Agent 可以根据已有数据点的时间间隔估算剩余训练时间，结合历史任务数据给出"是否达到预期"的判断。

---

### 7.2 环境变量方式（适用于 CI/脚本场景）

如不想将 Key 持久化到本地，可通过环境变量临时注入：

```bash
export FLUX_BASE_URL="https://internal.limxdynamics.com/dev-api"
export FLUX_API_KEY="gm_sk_xxxxxxxxxxxxxxxx"

flux task list
```

---

## 8. 常见问题

### Q1：`flux auth status` 显示 `has_api_key: false`

**原因**：API Key 尚未保存或已被清除。

**解决**：

```bash
flux auth login --api-key "gm_sk_xxxxxxxxxxxxxxxx"
```

---

### Q2：`flux auth whoami` 返回 `PERMISSION_DENIED`

**原因**：API Key 无效、已过期或已被撤销。

**解决**：前往 Flux 平台 → API Key 管理，检查 Key 状态，必要时重新创建并重新登录。

```bash
flux auth logout
flux auth login --api-key "gm_sk_新的Key"
```

---

### Q3：`base_url` 报错或请求失败

**原因**：`base_url` 未设置或地址不正确。

**解决**：

```bash
flux config set base_url "https://internal.limxdynamics.com/dev-api"
flux auth status  # 确认 base_url 已生效
```

---

### Q4：macOS Keychain 弹窗请求访问权限

**原因**：CLI 首次将 API Key 写入系统 Keychain 时，macOS 会弹出授权确认。

**解决**：点击 **允许（Allow）** 即可，后续不再弹出。

---

### Q5：CLI Skill 在 Agent 中没有生效

**检查步骤**：

1. 确认 `~/.cursor/skills/flux-cli/SKILL.md` 文件存在且内容正确。
2. 重启 Cursor。
3. 在 Agent 对话中明确提及 `flux` 或 `flux-cli` 关键词，触发 Skill 激活。

---

### Q6：`flux task stop / delete` 执行时需要输入确认 / 在 Agent 中报 NON_INTERACTIVE

**这是正常行为**。高风险操作（stop / delete / batch stop / batch delete）默认需要二次确认，防止误操作。

**在终端（TTY）中**：会弹出 `[y/N]` 确认提示。

**在非交互环境（Agent / CI / 管道）中**：CLI 检测到 stdin 不是终端后，不会挂起等待输入，而是直接返回退出码 `2` 并输出错误：

```json
{
  "error": {
    "code": "NON_INTERACTIVE",
    "message": "dangerous operation requires confirmation but stdin is not a terminal",
    "hint": "use --yes to skip confirmation in non-interactive mode"
  }
}
```

**解决方法**：加 `--yes` 跳过确认：

```bash
flux --yes task stop --task-id "task_xxx"
flux --yes task delete --task-id "task_xxx"
flux --yes task batch stop --task-ids "id1,id2"
```

> **推荐**：在正式执行前先用 `--dry-run` 预览确认，再去掉 `--dry-run` 执行。

---

### Q7：`flux task storage list` 和其他接口路径规则不一致？

这是预期行为。大多数命令走 `/api/...`，但 `flux task storage list` 使用的是绝对路径接口 `/gm/storage/list`。  
CLI 已内置兼容，无需手动处理路径拼接。

---

## 附录：常用命令速查

### 帮助与版本

| 操作 | 命令 |
|------|------|
| 总览帮助 | `flux --help` |
| 子命令帮助 | `flux task --help`、`flux project --help` |
| 查看版本 | `flux --version` 或 `flux -v` |

### 认证

| 操作 | 命令 |
|------|------|
| 保存 API Key | `flux auth login --api-key "<KEY>"` |
| 检查本地认证 | `flux auth status` |
| 验证服务端连接 | `flux auth whoami` |
| 退出登录 | `flux auth logout` |

### 配置与 Profile

| 操作 | 命令 |
|------|------|
| 设置服务地址 | `flux config set base_url "<URL>"` |
| Profile 列表 | `flux config profile list` |
| 创建/更新 Profile | `flux config profile set <name> --base-url "<URL>" --timeout 30s --retry 3 --concurrency 4` |
| 切换 Profile | `flux config profile use <name>` |
| 临时指定 Profile | `flux --profile <name> task list` |

### 项目

| 操作 | 命令 |
|------|------|
| 项目列表 | `flux project list --page 1 --limit 50` |
| 创建项目 | `flux project create --file ./project-create.json` |
| 项目详情 | `flux project info --project-id "<ID>"` |
| 编辑项目 | `flux project edit --file ./project-edit.json` 或 `--data '{"projectId":"proj_xxx","projectName":"新名称"}'` |
| 删除项目 | `flux project delete --project-id "<ID>"`（需确认，可加 `--yes`） |

### 任务（创建 / 编辑 / 生命周期）

| 操作 | 命令 |
|------|------|
| 查看任务列表 | `flux task list --page 1 --limit 50` |
| 查看任务详情 | `flux task info --task-id "<ID>"` |
| 查看任务 checkpoint 列表 | `flux task model list --task-id "<ID>" --page 1 --limit 20` |
| 查询单个 checkpoint | `flux task model list --task-id "<ID>" --checkpoint "6000" --limit 1` |
| 下载 checkpoint 模型文件 | `flux task model list --task-id "<ID>" --checkpoint "6000" --limit 1 --quiet` → 取 `policUrlDown` 后用 `curl -L ... -o ./model_6000.pt` |
| 创建任务 | `flux task create --file ./create.json` 或 `--data '{"...":"..."}'` |
| 编辑任务 | `flux task edit --file ./edit.json`（需先 `task info` 取全量再改） |
| 复制任务 | `flux task copy --file ./task-copy.json` |
| 运行任务 | `flux task run --task-id "<ID>"` |
| 停止任务 | `flux task stop --task-id "<ID>"`（需确认，可加 `--yes`） |
| 删除任务 | `flux task delete --task-id "<ID>"`（需确认，可加 `--yes`） |

### 任务日志

| 操作 | 命令 |
|------|------|
| 查看任务日志 | `flux task logs --task-id "<ID>"` |
| 实时追踪日志 | `flux task logs --task-id "<ID>" --follow --interval 2s --timeout 1m` |
| 仅输出日志正文（不包 JSON，便于管道） | `flux task logs --task-id "<ID>" --raw` |
| 不向 stderr 输出请求元数据 | `flux task logs ... --no-request-log` |

### 资源 / 镜像 / 存储

| 操作 | 命令 |
|------|------|
| 资源列表（算力） | `flux task resource list --goods-back-category 3 --page 1 --limit 10` |
| 官方镜像 | `flux task image official` |
| 个人镜像 | `flux task image personal --version-status 1 --page 1 --limit 50` |
| 镜像版本 | `flux task image versions --image-id "<ID>"` |
| 个人存储列表 | `flux task storage list --folder-path "personal/"` |

### 数据 / 超参 / 环境

| 操作 | 命令 |
|------|------|
| 图表 Key 列表 | `flux task data keys --task-id "<ID>"` |
| 图表数据查询（加速模式） | `flux task data get --task-id "<ID>" --data-key "Train/mean_reward" --sampling-mode "accelerate" --max-data-points 10000 --end-time "2026-03-19 15:00:00"` |
| 图表数据查询（精细模式） | `flux task data get --task-id "<ID>" --data-key "Train/mean_reward" --sampling-mode "precise" --end-time "2026-03-19 15:00:00"` |
| 图表数据下载 | `flux task data download --task-id "<ID>"` |

> **图表数据采样模式说明**：`--sampling-mode` 为必填参数。已完成/已终止的任务可选 `accelerate`（加速）或 `precise`（精细）；运行中的任务只能使用 `precise`。`--end-time` 可选，不传时后端默认取当前时间，格式为 `YYYY-MM-DD HH:mm:ss`。`--max-data-points` 在加速模式下建议传入（默认 10000），精细模式下可不传。

| 超参读取 | `flux task hp get --task-id "<ID>"` |
| 超参提交 | `flux task params submit --task-id "<ID>" --file ./params.json` |
| 超参更新 | `flux task params update --task-id "<ID>" --data '{"...":"..."}'` |
| 运行环境 | `flux task env get --task-id "<ID>"` |

### 任务标签

| 操作 | 命令 |
|------|------|
| 更新任务标签 | `flux task tag update --task-id "<ID>" --tags "tag1,tag2"` 或 `--file ./tag.json` |
| 查看任务标签 | `flux task tag get --task-id "<ID>"` |
| 用户历史标签列表 | `flux task tag list --limit 200` |

### 任务笔记（实验记录）

| 操作 | 命令 |
|------|------|
| 更新任务笔记 | `flux task note update --task-id "<ID>" --note "<p>实验记录内容</p>"` |
| 通过 JSON 文件更新笔记 | `flux task note update --task-id "<ID>" --file ./note.json` |
| 查看任务笔记 | `flux task note get --task-id "<ID>"` |

> **格式要求**：前端笔记组件使用 `react-quill`（富文本 HTML 编辑器），`taskNote` 必须是 **HTML 片段**（如 `<p>`、`<h3>`、`<ul><li>`、`<strong>`、`<table>` 等），不支持 Markdown。
>
> **适用场景**：每轮训练/HPO 迭代完成后，将超参配置、训练指标、分析结论记录到任务上，便于后续回溯对比实验历史。

### 批量操作（高风险，默认需确认）

| 操作 | 命令 |
|------|------|
| 批量停止 | `flux task batch stop --task-ids "id1,id2,id3"` |
| 批量删除 | `flux task batch delete --task-ids "id1,id2,id3"` |

### 输出与调试

| 操作 | 命令 |
|------|------|
| 人类可读输出 | `flux task list --human` |
| 仅关键字段 | `flux task list --quiet` |
| 预览请求不执行 | `flux task create --file ./create.json --dry-run` |
| 跳过危险确认 | `flux --yes task stop --task-id "<ID>"` |
| 开启调试日志 | `flux task list --debug` |
| 日志写入文件 | `flux task list --log-file ./flux.log` |
| 临时覆盖 base_url / api-key（不落盘） | `flux --base-url "<URL>" --api-key "<KEY>" auth whoami` |

### VLA 任务（Vision-Language-Action 训练）

> **VLA 是独立于 RL（`flux task`）的训练链路**，命令在 `flux vla` 下，后端走 `/api/vla/*`。不要把 RL 的 `flux task` 用在 VLA 任务上，反之亦然。

与 RL 的关键差异（易踩坑）：

- **创建/编辑是单段扁平 `{ "taskBaseInfo": {...} }`**，无 `taskCodeInfo`；配置字段（`modelFamily` / `finetuneMode` / `baseModelId` / `datasetIds` / `paramOverrides`）平铺在 `taskBaseInfo` 内。
- **编辑是 `PUT /vla/task/config`，且为部分更新**（后端 `exclude_unset`）：只传要改的字段即可，**不必**像 RL 那样先 `info` 回读全量再合并。
- **启动/停止是 `start` / `stop`**（不是 RL 的 `run`）；**删除是路径参数** `DELETE /vla/task/{id}`。
- **算力类目使用 `3`**：flux-cli `1.1.0` 的 `flux vla --help` 与实际接口均表明 VLA、RL 共用资源目录，使用 `flux task resource list --goods-back-category 3`，取 `goodsId` / `goodsBackId` / `goodsBackSku.gpuNum`。
- **`startScript` 通常省略**：底模配了 `base_config_{full|lora}` 时后端会忽略提交值并自动按 `torchrun` 拼装训练命令，再用 `gm-vla-run` 包一层；仅老底模才回退用用户脚本。
- **`paramOverrides` 有白名单**：key 必须在所选底模 `exposedParams[finetuneMode]` 暴露的参数内，否则后端拒绝（用 `flux vla base-model info` 查看暴露参数）。
- VLA 暂无 copy / batch / tag / note / hp / env / storage 子命令（后端无对应接口）。

任务（创建 / 编辑 / 生命周期）

| 操作 | 命令 |
|------|------|
| 任务列表 | `flux vla task list --page 1 --limit 50`（可加 `--project-id "<ID>"` / `--task-name "<kw>"`） |
| 任务详情 | `flux vla task info --task-id "<ID>"` |
| 创建任务 | `flux vla task create --file ./vla-create.json` 或 `--data '{"taskBaseInfo":{...}}'` |
| 编辑任务（部分更新） | `flux vla task edit --data '{"taskId":"<ID>","taskBaseInfo":{"taskName":"new"}}'` |
| 启动任务 | `flux vla task start --task-id "<ID>"` |
| 停止任务 | `flux vla task stop --task-id "<ID>"`（需确认，可加 `--yes`） |
| 删除任务（软删） | `flux vla task delete --task-id "<ID>"`（需确认，可加 `--yes`） |
| checkpoint 列表 | `flux vla task models --task-id "<ID>" --page 1 --limit 20` |
| 下载 checkpoint 模型文件 | `flux vla task models --task-id "<ID>" --limit 20` → 取目标行 `policUrlDown` 后 `curl -L "<policUrlDown>" -o ./model_3000.pt` |

任务日志 / 训练曲线

| 操作 | 命令 |
|------|------|
| 查看日志 | `flux vla task logs --task-id "<ID>"`（支持 `--follow` / `--raw` / `--no-request-log`） |
| 图表 Key 列表 | `flux vla task data keys --task-id "<ID>"` |
| 图表数据查询 | `flux vla task data get --task-id "<ID>" --data-key "loss" [--start-time "2026-06-29T00:00:00" --end-time "2026-06-29T12:00:00"]` |

项目

| 操作 | 命令 |
|------|------|
| 项目列表 | `flux vla project list --page 1 --limit 50`（可加 `--project-name "<kw>"`） |
| 创建项目 | `flux vla project create --data '{"projectName":"my-vla-project"}'` |
| 项目详情 | `flux vla project info --project-id "<ID>"`（返回含 `taskCount`） |
| 编辑项目 | `flux vla project edit --data '{"projectId":"<ID>","projectName":"新名称"}'` |
| 删除项目 | `flux vla project delete --project-id "<ID>"`（需确认，可加 `--yes`） |

资源查询（创建任务前的下拉数据，只读）

| 操作 | 命令 |
|------|------|
| 数据集列表 / 详情 | `flux vla dataset list` / `flux vla dataset info --dataset-id "<ID>"` |
| 底模列表 / 详情 | `flux vla base-model list` / `flux vla base-model info --base-model-id "<ID>"`（含 `modelFamily` / `supportedFinetune` / `exposedParams`） |
| 镜像列表 / 详情 | `flux vla image list [--scope all]` / `flux vla image info --image-id "<ID>"` |
| 算力（共享目录，类目=3） | `flux task resource list --goods-back-category 3` |

最小可运行 JSON 模板（VLA 训练任务）：

```json
{
  "taskBaseInfo": {
    "projectId": "VPRO_xxx",
    "taskName": "pi05-lora-v1",
    "goodsId": "ESKxxx",
    "goodsBackId": "BACKxxx",
    "gpuNum": 1,
    "imageId": "VIMGxxx",
    "modelFamily": "pi05",
    "finetuneMode": "lora",
    "baseModelId": "BMxxx",
    "datasetIds": ["DSxxx", "DSyyy"],
    "paramOverrides": { "train_dataloader.batch_size": 32, "optim_wrapper.optimizer.lr": 0.0001 }
  }
}
```

> **不要填 `startScript`**：底模配了 `base_config_*` 时后端会忽略它并自动拼 torchrun。`paramOverrides` 的 key 必须在底模 `exposedParams[finetuneMode]` 白名单内（用 `flux vla base-model info` 查），上面 `train_dataloader.batch_size` 仅为示例。

Agent 创建 VLA 任务的推荐流程：

```bash
flux vla project list                              # 或 flux vla project create → 得 projectId
flux vla base-model list                           # 得 baseModelId，并据 supportedFinetune 定 finetuneMode
flux vla dataset list                              # 得 datasetIds
flux vla image list [--scope all]                  # 得 imageId
flux task resource list --goods-back-category 3    # 得 goodsId / goodsBackId / goodsBackSku.gpuNum
flux vla task create --file ./vla-create.json --dry-run   # exit 10 通过 → 去掉 --dry-run 正式执行 → 删除临时 JSON
flux vla task start --task-id "<ID>"               # 用户明确要求才启动，避免误触发计费
flux vla task logs --task-id "<ID>" --follow
```
