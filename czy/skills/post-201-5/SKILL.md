---
name: "post-201.5"
description: "通过 SSH 把整个项目传输到远程服务器 10.12.201.5 的 ~/czy/exp1/exp_<时间戳>/ 下，并在远程激活 conda 环境、安装依赖、启动/恢复训练。当用户提到部署到服务器、发送项目到 10.12.201.5、上传代码到远程、ssh 传输、rsync/scp 项目、远程训练、在服务器上跑训练、post_122 时使用。"
---

# post-122：项目 SSH 传输 + 远程训练

## 适用范围

把本地项目 `agibot_x1_train-runner` 通过 SSH 发送到远程服务器，并在远程启动训练：

- 传输：本地 → `robot@10.12.201.5:~/czy/exp1/exp_<时间戳>/`（每次传输生成新时间戳目录）
- 远程训练：`conda activate F1` → `pip install -e .` → `python humanoid/scripts/train.py ...`

> 本文件自包含 Agent 执行所需的全部固定流程、命令与约束（基于首次端到端实测）。

## 目标参数（固定）

| 项 | 值 |
| --- | --- |
| 远程主机 | `10.12.201.5` |
| 登录用户 | `robot` |
| 登录认证 | 已配 SSH 密钥免密，见本机 `~/.ssh`；如需密码登录请手动输入，不在此记录 |
| SSH 端口 | `22` |
| 远程目标目录 | `~/czy/exp1/exp_<YYYYMMDD_HHMMSS>/`（**动态创建**，每次传输生成新时间戳目录）|
| 本地源目录 | 项目根 `agibot_x1_train-runner` |
| 远程 conda 安装路径 | `/home/robot/Anaconda`（**实测确认**，非 miniconda3/anaconda3）|
| conda 初始化脚本 | `/home/robot/Anaconda/etc/profile.d/conda.sh` |
| conda 环境 | `F1`（Python 3.8.20）|
| 训练日志文件 | `~/czy/exp1/exp_<时间戳>/agibot_x1_train-runner/train_test_20_video.log` |
| 训练命令 | `python humanoid/scripts/train.py --task=x1_dh_stand --run_name=test_20_video --resume --headless --load_run 2026-01-14_09-58-10test_20_video --checkpoint 6000` |

> **时间戳格式**：`exp_20260605_143025` 表示 2026年6月5日 14:30:25 创建的实验目录。

## 实测经验要点（首次执行已验证）

这些是首次端到端跑通时踩过并解决的点，后续执行直接套用：

1. **SSH 必须加 `-o BatchMode=yes`**：强制走密钥、禁交互，避免命令卡在密码提示。首次可加 `-o StrictHostKeyChecking=no` 跳过指纹确认。
2. **conda 在非交互 SSH 下未初始化**：交互登录显示 `(base)` 不代表非交互可用 `conda`。所有远程命令必须先 `source /home/robot/Anaconda/etc/profile.d/conda.sh` 再 `conda activate F1`。
3. **checkpoint 实际路径含 `exported_data/` 层**：
   - 物理路径：`logs/x1_dh_stand/exported_data/2026-01-14_09-58-10test_20_video/model_6000.pt`
   - 训练 `log_root` 默认 = `logs/<experiment_name>/exported_data`，`get_load_path` 拼 `log_root/<load_run>/model_<ckpt>.pt`，**正好对上**，`--resume` 能找到。
   - ⚠️ 验证 checkpoint 时要查含 `exported_data/` 的完整路径，否则误报 `CKPT_MISSING`。
4. **本地无 rsync/sshpass**（Windows 自带仅 ssh/scp）：用 scp 全量传输；已配密钥，scp 可非交互全自动。
5. **nohup 启动训练会触发本地 SSH 命令超时**：因为前台 SSH 等会话结束，但 `&` 后台进程已脱离会话正常运行。超时是预期现象，用进程检查 + 日志确认实际状态即可，**不要因超时重复启动**（会起多个训练抢 GPU）。
6. **scp 用绝对远程路径**：`robot@10.12.201.5:/home/robot/czy/exp1/`，比 `~` 更稳。

## 安全与约束

- 🔑 **认证方式**：统一使用 SSH 密钥免密（见本机 `~/.ssh`）。**本文件不保存任何明文密码**；如确需密码登录，由操作者在终端手动输入，切勿写入本文件或任何项目文件。
- 🔒 **凭据存放原则**：任何密码/Token 不放入项目或 skill 文件，应使用系统 keychain 或专用密钥管理器；若密钥失效，优先重新分发密钥而非改用明文密码。
- **保留 `logs/` 与 `*.pt`**：训练用 `--resume --checkpoint 6000`，必须保留 `logs/x1_dh_stand/2026-01-14_09-58-10test_20_video/model_6000.pt`，否则恢复训练失败。
- **传输排除**：`skills/`（含凭据/文档，远程不需要）、`czy/data/`（诊断 CSV/图）、`*.mp4`、`.git/`、`__pycache__/`、`*.pyc`、`*.log`。优先用 rsync `--exclude`；用 scp 全量传输时必须在远程清理 `skills/` 与 `czy/data/`（见第 3 步）。
- **传输属高影响操作**：会向远程主机写入大量文件并占用 GPU 训练。Agent 执行真实传输/训练命令前，应向用户确认，不要擅自发起。
- **Windows 路径**：cmd 用 `e:\...`，WSL 用 `/mnt/e/...`，Git-Bash 用 `/e/...`。
- **长训练防断连**：用 `nohup` 或 `tmux`，避免 SSH 断开终止训练。

## 标准执行流程

> 所有 SSH/scp 命令统一加 `-o BatchMode=yes` 走密钥免密。

### 第 1 步：连通性预检 + conda/F1 验证

```bash
# 网络与登录（PowerShell 可先 Test-NetConnection 10.12.201.5 -Port 22）
ssh -p 22 -o BatchMode=yes robot@10.12.201.5 "echo connected"

# 验证 conda 初始化脚本可用 + F1 环境
ssh -p 22 -o BatchMode=yes robot@10.12.201.5 "source /home/robot/Anaconda/etc/profile.d/conda.sh && conda activate F1 && python --version && echo F1_OK"
```
预期：`connected` + `Python 3.8.20` + `F1_OK`。若 conda 路径变化，用 `ssh ... \"bash -lic 'which conda'\"` 重新定位。

### 第 2 步：远程创建时间戳目录

**在执行前生成时间戳**：
```powershell
# PowerShell 获取时间戳（格式：exp_YYYYMMDD_HHMMSS）
$timestamp = "exp_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
echo $timestamp  # 如 exp_20260605_143025
```

```bash
# 在远程创建带时间戳的实验目录
ssh -p 22 -o BatchMode=yes robot@10.12.201.5 "mkdir -p ~/czy/exp1/$timestamp && echo MKDIR_OK"
```

> 后续所有命令中的 `$timestamp` 需替换为实际生成的时间戳值（如 `exp_20260605_143025`）。

### 第 3 步：传输项目（优先 rsync 增量 + 排除非训练文件）

**传输范围原则**：只传远程训练真正需要的内容（代码 + `logs/` + `*.pt` + `resources/`）。
**排除**：`skills/`（含凭据/文档，远程训练不需要）、`czy/data/`（诊断 CSV/图，体积大且与训练无关）、`*.mp4`、`.git/`、`__pycache__/`、`*.pyc`、`*.log`。

**首选 · rsync（支持 `--exclude`，增量同步）**——本地有 WSL/Git-Bash/Linux 时使用：
```bash
rsync -avz -e "ssh -p 22 -o BatchMode=yes -o StrictHostKeyChecking=no" \
  --exclude='skills/' \
  --exclude='czy/data/' \
  --exclude='*.mp4' --exclude='.git/' \
  --exclude='__pycache__/' --exclude='*.pyc' --exclude='*.log' \
  /mnt/e/X1/real_test/exp1/agibot_x1_train-runner \
  robot@10.12.201.5:/home/robot/czy/exp1/$timestamp/
```
> WSL 路径用 `/mnt/e/...`，Git-Bash 用 `/e/...`。rsync 增量同步，重复传输只发送变化文件。

**回退 · scp（Windows 自带，但 scp 不支持 `--exclude`）**——无 rsync 时：
scp 无法在传输时排除子目录，需先在本地准备一个不含排除项的临时副本再传，或接受全量传输后**在远程删除**不需要的目录：
```powershell
# 全量传输（含 skills/、czy/data/，会多传无关文件）
scp -r -P 22 -o BatchMode=yes -o StrictHostKeyChecking=no "e:\X1\real_test\exp1\agibot_x1_train-runner" robot@10.12.201.5:/home/robot/czy/exp1/$timestamp/
```
```bash
# 传完后清理远程的非训练/含凭据目录（重要：含 skills 凭据文档）
ssh -p 22 -o BatchMode=yes robot@10.12.201.5 "rm -rf ~/czy/exp1/$timestamp/agibot_x1_train-runner/skills ~/czy/exp1/$timestamp/agibot_x1_train-runner/czy/data && echo CLEANED"
```
> ⚠️ scp 回退方案必须执行远程清理，否则 `skills/`（含凭据/文档）会残留在服务器上。
> 项目核心约 75MB，排除 `czy/data/` 与 `skills/` 后更小。

### 第 4 步：传输后验证（注意 checkpoint 含 exported_data 层）

```bash
ssh -p 22 -o BatchMode=yes robot@10.12.201.5 "test -f ~/czy/exp1/$timestamp/agibot_x1_train-runner/humanoid/scripts/train.py && echo OK || echo MISSING; test -f ~/czy/exp1/$timestamp/agibot_x1_train-runner/logs/x1_dh_stand/exported_data/2026-01-14_09-58-10test_20_video/model_6000.pt && echo CKPT_OK || echo CKPT_MISSING"
```
必须同时 `OK` + `CKPT_OK` 才进入下一步。

### 第 5 步：安装依赖

```bash
ssh -p 22 -o BatchMode=yes robot@10.12.201.5 "source /home/robot/Anaconda/etc/profile.d/conda.sh && conda activate F1 && cd ~/czy/exp1/$timestamp/agibot_x1_train-runner && pip install -e . 2>&1 | tail -n 5"
```
预期末尾 `Successfully installed humanoid`。

### 第 6 步：后台启动训练（nohup，会本地超时属正常）

```bash
ssh -p 22 -o BatchMode=yes robot@10.12.201.5 "source /home/robot/Anaconda/etc/profile.d/conda.sh && conda activate F1 && cd ~/czy/exp1/$timestamp/agibot_x1_train-runner && nohup python humanoid/scripts/train.py --task=x1_dh_stand --run_name=test_20_video --resume --headless --load_run 2026-01-14_09-58-10test_20_video --checkpoint 6000 > train_test_20_video.log 2>&1 & echo STARTED_PID=\$!"
```
> 本地 SSH 命令会超时（前台等会话结束），但 `&` 后台进程已正常运行。**记下 PID，不要因超时重复启动**。

### 第 7 步：确认训练已启动（启动后等 ~45s 再查）

见下方「查看训练进度」。

## 查看训练进度

随时调用以下命令查看远程训练状态，**不会**影响正在运行的训练。

> **注意**：以下命令中的 `$timestamp` 需替换为实际的实验目录时间戳（如 `exp_20260605_143025`）。

### 7.1 进程是否存活 + 日志末尾

```bash
ssh -p 22 -o BatchMode=yes robot@10.12.201.5 "ps aux | grep train.py | grep -v grep | grep -v 'bash -c' | head -1; echo '===== LOG ====='; tail -n 45 ~/czy/exp1/$timestamp/agibot_x1_train-runner/train_test_20_video.log"
```
- 进程行存在 = 训练在跑；为空 = 已结束或崩溃（查日志末尾原因）。
- 日志关注：`Learning iteration N/总数`、`Mean reward`、`Mean episode length`。

### 7.2 实时跟踪日志（手动终端用，Agent 勿用，会一直阻塞）

```bash
ssh -p 22 robot@10.12.201.5 "tail -f ~/czy/exp1/$timestamp/agibot_x1_train-runner/train_test_20_video.log"
```

### 7.3 GPU 占用确认

```bash
ssh -p 22 -o BatchMode=yes robot@10.12.201.5 "nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv"
```

### 7.4 只看当前迭代号与关键奖励（快速概览）

```bash
ssh -p 22 -o BatchMode=yes robot@10.12.201.5 "grep -E 'Learning iteration|Mean reward|Mean episode length|tracking_lin_vel|feet_contact_forces' ~/czy/exp1/$timestamp/agibot_x1_train-runner/train_test_20_video.log | tail -n 12"
```

### 进度判读要点

| 信号 | 健康 | 异常 |
| --- | --- | --- |
| 进程存活 | `ps` 有 train.py 行 | 无 → 崩溃/结束，查日志尾部 traceback |
| Mean reward | 持续上升或高位稳定 | 长期低位/为 0 → 策略退化 |
| Mean episode length | 接近 episode 上限（如 ~1288） | 持续很小（如 <300）→ 频繁摔倒 |
| Learning iteration | 单调增长 | 长时间不动 → 卡死 |
| GPU 显存 | 被占用 | 0 → 训练未真正用 GPU |

### 停止训练（按需，高影响，需确认）

```bash
# 先看 PID
ssh -p 22 -o BatchMode=yes robot@10.12.201.5 "ps aux | grep train.py | grep -v grep | grep -v 'bash -c'"
# 停止（替换 <PID>）
ssh -p 22 -o BatchMode=yes robot@10.12.201.5 "kill <PID>"
```

## 第 8 步：训练结果验证（训练结束后执行）

训练完成后，运行 `play.py` 验证训练效果，结果会保存在 `/personal/train-more` 目录下。

### 8.1 启动验证脚本

```bash
ssh -p 22 -o BatchMode=yes robot@10.12.201.5 "source /home/robot/Anaconda/etc/profile.d/conda.sh && conda activate F1 && cd ~/czy/exp1/$timestamp/agibot_x1_train-runner && nohup python humanoid/scripts/play.py --task=x1_dh_stand --run_name=test_20_video > play_test_20_video.log 2>&1 & echo PLAY_PID=\$!"
```

### 8.2 等待约 60 秒后终止进程

```bash
# 等待 60 秒（本地 PowerShell）
Start-Sleep -Seconds 60

# 查找并终止 play.py 进程
ssh -p 22 -o BatchMode=yes robot@10.12.201.5 "pkill -f 'play.py' && echo PLAY_STOPPED || echo NO_PLAY_PROCESS"
```

### 8.3 检查验证结果

```bash
# 查看结果目录内容
ssh -p 22 -o BatchMode=yes robot@10.12.201.5 "ls -la ~/czy/exp1/$timestamp/agibot_x1_train-runner/personal/train-more/ 2>/dev/null || echo RESULT_DIR_MISSING"

# 查看验证日志末尾
ssh -p 22 -o BatchMode=yes robot@10.12.201.5 "tail -n 30 ~/czy/exp1/$timestamp/agibot_x1_train-runner/play_test_20_video.log"
```

> **预期结果**：`/personal/train-more/` 目录下会生成训练验证相关的输出文件（如视频、日志等）。

## 执行决策规则（给 Agent）

1. **真实执行前必须向用户确认**：传输和训练都是高影响操作，确认后再发起。
2. **按工具可用性选方案**：本地 Windows 自带仅 ssh/scp，默认用 scp（已配密钥可全自动）；有 rsync 环境时优先 rsync 增量同步。
3. **传输完成必须验证 checkpoint**（第 4 步），`CKPT_OK` 后才启动训练。
4. **训练默认后台运行**（nohup/tmux），不要前台阻塞 SSH 会话；nohup 启动触发的本地超时属正常，勿重复启动。
5. **遇错查下方「常见问题」表**，按表处置；checkpoint 缺失、conda 未初始化、F1 不存在为高频问题。
6. **不回显/不记录密码到日志输出**。

## 常见问题

| 问题 | 原因 | 处理 |
| --- | --- | --- |
| `conda: command not found` | 非交互 SSH 未加载 `~/.bashrc` | 命令前加 `source /home/robot/Anaconda/etc/profile.d/conda.sh`，或用 `conda run -n F1` |
| `Permission denied` | 密钥未生效/用户错 | 确认免密已配；命令加 `-o BatchMode=yes` |
| `Host key verification failed` | 首次连接指纹未确认 | 加 `-o StrictHostKeyChecking=no` |
| 校验 `CKPT_MISSING` | 漏了 `exported_data/` 层 | 查完整路径 `logs/x1_dh_stand/exported_data/<load_run>/model_6000.pt` |
| `--resume` 找不到 run | logs 未传全 | 确认 scp 已含 logs 目录，重新校验 |
| nohup 启动后本地超时 | 前台 SSH 等会话结束 | 正常现象，进程已后台运行；用第 7 步查进程，勿重启 |
| 训练进程不存在 | 崩溃/已结束 | `tail -n 50` 看日志尾部 traceback |
| `CUDA out of memory` | 显存不足 | 减小 `num_envs` 或确认无其他进程占 GPU |
| 多个 train.py 进程 | 重复启动 | `kill` 多余 PID，只保留一个 |

## 回放（play_adaptive.py）经验坑（2026-08-27 汇总）

| # | 坑 | 症状 | 处理 |
| --- | --- | --- | --- |
| 1 | **模型必须放 `logs/x1_dh_stand/exported_data/gm_play/`** | `get_load_path` 报 `No runs in this directory`（模型传到了项目根或 `exported_data/` 直下都不行） | 上传后 `mkdir -p .../exported_data/gm_play && mv model_*.pt .../exported_data/gm_play/`；启动参数 `--load_run gm_play --checkpoint <N>` |
| 2 | **回放必须无推力（验收基线）** | 推力窗 catch-steps 污染碎步统计（exp6.2 实测 64% vs 无扰动 40%）、掩盖偏航漂移（+15° vs 真实 +27.6°） | play_adaptive.py 已内置 `push_robots = False`（exp6.3 起入库）；**勿手动改回 True**，除非刻意测抗推 |
| 3 | **armature 固定校准中心值** | 回放关闭随机化后 dof armature 回退 URDF 基线（无 armature 属性 = 0），"轻腿"回放失真（exp5 教训） | play_adaptive.py 已内置（armature fixed to calibration centers 日志行）。**URDF 确认用 `X1_12DOF_physically_mirrored.urdf`（exp7 起）**——右踝 Pitch axis 已翻转 (0,0,-1)，dof10 符号约定反转；此 URDF 无 armature 属性，回放校准中心值 = config `domain_rand.joint_*_armature_range` 中值（exp7 已按 J辨识−M_ii_new 重算）：L/R 髋Pitch [0.10,0.19]/[0.05,0.14]、髋Yaw [0.005,0.015]、膝 [0.20,0.30] |
| 4 | **`__pycache__` 残留旧代码** | 改了 env/config 但行为不变（Python 缓存字节码） | 部署后 `find <dir>/humanoid -name __pycache__ -type d -exec rm -rf {} +` |
| 5 | **新目录部署要带全三件套** | 缺 URDF/资源导致 `[carb.gym.plugin] Failed to resolve visual mesh` 级联失败 | 复制上个实验目录的 `humanoid/ resources/ setup.py` 再覆盖新改文件，模型放坑 1 位置 |
| 6 | **scp 传服务器 wget 失败** | 服务器直连 OSS 被拒（签名/网络），本地 Invoke-WebRequest 报吊销错误 | 本地 `curl.exe -L --ssl-no-revoke` 下载（Windows schannel 吊销检查误报），再 scp 上去 |
| 7 | **回放产物路径** | 找不到 CSV/视频 | 固定在 `<项目根>/logs/x1_dh_stand/play_output/`：`isaac_diag.csv` + `play_adaptive.mp4`；分析后归档 `czy/data/<exp>/` |
| 8 | **零动作开环开关** | 想验证参考+PD 开环稳定性时误用策略 | `USE_POLICY = False`（顶部常量）= 零动作回放；验收必须 True（服务器上确认后再启动） |
| 9 | **回放时长/日志** | 八段 4000 步约 4 分钟；每 500 步打一行进度 | `[yaw]` 行每 0.5s 打印偏航（exp6.2 起）；Summary 有逐段 yaw 漂移 + 全程总览 |