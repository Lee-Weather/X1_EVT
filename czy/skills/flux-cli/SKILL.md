---
name: flux-cli
description: "Operate the official flux-cli successor to gm-cli for RL and VLA projects, tasks, authentication, logs, checkpoints, data, and safe automation. Also use for the F1/X1 project extensions: Isaac Gym replay video and CSV export, recommended GM resources and images, account rotation, GitHub/GitLab version mirroring, periodic training monitoring, artifact download, and experiment-record handoff."
---

# flux-cli

## 适用范围
用 `flux` 完成以下工作流：
- 认证：`flux auth login/logout/status/whoami`
- 配置与 profile：`flux config ...`
- 项目管理：`flux project ...`（list/create/edit/delete/info）
- 任务管理（RL）：`flux task ...`（create/edit/copy/list/info/run/stop/delete/logs/resource/image/storage/data/hp/env/params/tag/note/batch）
- VLA 训练：`flux vla ...`（task / project / dataset / base-model / image）——见文末「VLA 命令（Vision-Language-Action 训练）」章节

## 安全与约束
- 不要在对话输出中回显用户的 `api-key` 或完整密钥内容。
- **Agent 场景**：当 Agent 通过 shell 工具执行命令时（非交互式终端），必须始终加 `--yes`，因为 Agent 无法响应交互式确认提示。用户在对话中下达指令本身即视为授权确认。
- **非交互环境（Agent / CI / 管道）**：CLI 检测到 stdin 不是终端后，危险操作不会挂起等待输入，而是直接返回退出码 `2`（`NON_INTERACTIVE` 错误）。Agent 执行危险操作时**必须加 `--yes`**。
- **写操作推荐先 `--dry-run`**：所有 create/edit/run/stop/delete 等写操作支持 `--dry-run`，预览请求而不实际执行。推荐流程：`--dry-run` 确认 → 去掉 `--dry-run` 正式执行。
- 涉及文件路径一律使用相对路径（例如 `--file ./payload.json`）。
- Agent 生成的临时 JSON 文件（如 `create-*.json`、`edit-*.json`、`copy-*.json` 等），在对应的 CLI 命令执行成功后应**立即删除**，避免在工作目录中残留过期的临时文件。
- 不要回显 `policUrlDown`、`videoUrlDown`、Bearer token，或包含其 Base64 编码的 `startScript`。读取 `task info` 时只输出所需字段；完整结果可能含临时凭据。
- PowerShell 中优先解析 `flux.cmd` 的绝对路径；如果裸 `flux` 被别名占用，不要调用该别名。
- 官方命令已改名为 `flux`，但 RL 任务的 `taskCodeInfo.startScript` 仍必须以 `gm-run` 开头；不要改成 `flux-run`。
- 代码推送（GitHub）：训练版本启动前确认 `origin` 已包含训练要用的 commit；平时可按开发需要随时推送。完整规则见 [references/git-mirror.md](references/git-mirror.md)。

## 官方能力与项目扩展路由

- 安装、认证、RL/VLA 命令、退出码和完整示例：按需读取 [FluxCLISkill-Guide.md](FluxCLISkill-Guide.md)。
- F1/X1 Isaac Gym 回放、视频与 CSV：执行前完整读取 [references/replay.md](references/replay.md)。
- 镜像、算力和字段选择：创建或恢复任务前读取 [references/resources.md](references/resources.md)。
- 多账号额度管理与自动切换：涉及账号选择或余额不足时读取 [references/accounts.md](references/accounts.md)；需**携带 checkpoint 换账号续训**（旧账号任务/项目的 OSS 路径跨账号不可见）时，按同文件的「跨账号续训（git 内置 checkpoint 路线）」执行。
- GitHub/GitLab 版本镜像：训练版本即将启动、需要同步代码或配置 Git 远程时读取 [references/git-mirror.md](references/git-mirror.md)。
- 训练监控、ETA、产物下载与实验记录：需要监控或收尾时读取 [references/monitoring.md](references/monitoring.md)。
- 保留 `czy/skills/gm-cli/` 作为迁移期回滚基线；新操作优先使用 `flux`，不要同时用两套 CLI 修改同一任务。

## 帮助与版本
- 总览：`flux --help`
- 子命令：`flux <command> --help`
- 版本：`flux --version`（或 `flux -v`，不使用 `flux version`）

## 执行前快速探测（固定步骤）
在执行任何写操作前，先跑以下 3 条命令确认 CLI 能力与命令可用性：
1. `flux --help`
2. `flux task --help`
3. `flux project --help`

建议：
- 若任一命令报错，先不要继续执行创建/编辑/删除类操作。
- 若子命令缺失，优先按当前 CLI 版本能力降级执行或提示用户升级。

## 配置优先级
按优先级覆盖：`CLI flags > 环境变量 > 配置文件`。

常用环境变量：
- `FLUX_PROFILE`
- `FLUX_BASE_URL` / `FLUX_API_KEY` / `FLUX_TIMEOUT` / `FLUX_RETRY` / `FLUX_CONCURRENCY`

说明：
- 默认：CLI 请求 `base_url + /api + endpoint`。
- 绝对路径模式：个别命令（如 `flux task storage list`）会直接请求 `base_url + endpoint`（不自动拼 `/api`）。

## 首次上手（推荐步骤）
1. 登录保存 API Key（优先 Keychain，失败回落 config）：
   - `flux auth login --api-key "<YOUR_KEY>"`
2. 验证：
   - `flux auth status`（本地）
   - `flux auth whoami`（请求服务端）

如需临时覆盖且不落盘：
- `flux --base-url "https://..." --api-key "<KEY>" auth whoami`

## Profile（多环境）
- 列表：`flux config profile list`
- 创建/更新：
  - `flux config profile set dev --base-url "https://..." --timeout 30s --retry 3 --concurrency 4`
- 切换：`flux config profile use dev`
- 临时指定：`flux --profile dev task list` 或 `FLUX_PROFILE=dev flux task list`

## Task 常用操作
- 列表：`flux task list --page 1 --limit 50`
- 按状态筛选：`flux task list --status "3"`（运行中）或 `flux task list --status "3,5,6"`（多状态）
- 按项目筛选：`flux task list --project-id "PRO_xxx"`
- 按标签筛选：`flux task list --tag "baseline"`（模糊匹配）
- 按名称筛选：`flux task list --task-name "v5"`（模糊匹配）
- 组合筛选：`flux task list --project-id "PRO_xxx" --status "3" --limit 20`
- 详情：`flux task info --task-id "task_xxx"`
- Checkpoint 列表：`flux task model list --task-id "task_xxx" --page 1 --limit 20`
- 单 checkpoint 查询：`flux task model list --task-id "task_xxx" --checkpoint "3000" --limit 1`
- 复制：`flux task copy --file ./copy.json`
- 运行：`flux task run --task-id "task_xxx"`
- 停止：`flux --yes task stop --task-id "task_xxx"`（Agent 必须加 `--yes`，推荐先 `--dry-run`）
- 删除：`flux --yes task delete --task-id "task_xxx"`（Agent 必须加 `--yes`，推荐先 `--dry-run`）
- 更新笔记：`flux task note update --task-id "task_xxx" --note "<p>实验记录内容</p>"` 或 `--file ./note.json`
- 查看笔记：`flux task note get --task-id "task_xxx"`

日志：
- 单次：`flux task logs --task-id "task_xxx"`
- 追踪：`flux task logs --task-id "task_xxx" --follow --interval 2s --timeout 1m`
- 仅输出日志正文（不包 JSON）：`flux task logs --task-id "task_xxx" --raw`；管道/重定向时常用。
- 不向 stderr 打请求元数据：`flux task logs ... --no-request-log`；与 `--raw` 搭配可得到纯净日志流。

资源/镜像/存储：
- 资源列表：`flux task resource list --goods-back-category 3 --page 1 --limit 10`
  > 返回字段说明：`goodsId` 对应 `taskBaseInfo.goodsId`（填任务时使用此值）；`goodsBackId` 是后台 SKU 标识，**不可**混用。
- 官方镜像：`flux task image official`
- 个人镜像：`flux task image personal --version-status 1 --page 1 --limit 50`
- 镜像版本：`flux task image versions --image-id "img_xxx"`
  > 返回字段说明：`id` 对应 `taskBaseInfo.imageVersion`（填任务时使用此值），`versionCode` 仅为可读标识，**不可**用于 `imageVersion` 字段。
- 个人存储：`flux task storage list --folder-path "personal/"`

图表/超参/环境：
- 图表 keys：`flux task data keys --task-id "task_xxx"`
- 图表数据（加速模式）：`flux task data get --task-id "task_xxx" --data-key "Train/mean_reward" --sampling-mode "accelerate" --max-data-points 10000 --end-time "2026-03-19 15:00:00"`
- 图表数据（精细模式）：`flux task data get --task-id "task_xxx" --data-key "Train/mean_reward" --sampling-mode "precise" --end-time "2026-03-19 15:00:00"`
  > **采样模式说明**：已完成/已终止的任务可选 `accelerate`（加速）或 `precise`（精细）；运行中的任务只能使用 `precise` 模式。`--end-time` 可选，不传时后端默认取当前时间。
- 图表下载：`flux task data download --task-id "task_xxx"`
- 超参读取：`flux task hp get --task-id "task_xxx"`
- 运行环境：`flux task env get --task-id "task_xxx"`

## 模型文件下载（pt）
适用场景：
- 用户要下载某个任务的 checkpoint 对应模型文件

当前方式：
- `flux` 目前已有 `flux task model list`，可调用 `POST /api/task/model/info`
- 取对应 checkpoint 中的`policUrlDown`链接，再用 `curl` 下载，默认保存到当前项目根路径下

任务打标签：
- 更新标签：`flux task tag update --task-id "task_xxx" --tags "tag1,tag2"` 或 `--file ./tag.json`
- 查看任务标签：`flux task tag get --task-id "task_xxx"`
- 用户历史标签列表：`flux task tag list --limit 200`

任务笔记（实验记录）：
- 更新笔记：`flux task note update --task-id "task_xxx" --note "<p>iter-1: lr=3e-4, reward=850, converged at step 2000</p>"`
- 通过 JSON 文件更新：`flux task note update --task-id "task_xxx" --file ./note.json`
- 查看笔记：`flux task note get --task-id "task_xxx"`
  > **格式要求**：前端笔记组件使用 `react-quill`（富文本 HTML 编辑器），`taskNote` 存储的是 **HTML 片段**，不是 Markdown 或纯文本。Agent 生成笔记时必须使用 HTML 标签（如 `<p>`、`<h3>`、`<ul><li>`、`<strong>`、`<table>` 等），否则在 Web 端会原样显示而非渲染。
  > **适用场景**：每轮训练/HPO 迭代完成后，将超参配置、训练指标、分析结论记录到任务上，便于后续回溯对比。

> **说明**：任务分享（生成分享链接）需在 Web 端操作，CLI 未提供对应命令。

## Project 常用操作
- 列表：`flux project list --page 1 --limit 50`
- 创建：`flux project create --file ./project-create.json`
- 编辑（如修改名称）：`flux project edit --file ./project-edit.json` 或 `--data '{"projectId":"proj_xxx","projectName":"新名称"}'`
- 删除：`flux project delete --project-id "proj_xxx"`（会二次确认，可加 `--yes` 跳过）
- 详情：`flux project info --project-id "proj_xxx"`

## create/edit/params 的请求体输入（JSON）
这些命令通过 `--data` 或 `--file` 提供 JSON（两者二选一）。
- `flux task create --data '{"...":"..."}'`
- `flux task create --file ./create.json`
- `flux task edit --file ./edit.json`

### `taskCodeInfo.startScript` 强限制

> **硬限制：`startScript` 只能填写 `gm-run` 命令。**

- 合法形式：`gm-run ...`
- 不允许：`python train.py`、`bash xxx.sh`、`sh xxx.sh`、`./run.sh`、`source ... && ...`、`cd ... && ...` 等非 `gm-run` 启动方式
- Agent 在生成 `create/edit` JSON 时，若发现 `startScript` 不是以 `gm-run` 开头，应先改写为 `gm-run ...` 或提示用户修正后再执行

超参：
- `flux task params submit --task-id "task_xxx" --file ./params.json`
- `flux task params update --task-id "task_xxx" --data '{"...":"..."}'`

## Agent 创建训练任务时自动解析 Git 超参文件路径

> **当用户要求创建训练任务并提供了 Git 仓库地址时，Agent 应先主动扫描仓库自动发现超参文件路径（`hparamsPath`）；仅在扫描未识别到候选文件时，再引导用户手动填写或留空。**

### 触发条件

满足以下任一条件时触发此工作流：
- 用户提供了 Git 仓库地址并要求创建训练任务
- 用户明确要求解析/扫描仓库中的超参文件
- 构建 task create JSON 时 `hparamsPath` 未知

### 工作流步骤

#### 第 1 步：提取 Git 仓库信息

从用户提供的 `codeUrl` 中提取：
- `repo_url`：仓库地址（如 `https://github.com/org/repo.git`）
- `branch`：分支名（如 `main`），取自 `versionName`

#### 第 2 步：获取仓库文件树

使用浅克隆 + ls-tree 获取完整文件列表（不拉取文件内容，速度快）：

```bash
TEMP_DIR=$(mktemp -d)
git clone --depth 1 --branch <branch> --no-checkout <repo_url> "$TEMP_DIR" 2>/dev/null
cd "$TEMP_DIR" && git ls-tree -r --name-only HEAD
rm -rf "$TEMP_DIR"
```

**认证处理**：
- 公开仓库：直接 clone
- 私有仓库 clone 失败时：提示用户提供 Token，使用 `https://oauth2:<token>@host/path` 格式注入
- 也可尝试利用本地已配置的 SSH Key 或 Git credential helper

#### 第 3 步：应用超参文件识别规则

对文件树应用以下规则，按置信度排序输出候选列表：

**高置信度（high）——优先推荐**：
- 文件名包含关键词：`hparam`、`hyper`、`hyperparam`
- 位于超参专用目录下：`hparams/`、`hyperparams/`
- 文件名为 `train.yaml`、`train.yml`、`train_config.*`、`training_config.*`

**中置信度（medium）——推荐**：
- 位于配置目录下（`configs/`、`conf/`、`config/`、`cfg/`、`params/`、`settings/`）且扩展名为 `.yaml`、`.yml`、`.json`、`.toml`、`.cfg`、`.ini`
- 根目录下文件名含 `config`、`cfg`、`param`、`setting`、`args`、`options` 且扩展名为 `.yaml`、`.yml`、`.json`、`.toml`、`.py`
- Python 配置文件：`config.py`、`args.py`、`options.py`、`params.py`、`settings.py`
- Hydra 框架标志：`conf/` 下的 `.yaml` 文件

**低置信度（low）——仅当无更高候选时展示**：
- 根目录下的通用 `.yaml`/`.yml`/`.json` 文件（排除已知非超参文件后）
- 深层嵌套（>3 层目录）的配置文件

**强制排除（不作为候选）**：
- 目录：`node_modules/`、`.git/`、`__pycache__/`、`.venv/`、`venv/`、`env/`、`.tox/`、`dist/`、`build/`、`.eggs/`、`*.egg-info/`、`.github/`、`.gitlab-ci/`、`.circleci/`
- 依赖/构建文件：`package.json`、`package-lock.json`、`tsconfig.json`、`Dockerfile`、`docker-compose*.yml`、`setup.py`、`setup.cfg`、`pyproject.toml`、`requirements*.txt`、`Pipfile`、`Pipfile.lock`、`poetry.lock`、`Cargo.toml`、`go.mod`、`go.sum`、`Makefile`、`CMakeLists.txt`
- 文档/元数据：`*.md`、`*.rst`、`LICENSE*`、`MANIFEST.in`、`.gitignore`、`.gitmodules`
- Lint/测试配置：`.pre-commit-config.yaml`、`.flake8`、`.pylintrc`、`tox.ini`、`pytest.ini`、`mypy.ini`
- CI/CD：`.github/workflows/*.yml`、`.gitlab-ci.yml`、`.travis.yml`、`Jenkinsfile`

#### 第 4 步（可选）：预览候选文件内容辅助判断

当存在多个中/高置信度候选且 Agent 无法仅凭路径确定时，checkout 并读取候选文件内容：

```bash
cd "$TEMP_DIR" && git checkout HEAD -- <candidate_path> && cat <candidate_path>
```

置信度提升依据（文件内含以下关键键名）：
- RL 超参：`learning_rate`、`lr`、`gamma`、`discount`、`reward`、`max_iterations`、`num_envs`、`num_steps`、`ppo`、`sac`、`dqn`
- 通用 ML 超参：`batch_size`、`num_epochs`、`optimizer`、`hidden_size`、`dropout`、`weight_decay`、`scheduler`

排除依据（文件内容为非超参配置）：
- 环境变量/secrets 配置（`DATABASE_URL`、`SECRET_KEY`、`AWS_`）
- 日志配置（`logging`、`handlers`、`formatters`）
- 部署/基础设施配置（`replicas`、`ports`、`volumes`、`services`）

#### 第 5 步：向用户确认

将候选列表按置信度排序展示，格式：

```
在仓库 your-org/your-repo (main) 中发现以下超参文件候选：

1. [高] configs/train.yaml — 位于 configs/ 目录，文件名含 train
2. [中] config.py — 根目录 Python 配置文件
3. [中] params/reward.json — 位于 params/ 目录

请确认使用哪个作为 hparamsPath？（输入序号或自定义路径）
```

**特殊情况处理**：
- 仅 1 个高置信度候选：直接建议使用，告知用户可更改
- 无候选：告知用户仓库中未发现明显的超参文件，请手动指定 `hparamsPath` 或留空
- 用户主动指定了路径：跳过扫描，直接使用用户指定值

#### 第 6 步：填入 create JSON 并继续

用户确认后将路径填入 `taskCodeInfo.hparamsPath`，继续正常的 task create 流程。

> **路径格式要求**：`hparamsPath` 中的文件路径必须从 **Git 仓库项目名（clone 后的目录名）** 开始，例如 `pointfoot-legged-gym/configs/train.yaml`，而不是仓库内的相对路径 `configs/train.yaml`。

### 同时发现 mainCodeUri 和 startScript（可选增强）

扫描文件树时可同时识别训练入口脚本，减少用户手填工作量：
- 高置信度入口脚本：`train.py`、`main.py`、`run.py`、`run_training.py`
- 中置信度入口脚本：根目录或 `scripts/` 下文件名含 `train`、`run` 的 `.py` 文件
- 发现后建议填入 `mainCodeUri`，并自动生成 `startScript`：`gm-run <mainCodeUri> --task=<task_name> --headless`

### 完整示例流程

```
用户：帮我创建一个训练任务，代码仓库 https://github.com/my-org/rl-project.git，main 分支

Agent 执行：
  1. git clone --depth 1 --branch main --no-checkout → 获取文件树
  2. 识别候选：configs/train.yaml [高]、config.py [中]
  3. 同时发现入口脚本：train.py
  4. 向用户确认：
     "发现超参文件 your-repo/configs/train.yaml（高置信度），训练入口 train.py，是否使用？"
  5. 用户确认 → 构建 JSON：
     hparamsPath="your-repo/configs/train.yaml"
     mainCodeUri="your-repo/legged_gym/scripts/train.py"
     startScript="gm-run your-repo/legged_gym/scripts/train.py --task=pointfoot_flat --headless"
  6. flux task create --file ./create-train.json
  7. 清理临时 JSON 文件
```

## 最小可运行 JSON 模版（训练任务）
下面是一个“可创建并可运行”的最小模板（请替换示例值）：

```json
{
  "taskBaseInfo": {
    "projectId": "proj_xxx",
    "taskType": "1",
    "trainType": "1",
    "taskName": "mvp-train-task",
    "taskDescription": "created by flux-cli",
    "taskTag": [],
    "goodsId": "goods_xxx",
    "imageId": "BJX00000001",
    "imageVersion": "V000057",
    "personalDataPath": "/personal"
  },
  "taskCodeInfo": {
    "codeType": "2",
    "codeUrl": "[{\"codeUrl\":\"https://github.com/your-org/your-repo.git\",\"versionType\":\"1\",\"versionName\":\"main\"}]",
    "mainCodeUri": "your-repo/legged_gym/scripts/train.py",
    "hparamsPath": "your-repo/configs/train.yaml",
    "startScript": "gm-run your-repo/legged_gym/scripts/train.py --task=pointfoot_flat --headless",
    "isOpen": "1"
  },
  "runtimeReminderConfig": {
    "enableRuntimeReminder": false,
    "reminderDurations": []
  }
}
```

建议创建与运行步骤：
- `flux task create --file ./create-train.json`
- 从返回结果取 `taskId`，执行 `flux task run --task-id "task_xxx"`
- `flux task logs --task-id "task_xxx" --follow`

## 最小可运行 JSON 模版（恢复训练任务）
下面是一个“基于已有任务 checkpoint 恢复训练”的最小模板（请替换示例值）：

```json
{
  "taskBaseInfo": {
    "projectId": "proj_xxx",
    "taskType": "1",
    "trainType": "2",
    "taskName": "resume-train-task",
    "taskDescription": "resume from existing checkpoint",
    "taskTag": [],
    "goodsId": "goods_xxx",
    "imageId": "BJX00000001",
    "imageVersion": "V000057",
    "personalDataPath": "/personal"
  },
  "taskCodeInfo": {
    "codeType": "2",
    "codeUrl": "[{\"codeUrl\":\"https://github.com/your-org/your-repo.git\",\"versionType\":\"1\",\"versionName\":\"main\"}]",
    "mainCodeUri": "your-repo/legged_gym/scripts/train.py",
    "hparamsPath": "your-repo/configs/train.yaml",
    "startScript": "gm-run your-repo/legged_gym/scripts/train.py --task=pointfoot_flat --headless --max_iterations=3000",
    "isOpen": "1",
    "checkPointFilePath": "upload/2026/3/17/model_3000_xxx.pt",
    "checkPointMountPath": "your-project-root/",
    "resumeFromTaskId": "task_source_xxx",
    "resumeFromTaskName": "source-task-name",
    "resumeFromCheckPoint": "3000"
  },
  "runtimeReminderConfig": {
    "enableRuntimeReminder": false,
    "reminderDurations": []
  }
}
```

建议恢复步骤：
- **先获取任务列表**：执行 `flux task list --page 1 --limit 50`，展示任务列表供用户选择。
- **用户选择源任务**：根据列表中的 `taskId`、任务名称、任务状态等，让用户确认或选择要恢复的源任务（得到 `task_source_xxx`）。
- **再获取该任务的 checkpoint**：执行 `flux task model list --task-id "task_source_xxx" --page 1 --limit 20`，找到目标 checkpoint。
- 将返回结果中的 `policUrl` 填入 `taskCodeInfo.checkPointFilePath`
- 将 `resumeFromTaskId` / `resumeFromTaskName` / `resumeFromCheckPoint` 与源任务、源 checkpoint 保持一致
- `flux task create --file ./create-resume-train.json`
- 如需启动，再执行 `flux task run --task-id "task_xxx"`

恢复训练任务的软提示：
1. 优先复用源任务的 `goodsId`、`imageId`、`imageVersion`、`codeUrl`、`mainCodeUri`、`hparamsPath`，避免环境不一致导致恢复失败。
2. `checkPointFilePath` 应优先使用 `flux task model list` 返回的 `policUrl`，不要手写猜测路径。
3. 若用户只是想“基于 checkpoint 新建恢复任务”，默认先 `create`，不要自动 `run`；只有用户明确要求时才执行运行。

### 关于本地 zip 压缩包上传（`codeType=1`）—— 不支持

> **重要限制：Agent / flux-cli 不支持本地上传 zip 压缩包的方式创建训练任务。**

原因：
- `codeType=1` 要求代码以 zip 包形式先上传至平台对象存储（OSS），再将返回的 OSS 路径填入 `codeUrl`。
- 这一上传过程依赖 Web 端的文件上传接口，flux-cli 及 Agent 均未实现本地文件上传到 OSS 的能力。
- 因此，即使在 JSON 中指定 `codeType=1`，Agent 也无法帮用户完成本地压缩包的上传流程。

**Agent 应遵循以下规则：**
1. 当用户要求以本地 zip/压缩包方式创建训练任务时，应**明确告知不支持**，并建议用户改用 Git 仓库方式（`codeType=2`）。
2. 若用户坚持使用 zip 方式，应引导用户前往 Web 平台手动上传。
3. 创建训练任务时，**默认且唯一推荐的代码方式为 Git 仓库**（`codeType=2`），参见上方模板。

### 私有 Git 仓库需要配置账号和 Token

> **重要提示：当用户使用私有 Git 仓库（GitHub / GitLab）创建训练任务时，必须确认已在平台配置 Git 凭证。**

背景：
- 任务运行时，后端会自动从用户资料中读取 `github_name` + `github_token`（或 `gitlab_name` + `gitlab_token`）来拉取私有仓库代码。
- 这些凭证通过 Web 平台的「个人设置 → Git 信息」页面配置（对应后端接口 `POST /api/user/editGitInfo`）。
- **flux-cli 当前没有管理 Git 凭证的命令**，无法通过 CLI 直接设置。

**Agent 应遵循以下规则：**
1. 当用户提供的 `codeUrl` 为私有仓库时，**必须主动询问**用户是否已在平台配置对应的 Git 账号和 Token。
2. 若用户尚未配置，应引导其前往 Web 平台「个人设置 → Git 信息」页面填写：
   - GitHub 仓库需填写：`GitHub 账号名` 和 `GitHub Token`（Personal Access Token）
   - GitLab 仓库需填写：`GitLab 账号名` 和 `GitLab Token`
3. **不要在 task create 的 JSON 中传递 Git 凭证**——凭证不属于任务请求体，由后端在运行时自动关联。
4. 若用户不确定仓库是否为私有，建议先确认仓库可访问性后再创建任务，避免任务运行时因拉取代码失败而报错。

### `flux task edit` 必须提交完整数据（全量更新）

> **重要限制：后端 `edit_task_dao` 采用全字段覆盖更新（`model_dump()` → `UPDATE`），不支持部分字段更新。**
> **如果只提交用户想改的字段，其余未传字段会被 Pydantic 默认值（`None`/`''`）覆盖，导致 `task_status`、`userId`、`queue` 等关键数据丢失，接口返回 500 或数据损坏。**

**Agent 执行 `flux task edit` 的强制流程：**

1. **先读后改**——执行编辑前，必须先通过 `flux task info --task-id "task_xxx"` 获取任务当前完整数据。
2. **合并生成完整 JSON**——以 `task info` 返回的 `taskBaseInfo` + `taskCodeInfo` 为基础，仅替换用户明确要求修改的字段，其余字段保持原值。
3. **补齐 `taskCodeInfo.taskId`**——编辑 JSON 的 `taskCodeInfo` 中必须包含 `taskId`（与 `taskBaseInfo.taskId` 一致），否则后端代码表更新会因主键为空而失效。
4. **写出完整 JSON 文件**——将合并后的完整 payload 写入 `--file`，再执行 `flux task edit --file ./edit.json`。

**合并时需特别注意的字段：**
- `taskBaseInfo.taskStatus`：必须保留原值，绝不能被默认值覆盖
- `taskBaseInfo.userId`：必须保留原值
- `taskBaseInfo.goodsId` / `goodsBackId`：保留原值或替换为用户指定的新值
- `taskBaseInfo.imageId` / `imageVersion`：保留原值或替换为用户指定的新值
- `taskBaseInfo.taskTag`：保留原值（数组格式）
- `taskCodeInfo` 的所有字段：保留原值，仅覆盖用户明确修改的部分

**示例流程（Agent 修改算力资源和镜像）：**
```bash
# 1. 读取现有任务
flux task info --task-id "TASK_xxx"

# 2. Agent 在本地合并 JSON：以 info 返回为基础，替换 goodsId/imageId/imageVersion
# 3. 写出完整 edit JSON 文件（包含所有原有字段 + 修改字段）

# 4. 执行编辑
flux task edit --file ./edit-task.json
```

## Task 参数软限制
说明：
- 这是 **skill 软限制**（执行前检查并提示），不是后端强校验的替代。
- 字段命名优先使用后端 alias（小驼峰），如 `taskBaseInfo`/`taskCodeInfo`/`taskId`。
- 后端在 task 流程中并未统一显式调用 `validate_fields()`；因此本节采用：
  - `STRICT`：强烈建议拦截（明显会失败或风险极高）
  - `WARN`：仅提示（业务建议或 Agent 侧保护）

### 1) `flux task create` -> `POST /api/task/create` -> `TaskCreateModel`
`STRICT`：
- 顶层必须有：`taskBaseInfo`（object）、`taskCodeInfo`（object）
- `taskBaseInfo.projectId`：必填，长度 `1..20`
- `taskBaseInfo.taskName`：必填，长度 `1..100`
- `taskCodeInfo.codeType`：必填，长度 `1..2`
- `taskCodeInfo.startScript`：若传入，必须是 `gm-run` 命令，且必须以 `gm-run` 开头

`WARN`：
- `taskBaseInfo.taskDescription`：可选，最大 `1000`
- `taskBaseInfo.goodsId`：建议必填，最大 `20`（业务侧常见硬依赖）
- `taskBaseInfo.userId`：可选；服务端会按当前登录用户覆盖，不建议依赖请求体值
- `taskCodeInfo.codeUrl`：可选，最大 `1000`
- `taskCodeInfo.mainCodeUri`：可选，最大 `255`
- `taskCodeInfo.runParams`：可选，最大 `255`
- `taskCodeInfo.urdfPath` / `hparamsPath`：可选，最大 `255`
- `taskCodeInfo.checkPointFilePath`：可选，最大 `1000`；若传入建议先确认对象存在

### 2) `flux task edit` -> `POST /api/task/edit` -> `TaskEditModel`
`STRICT`（在 create 基础上追加）：
- `taskBaseInfo.taskId`：必填，长度 `1..20`
- `taskCodeInfo.taskId`：必填，须与 `taskBaseInfo.taskId` 一致（后端不会自动同步，缺失会导致代码表更新失效）
- `taskCodeInfo.startScript`：若传入，必须继续保持为 `gm-run` 命令，禁止改成其他启动方式
- **必须提交完整字段**：编辑前先 `flux task info` 获取原数据，合并后再提交（参见上方「`flux task edit` 必须提交完整数据」章节）

`WARN`：
- `taskCodeInfo.isCopyHparams`：可选，建议 `1/2`

### 3) `flux task list` -> `POST /api/task/list` -> `TaskPageQueryModel`
`STRICT`：
- 无必须拦截项（可空请求体，CLI 会补 page）

`WARN`：
- `page`：建议 `>=1`
- `limit`：建议 `1..200`（Agent 侧保护阈值，非后端硬限制）
- `--status`：任务状态码，支持逗号分隔多值。已验证 `0` 为草稿/未启动、`3` 为运行中、`5` 为完成、`6` 为失败或终止；`1/2/4/7` 的展示名称按当前服务端返回解释，不要把 `0` 误报为排队。
- `--project-id`：按项目 ID 精确匹配，长度 `<=20`
- `--tag`：按标签模糊匹配
- `--task-name`：按任务名模糊匹配，长度 `<=100`

### 4) `flux task info` -> `GET /api/task/info/{task_id}`
`STRICT`：
- `task-id`：必填，长度 `1..20`

### 5) `flux task model list` -> `POST /api/task/model/info` -> `TaskModelPagesModel`
`STRICT`：
- `task-id`：必填，长度 `1..20`

`WARN`：
- `page`：建议 `>=1`
- `limit`：建议 `1..200`
- `checkpoint`：可选筛选条件
- 返回项通常包含 `policUrl` 与 `policUrlDown`；若用户目标是“下载模型文件”，使用 `policUrlDown`

### 6) `flux task run` -> `POST /api/task/run` -> `TaskOperation`
`STRICT`：
- 请求体 `task_id`：必填，长度 `1..20`

`WARN`（执行前建议先 `task info` 预检）：
- 任务状态应为草稿态（后端要求 `task_status == "0"`）
- 任务应已绑定可用资源（如 `goodsId/imageId/goodsBackId` 完整）

### 7) `flux task stop` -> `POST /api/task/stop` -> `TaskOperation`
`STRICT`：
- 请求体 `task_id`：必填，长度 `1..20`

`WARN`（执行前建议先 `task info` 预检）：
- 后端不允许停止状态 `0/5/6` 的任务

### 8) `flux task delete` -> `POST /api/task/del` -> `TaskDelModel`
`STRICT`：
- 请求体 `task_id`：必填，长度 `1..20`

`WARN`（执行前建议先 `task info` 预检）：
- 后端仅允许状态集合 `{0,1,2,5,6}` 删除

### 9) `flux task logs` -> `POST /api/task/console/log` -> `ConsoleLogUp`
`STRICT`：
- 请求体 `task_id`：必填，长度 `1..20`

### 10) `flux task params submit` -> `POST /api/task/hp/up` -> `TaskHpModel`
`STRICT`：
- `task_id`：必填，长度 `1..20`

`WARN`：
- `hp_file_name`：建议提供，最大 `1000`
- `hp_file_uri`：建议提供，最大 `1000`
- `hp_save_file_uri`：建议提供，最大 `1000`

### 11) `flux task params update` -> `POST /api/task/hp/edit` -> `EditTaskHpModel`
`STRICT`：
- `task_id`：必填，长度 `1..20`

`WARN`：
- `hp_file_content`：建议必填，最大 `20000`

### 12) `flux task batch stop` -> `POST /api/task/batch/stop` -> `BatchTaskOperation`
`STRICT`：
- `task_ids`：必填，非空数组

`WARN`：
- 每个 `task_id` 建议长度 `1..20`

### 13) `flux task batch delete` -> `POST /api/task/batch/delete` -> `BatchTaskDelete`
`STRICT`：
- `task_ids`：必填，非空数组

`WARN`：
- 每个 `task_id` 建议长度 `1..20`

### 14) `flux task copy` -> `POST /api/task/copy` -> `CopyTaskModel`
`STRICT`：
- 建议请求体包含：`taskId`、`projectId`、`taskName`

`WARN`：
- `taskDescription`：可选，最大 `1000`

### 15) `flux task resource list` -> `GET /api/task/goods/list-by-category`
`STRICT`：
- `goods-back-category`：必填，RL 与 VLA 训练使用 `3`，开发机使用 `4`；CLI 层已做枚举校验，其他值直接返回 exit 2

`WARN`：
- `page >= 1`
- `limit >= 1`

### 16) `flux task image official` -> `GET /api/images/official/list`
`STRICT`：
- 无必须参数

### 17) `flux task image personal` -> `GET /api/images/personal/list`
`STRICT`：
- 无必须参数

`WARN`：
- `version-status` 默认 `1`
- 分页建议：`page >=1`, `limit >=1`

### 18) `flux task image versions` -> `GET /api/task/getImageVersion`
`STRICT`：
- `image-id`：必填
- 返回的 `id` 字段（如 `V000057`）才是 `taskBaseInfo.imageVersion` 的正确填值；`versionCode`（如 `isaac-gym-v17`）是可读标识，**不能**用于 `imageVersion`。

### 19) `flux task storage list` -> `GET /gm/storage/list`（绝对路径模式）
`STRICT`：
- 无必须参数

`WARN`：
- 查询参数使用 `folderPath`（CLI flag: `--folder-path`）

### 20) `flux task data keys` -> `GET /api/task/data/keys/{task_id}`
`STRICT`：
- `task-id`：必填，长度 `1..20`

### 21) `flux task data get` -> `POST /api/task/data/info` -> `GetDataInfoModel`
`STRICT`：
- `task_id`：必填，长度 `1..20`
- `data_key`：必填（先通过 `flux task data keys` 获取可用 key 列表）
- `sampling_mode`：必填，仅允许 `precise`（精细）或 `accelerate`（加速），CLI 层已做枚举校验，其他值直接返回 exit 2
  - 运行中的任务：只能使用 `precise`
  - 已完成/已终止的任务：可选 `precise` 或 `accelerate`

`WARN`：
- `end_time`：可选，格式 `YYYY-MM-DD HH:mm:ss`；不传时后端默认取当前时间
- `max_data_points`：加速模式下建议传入，默认 `10000`，正整数；精细模式下可不传

### 22) `flux task data download` -> `GET /api/task/data/download/{task_id}`
`STRICT`：
- `task-id`：必填，长度 `1..20`

### 23) `flux task hp get` -> `GET /api/task/hp/info/{task_id}`
`STRICT`：
- `task-id`：必填，长度 `1..20`

### 24) `flux task env get` -> `GET /api/task/run/env/{task_id}`
`STRICT`：
- `task-id`：必填，长度 `1..20`

### 25) `flux project list` -> `POST /api/project/list`
`STRICT`：
- 无必须拦截项（可空请求体，CLI 会补 page）

`WARN`：
- `pageNum >= 1`
- `pageSize >= 1`

### 26) `flux project create` -> `POST /api/project/create`
`STRICT`：
- 建议请求体至少包含：`projectName`

### 27) `flux project info` -> `GET /api/project/info/{project_id}`
`STRICT`：
- `project-id`：必填，长度建议 `1..20`

### 28) `flux project edit` -> `POST /api/project/edit` -> `ProjectEditModel`
`STRICT`：
- `projectId`：必填，长度 `1..20`

`WARN`：
- `projectName`：可选，最大 `100`
- `projectDescription`：可选，最大 `1000`

### 29) `flux project delete` -> `POST /api/project/del` -> `ProjectDelModel`
`STRICT`：
- `projectId`：必填，长度 `1..20`

`WARN`：
- 会级联删除项目下所有任务，执行前建议确认；默认需二次确认，可用 `--yes` 跳过。

### 30) `flux task tag update` -> `POST /api/task/updateTag` -> `UpdateTaskTagModel`
`STRICT`：
- `taskId`：必填，长度 `1..20`

`WARN`：
- `taskTag`：数组，可为空（清空标签）

### 31) `flux task tag get` -> `POST /api/task/getTaskTag` -> `TaskIdModel`
`STRICT`：
- `task-id`：必填，长度 `1..20`

### 32) `flux task tag list` -> `POST /api/task/getUserTag`
`STRICT`：
- 无必须参数

`WARN`：
- `limit`：查询参数，默认 `200`

### 33) `flux task note update` -> `POST /api/task/updateTaskNote` -> `UpdateTaskNoteModel`
`STRICT`：
- `taskId`：必填，长度 `1..20`

`WARN`：
- `taskNote`：建议必填（笔记内容，**HTML 格式**），无固定长度限制。前端使用 react-quill 渲染，必须传 HTML 标签（如 `<p>`、`<h3>`、`<ul><li>`、`<strong>`、`<table>` 等）

### 34) `flux task note get` -> `POST /api/task/getTaskNote` -> `TaskIdModel`
`STRICT`：
- `task-id`：必填，长度 `1..20`

## 软限制执行规则（给 Agent）
- 先按 `STRICT` 做预检，不通过则先提示修复示例后再执行。
- `WARN` 只提醒，不阻塞；用户明确要求可带风险继续执行。
- 对 `create/edit` 优先建议 `--file ./payload.json`，避免 shell 转义造成 JSON 结构错误。
- 对 `project create/copy/data get` 同样优先建议 `--file ./payload.json`。
- 对 `run/stop/delete` 优先建议先执行 `flux task info --task-id ...` 做状态预检。
- 默认不自动补全高风险业务字段（如 `goodsId`）；需向用户确认或回读既有任务信息后再填充。

## 批量操作（batch）
- `flux --yes task batch stop --task-ids "t1,t2,t3"`（Agent 必须加 `--yes`）
- `flux --yes task batch delete --task-ids "t1,t2,t3"`（Agent 必须加 `--yes`）

Agent 执行危险操作的推荐流程：
```bash
# 1. dry-run 预览（exit 10 → 通过）
flux --yes task stop --task-id "task_xxx" --dry-run

# 2. 正式执行（exit 0 → 成功）
flux --yes task stop --task-id "task_xxx"
```

所有需要 `--yes` 的命令：
- `flux --yes project delete --project-id "proj_xxx"`
- `flux --yes task stop --task-id "task_xxx"`
- `flux --yes task delete --task-id "task_xxx"`
- `flux --yes task batch stop --task-ids "t1,t2"`
- `flux --yes task batch delete --task-ids "t1,t2"`

## 输出与调试

### 输出格式
- 默认 stdout：JSON；`--human` 人类可读；`--quiet` 仅关键字段（去掉 meta/error 包裹）
- `--debug` 开启调试日志
- `--log-file ./flux.log` 将 stderr JSONL 写入文件
- **Agent 调用时禁止使用 `--human`**：Agent 应始终使用默认 JSON 输出以便解析，`--human` 仅供用户在终端手动执行时使用

### stdout / stderr 分离
- **成功**：结构化 JSON 数据 → **stdout**
- **失败**：结构化 JSON 错误 → **stderr**，stdout 无内容
- Agent 可安全用管道处理 stdout 而不被错误信息干扰

### 语义退出码
Agent 应根据退出码决定下一步操作：

| 退出码 | 含义 | Agent 行为 |
|--------|------|-----------|
| `0` | 成功 | 继续执行 |
| `1` | 一般错误（网络、5xx） | 读 stderr，可重试 |
| `2` | 参数无效 / 非交互拒绝 | 修正参数后重试 |
| `3` | 资源未找到（404） | 跳过或创建 |
| `4` | 权限不足（401/403） | 检查 API Key |
| `5` | 冲突/已存在（409） | 跳过或更新 |
| `10` | dry-run 预览通过 | 去掉 `--dry-run` 正式执行 |

### 错误信息结构
失败时 stderr 输出的 JSON 包含可操作字段：
- `error.code`：机器可读错误类型（如 `INVALID_ARGUMENT`、`NON_INTERACTIVE`、`NETWORK_ERROR`）
- `error.retryable`：`true` 表示可重试（网络/5xx），`false` 表示永久错误（参数错误）
- `error.input`：导致失败的输入值回显，便于 Agent 定位并修正参数
- `error.hint`：恢复建议

### `--dry-run` 预览
- 所有写操作（create/edit/run/stop/delete 等）支持 `--dry-run`
- dry-run 成功时退出码为 **10**（非 0），输出将要发送的 method/endpoint/body/query
- dry-run 也会先校验参数，参数错误仍返回退出码 2
- 推荐 Agent 工作流：先 `--dry-run`（exit 10 → 通过）→ 去掉 `--dry-run` 正式执行（exit 0 → 成功）

## 常见报错快速处理
- **exit 2 + `INVALID_ARGUMENT`**：参数错误，查看 `error.input` 回显的输入值和 `error.message` 修正参数
- **exit 2 + `NON_INTERACTIVE`**：Agent 执行危险操作时忘加 `--yes`，补上即可
- **exit 1 + `NETWORK_ERROR`**（`retryable: true`）：网络问题，可直接重试
- **exit 4**：API Key 无效或权限不足，需 `flux auth login --api-key ...` 重新配置
- **exit 10**：`--dry-run` 预览通过，去掉 `--dry-run` 正式执行
- base_url 为空：先 `flux config set base_url "..."` 或设置 `FLUX_BASE_URL`
- api key 为空：先 `flux auth login --api-key ...` 或设置 `FLUX_API_KEY`
- 不确定参数：先跑 `flux <command> --help`

## task edit 关键注意事项

> **严重警告：后端 edit 接口会用提交的数据整体覆盖记录，未传的字段会被置为 null。**

**Agent 执行 `flux task edit` 前必须遵守以下规则：**
1. **先执行 `flux task info`** 获取任务完整数据，作为编辑的基准。
2. 编辑 JSON 的 `taskBaseInfo` 中**必须包含以下字段**（即使不修改也要从 info 中原样回传）：
   - `taskId`、`projectId`、`taskType`、`trainType`、`taskName`
   - `taskStatus`（关键！缺失会导致页面不可见）
   - `userId`（关键！缺失会导致任务变为"无主"，且后续无法编辑/删除）
   - `goodsId`、`gpuNum`、`imageId`、`imageVersion`、`personalDataPath`、`source`
3. 编辑 JSON 的 `taskCodeInfo` 中**必须包含以下字段**：
   - `taskId`、`userId`、`codeType`、`codeUrl`、`mainCodeUri`、`mainCodeType`
   - `startScript`、`isOpen`、`runParams`
4. 仅修改需要变更的字段值，其余字段从 `task info` 返回中原样保留。
5. 若 edit 返回 500 错误，**禁止盲目重试**，应先分析原因。

## VLA 命令（Vision-Language-Action 训练）

> **VLA 是独立于 RL（`flux task`）的训练链路**，命令在 `flux vla` 下，后端走 `/api/vla/*`。

### 命令总览

```
flux vla task    create | edit | list | info | delete | start | stop | models | logs | data(keys|get)
flux vla project create | edit | list | info | delete
flux vla dataset    list | info     # 只读，创建任务时取 datasetId
flux vla base-model list | info     # 只读，创建任务时取 baseModelId
flux vla image      list | info     # 只读，创建任务时取 imageId（--scope official|all）
```

### Task 常用操作

- 列表：`flux vla task list --page 1 --limit 50`
  - 按项目：`flux vla task list --project-id "VPRO_xxx"`
  - 按名称（模糊）：`flux vla task list --task-name "pi05"`
- 详情：`flux vla task info --task-id "VTASK_xxx"`
- 启动：`flux vla task start --task-id "VTASK_xxx"`（推荐先 `--dry-run`）
- 停止：`flux --yes vla task stop --task-id "VTASK_xxx"`（Agent 必须加 `--yes`）
- 删除：`flux --yes vla task delete --task-id "VTASK_xxx"`（Agent 必须加 `--yes`，软删）
- Checkpoint 列表：`flux vla task models --task-id "VTASK_xxx" --page 1 --limit 20`
  - 返回行含 `policUrlDown`（7 天签名下载地址），下载 `.pt` 模型用此链接 + `curl`。
- 日志：`flux vla task logs --task-id "VTASK_xxx"`
  - 追踪：`... --follow --interval 2s --timeout 1m`
  - 纯净日志流：`... --raw --no-request-log`
- 训练曲线：
  - 指标 keys：`flux vla task data keys --task-id "VTASK_xxx"`
  - 曲线数据：`flux vla task data get --task-id "VTASK_xxx" --data-key "loss" [--start-time "2026-06-29T00:00:00" --end-time "2026-06-29T12:00:00"]`

### VLA 模型文件下载（pt）

适用场景：
- 用户要下载某个 VLA 任务的 checkpoint 对应模型文件

当前方式：
- 用 `flux vla task models --task-id "VTASK_xxx" --page 1 --limit 20` 列 checkpoint（对应 `POST /api/vla/task/{task_id}/models`）
- 取目标 checkpoint 行的 `policUrlDown`（7 天签名下载地址），再用 `curl` 下载，默认保存到当前项目根路径下
- 示例：`curl -L -o model_3000.pt "<policUrlDown>"`
- 单个 checkpoint 可在结果中按 `checkpoint` 字段筛选目标行，再取其 `policUrlDown`

### 资源查询（创建任务前的下拉数据）

- 数据集：`flux vla dataset list` / `flux vla dataset info --dataset-id "DS_xxx"`
- 底模：`flux vla base-model list` / `flux vla base-model info --base-model-id "BM_xxx"`
  - 行内含 `modelFamily` / `supportedFinetune` / `exposedParams`，据此选 `baseModelId` 并确定可用 `finetuneMode`。
- 镜像：`flux vla image list`（默认仅官方）/ `flux vla image list --scope all`（官方+个人）/ `flux vla image info --image-id "VIMG_xxx"`
- 算力：flux-cli `1.1.0` 已验证 VLA 与 RL 共用类目 `3`，使用 `flux task resource list --goods-back-category 3`，取 `goodsId`（填 `taskBaseInfo.goodsId`）、`goodsBackId`（填 `taskBaseInfo.goodsBackId`，**不可混用**）与 `goodsBackSku.gpuNum`（填 `taskBaseInfo.gpuNum`）。

### Project 常用操作

- 列表：`flux vla project list --page 1 --limit 50 [--project-name "pi05"]`
- 创建：`flux vla project create --data '{"projectName":"my-vla-project"}'`
- 详情：`flux vla project info --project-id "VPRO_xxx"`（返回含 `taskCount`）
- 编辑：`flux vla project edit --data '{"projectId":"VPRO_xxx","projectName":"新名称"}'`（PUT）
- 删除：`flux --yes vla project delete --project-id "VPRO_xxx"`

### 最小可运行 JSON 模板（VLA 训练任务）

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

建议创建并运行：
- `flux vla task create --file ./vla-create.json`（成功后立即删除该临时 JSON）
- 从返回取 `taskId` → `flux vla task start --task-id "VTASK_xxx"`
- `flux vla task logs --task-id "VTASK_xxx" --follow`

### VLA Task 软限制（执行前预检）

字段命名用后端 alias（小驼峰）。`STRICT`=强烈建议拦截，`WARN`=仅提示。

**`flux vla task create` → `POST /vla/task/create` → `VlaTaskCreateModel`**
- `STRICT`：`taskBaseInfo`（object）必填；`taskBaseInfo.projectId` 必填，长度 `1..20`
- `WARN`（可跑通训练所需的业务必填）：`taskName`（≤200）、`goodsId`、`goodsBackId`、`gpuNum`、`imageId`、`modelFamily`（`pi05`/`gr00t`/`openvla`）、`finetuneMode`（`full`/`lora`）、`baseModelId`、`datasetIds`（数组）
- `WARN`（可选）：`taskDesc`、`goodsName`、`goodsPrice`、`hashrateResourceId`、`paramOverrides`（object；key 必须在底模 `exposedParams[finetuneMode]` 白名单内，否则后端 `validate_cfg_options` 拒绝）、`startScript`（**通常不传**；底模配了 `base_config_*` 时后端忽略并自动拼 torchrun）

**`flux vla task edit` → `PUT /vla/task/config` → `VlaTaskConfigEditRequest`**
- `STRICT`：`taskId` 必填，长度 `1..20`
- **部分更新**：`taskBaseInfo` 只传要改的字段即可（后端 `exclude_unset`）。

**`flux vla task list` → `POST /vla/task/list` → `VlaTaskPageQueryModel`**
- `WARN`：`page>=1`、`limit 1..200`；`--project-id`（精确）、`--task-name`（模糊）

**`flux vla task info` → `GET /vla/task/{id}`** ｜ `STRICT`：`task-id` 必填 `1..20`
**`flux vla task delete` → `DELETE /vla/task/{id}`** ｜ `STRICT`：`task-id` 必填；危险操作，Agent 必须 `--yes`
**`flux vla task start` → `POST /vla/task/start`** ｜ `STRICT`：`taskId` 必填 `1..20`
**`flux vla task stop` → `POST /vla/task/stop`** ｜ `STRICT`：`taskId` 必填；危险操作，Agent 必须 `--yes`
**`flux vla task models` → `POST /vla/task/{id}/models`** ｜ `STRICT`：`task-id` 必填；返回行含 `policUrlDown`
**`flux vla task logs` → `POST /vla/task/console/log`** ｜ `STRICT`：`taskId` 必填 `1..20`
**`flux vla task data keys` → `GET /vla/task/data/keys/{id}`** ｜ `STRICT`：`task-id` 必填 `1..20`
**`flux vla task data get` → `POST /vla/task/data/info` → `VlaChartDataQuery`**
- `STRICT`：`taskId` 必填、`dataKey` 必填（先用 `data keys` 获取可用 key）
- `WARN`：`startTime` / `endTime` 可选（ISO8601）

**Project**：`create`（`STRICT` `projectName` 必填，≤200）｜`edit`（`PUT`，`STRICT` `projectId` 必填 `1..20`）｜`delete`（`DELETE /vla/project/{id}`，`STRICT` `project-id` 必填，Agent 必须 `--yes`）｜`info`（`GET /vla/project/{id}`）｜`list`（`projectName` 模糊 + 分页）

### Agent 创建 VLA 任务的推荐流程

1. 选项目：`flux vla project list`（或新建 `flux vla project create`）→ 得 `projectId`
2. 选底模：`flux vla base-model list` → 得 `baseModelId`，并据 `modelFamily` / `supportedFinetune` 确定 `modelFamily` 与 `finetuneMode`
3. **展示训练参数并引导用户确认**（底模选定后必须执行）：
   - 从 `exposedParams[finetuneMode]` 提取当前微调模式的参数列表
   - 以表格形式展示给用户：参数说明（`label`）、默认值（`default`）、范围（`min`/`max`，无则显示"—"）
   - 询问用户是否修改，若是则收集修改值写入 `paramOverrides`；若否则不传 `paramOverrides`（后端使用默认值）
   - `paramOverrides` 的 key 必须在 `exposedParams[finetuneMode]` 白名单内，否则后端拒绝

   展示示例（以 pi05 / lora 为例）：
   ```
   底模训练参数（lora 模式，可修改）：
   | 参数           | 说明               | 默认值  | 范围     |
   |----------------|--------------------|---------|----------|
   | per_device_batch_size | 每卡 Batch Size | 4  | 1~16    |
   | runner.max_steps      | 训练 Steps      | 100 | ≥1      |
   | runner.save_iter_interval | Checkpoint 保存间隔 | 500 | 1~100000 |
   | runner.max_keep_ckpts | Checkpoint 保留数 | 10 | 1~50    |
   | runner.learning_rate  | Learning Rate   | 0.0001 | —      |
   | model.lora_rank       | LoRA Rank       | 16  | 4~128   |
   是否修改以上参数？（直接回车跳过使用默认值）
   ```

4. 选数据集：`flux vla dataset list` → 得 `datasetIds`
5. 选镜像：`flux vla image list [--scope all]` → 得 `imageId`
6. 选算力：`flux task resource list --goods-back-category 3` → 得 `goodsId` + `goodsBackId` + `goodsBackSku.gpuNum`
7. 写 `vla-create.json`（**不含 `startScript`**）→ `flux vla task create --file ./vla-create.json --dry-run`（exit 10 通过）→ 去掉 `--dry-run` 正式执行 → **删除临时 JSON**
8. 取 `taskId` → 按需 `flux vla task start --task-id ...`（用户明确要求才启动，避免误触发计费）
