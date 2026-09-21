# F1/X1 Isaac Gym 回放与产物下载

## 目录

1. 适用条件
2. checkpoint 传递
3. 回放任务
4. SDK 上传目录
5. 下载与解包
6. 成功判定

## 适用条件

仅在用户要求回放训练策略、生成 `play_output.mp4`、导出 `isaac_diag.csv` 或下载完整回放产物时使用。回放不训练策略，只加载已有 checkpoint。

仓库应提供 `humanoid/scripts/play_gm.py` 或等价脚本，并具备：

- `--headless --num_envs=1` 回放；
- `--checkpoint_url_b64` 运行时下载；
- GPU camera 的 headless 渲染；
- MP4、诊断 PT 与 CSV 导出；
- CSV 打包为 `model_isaac_csv.pt`。

`base_task.py` 在启用 headless camera 时必须保留渲染设备，不能无条件把 `graphics_device_id` 设为 `-1`。

## checkpoint 传递

1. 用 `flux task model list --task-id <source> --checkpoint <final> --limit 1` 查询源任务。
2. 从 `data.rows` 选中目标 checkpoint，并在内存中读取 `policUrlDown`。
3. 将 URL 编码成 URL-safe Base64，作为 `--checkpoint_url_b64=<value>` 传给回放脚本。
4. 不要硬编码、提交或回显原始签名 URL；任务 payload 成功提交后立即删除。

不要把带 `&` 的原始 URL 直接拼入 `startScript`。GM 工作流可能错误拆分它，最终执行空脚本或默认示例。

Isaac Gym 镜像中 `/personal` checkpoint 挂载可能不生效。回放任务使用 `trainType=1`，脚本运行时下载 checkpoint，不依赖 `checkPointFilePath` 或 `checkPointMountPath`。

## 回放任务

`startScript` 保持以下形式；官方 CLI 虽改名为 `flux`，运行包装器仍是 `gm-run`：

```text
gm-run <repo>/humanoid/scripts/play_gm.py --task=x1_trajectory --headless --num_envs=1 --checkpoint_url_b64=<URL_SAFE_BASE64>
```

执行顺序：

1. `flux --yes task create --file ./create-replay.json`。
2. 删除临时 payload。
3. 检查新任务状态。`0` 是草稿/未启动，不是排队。
4. `flux --yes task run --task-id <task>`。
5. 等待状态进入 `3`，再监控日志和产物。

不要因 play 任务终态为 `6` 就直接判定失败。play 脚本退出后平台可能显示终止/失败，最终以日志与产物为准。

## SDK 上传目录

MP4 写入 `logs/<replay-exp>/play_output.mp4`，SDK 会按视频类型上传。

CSV 原文件可写入回放输出目录，但上传包 `model_isaac_csv.pt` 必须写入 SDK 启动阶段已经识别的 PT 目录。本项目已验证目录为：

```text
logs/x1_dh_stand/gm_play/
```

该目录与运行时下载的 `model_5000.pt` 相同。不要依据回放任务名另建 `logs/x1_trajectory/gm_play/`；SDK 可能只记录 `New file detected globally`，却不加入 PT 上传队列。

日志必须依次出现：

- `Found PT file`；
- 放入 upload queue；
- `uploaded successfully`。

仅有 `New file detected globally` 不算上传成功。文件打包完成后保留至少 60 秒，让 SDK 完成扫描和上传。

## 下载与解包

用 `flux task model list --task-id <replay> --page 1 --limit 50` 读取 `data.rows`：

- `fileName=play_output.mp4`：取 `videoUrlDown`；
- `fileName=model_isaac_csv.pt`：取 `policUrlDown`；
- 最终 checkpoint：取对应 `policUrlDown`。

签名 URL 只保存在变量或一次性下载助手中，不输出到对话。Windows `curl` 出现证书吊销离线错误时可使用 `--ssl-no-revoke`。

`model_isaac_csv.pt` 是 `torch.save` 生成的 ZIP/Pickle 包。可信任务产物可用以下结构解包：

```python
import pickle, zipfile
with zipfile.ZipFile("model_isaac_csv.pt") as archive:
    data = pickle.load(archive.open("model_isaac_csv/data.pkl"))
with open("isaac_diag.csv", "wb") as output:
    output.write(data["bytes"])
```

不要解包不可信来源的 Pickle。解包并校验 CSV 后删除临时 PT 包。

F1/X1 默认本地交付目录：

```text
czy/data/exp0/
├── model_<final>.pt
├── play_output.mp4
└── isaac_diag.csv
```

## 成功判定

只有满足以下条件才报告完整成功：

- checkpoint 能被策略加载；
- 视频日志显示保存完成，并出现视频上传成功；
- `model_isaac_csv.pt` 出现 PT 上传成功；
- `model list` 同时包含视频和 CSV 包；
- 本地 MP4 可读取且非空；
- CSV 有表头、有效行和非零大小；
- 交付目录只保留用户要求的最终产物。
