# Flux 训练监控、收尾与实验记录

## 目录

1. 状态与指标
2. 周期监控
3. ETA 计算
4. 完成后的产物
5. 实验记录

## 状态与指标

先用 `flux task info --task-id <task>` 获取必要字段，不输出完整 `taskCodeInfo`。已验证的关键状态：

- `0`：草稿/未启动，必须执行 `task run`；
- `3`：运行中；
- `5`：完成；
- `6`：失败或终止。

play 任务即使产物成功也可能是 `6`，因此终态必须结合日志和 `model list`。

训练指标来源按优先级使用：

1. `flux task data keys` 获取平台实际指标名；
2. `flux task data get --sampling-mode precise` 查询运行中曲线；
3. `flux task logs --raw --no-request-log` 获取最新迭代、速度和 ETA；
4. `flux task model list` 获取 checkpoint 与回放产物。

报告至少包含：

- 当前状态；
- 当前迭代/总迭代；
- 平均奖励；
- 平均 episode 长度；
- 估算存活时长；
- 训练速度；
- 完成比例；
- 预计剩余时间；
- 最新 checkpoint。

## 周期监控

用户指定每 15 分钟检查时：

1. 保持同一任务 ID，不创建、停止或编辑任务；
2. 每次读取最新状态和指标；
3. 状态和指标无变化时简短报告，不重复长日志；
4. 任务进入终态后停止周期查询，转入产物下载与记录；
5. 任何签名 URL、token、完整 `startScript` 都先脱敏。

运行中任务的图表查询使用 `precise`；只有完成或终止后才可使用 `accelerate`。

## ETA 计算

优先采用训练日志提供的时间统计。没有现成 ETA 时：

```text
平均每迭代秒数 = 已运行秒数 / 已完成迭代数
剩余秒数 = (总迭代数 - 当前迭代数) × 平均每迭代秒数
```

使用最近一段窗口估算速度，避免启动编译时间扭曲全程平均值。说明 ETA 是估算值。

存活时长按环境定义换算：

```text
存活秒数 = mean_episode_length_steps × control_dt
```

先从配置确认 `control_dt`；F1/X1 常用 100 Hz 时每步约 `0.01 s`，不要对其他任务硬编码。

## 完成后的产物

训练任务完成后：

1. 从 `data.rows` 选择最终 checkpoint，使用 `policUrlDown`；
2. 回放任务读取 `play_output.mp4` 的 `videoUrlDown`；
3. 读取 `model_isaac_csv.pt` 的 `policUrlDown`；
4. 下载到用户指定实验目录；
5. 解包 CSV 包并校验；
6. 删除临时包和中间 checkpoint；
7. 只保留用户要求的最终文件。

F1/X1 默认交付集合：

```text
model_<final>.pt
play_output.mp4
isaac_diag.csv
```

下载 URL 是临时凭据，只存入变量或一次性助手。验证下载文件大小、可读性和名称后再报告成功。

## 实验记录

本地实验记录由 `czy/skills/lab-notebook/SKILL.md` 管理。需要更新 `czy/exp1/实验记录/exp1.md` 时，完整读取并遵循该技能，不在本文件复制笔记结构。

记录至少包括：

- 训练与回放任务 ID；
- 代码分支或提交；
- 镜像和算力；
- 迭代数、运行时长、最终奖励和 episode 长度；
- 最终 checkpoint；
- 本地视频与 CSV 路径；
- 成功、失败或部分成功的客观结论。

远端 `task note` 使用 HTML 片段；本地 Markdown 实验记录按 lab-notebook 规范更新。失败实验也保留记录，不删除历史。
