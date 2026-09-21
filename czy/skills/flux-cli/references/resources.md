# F1/X1 镜像与算力选择

## 选择原则

创建任务前先查询当前平台资源，不要只依赖硬编码推荐：

```text
flux task resource list --goods-back-category 3 --page 1 --limit 20
flux task image official
flux task image versions --image-id <image>
```

flux-cli `1.1.0` 已验证 RL 与 VLA 共用资源类别 `3`；类别 `6` 当前返回空列表，不要使用。

字段含义：

- `goodsId`：填写 `taskBaseInfo.goodsId`；
- `goodsBackId`：后端 SKU 标识，只有接口要求时填写对应字段；
- `goodsBackSku.gpuNum`：填写 GPU 数量；
- 镜像版本返回中的 `id`：填写 `taskBaseInfo.imageVersion`；
- `versionCode`：仅供展示，不能代替版本 `id`。

## 当前项目已验证配置

F1/X1 的 Isaac Gym RL 训练与回放已验证：

| 配置 | 值 |
|---|---|
| 算力（**首选**） | `ESKU000005`（1×L20 48G，¥8.31/时）——**exp0.2 起用户指定优先使用**，exp0.1~exp0.2 已验证 |
| 算力（备选） | `ESKU000001`（1×4090D 24G，¥5.4/时）——exp0.1 曾验证；新任务默认不再选用 |
| 镜像 ID | `BJX00000001` |
| 镜像版本 | `V000124` |
| GPU 数量 | 1 |
| 运行环境 | Isaac Gym Preview 4 / Python 3.8 / PyTorch 2.4.x |

> 创建训练任务时默认选 `ESKU000005`（L20），除非用户明确指定其他资源或其下架。

推荐值只在平台查询仍返回该资源和镜像时使用。若已下架或版本变化，选择兼容 Isaac Gym Preview 4、CUDA、Python 和 PyTorch 的最新可用镜像，并记录实际选择。

## 创建与恢复规则

- 新建 RL 任务使用 `trainType=1`。
- 恢复训练通常使用 `trainType=2`，并复用源任务的算力、镜像、代码和 checkpoint 元数据。
- Isaac Gym 回放的 checkpoint 挂载已验证不可靠，回放仍使用 `trainType=1` + 运行时下载。
- RL `startScript` 必须以 `gm-run` 开头，即使客户端命令已经改为 `flux`。
- VLA 任务通常不传 `startScript`，由底模配置自动生成运行命令。

## 提交前检查

提交 payload 前确认：

- `projectId`、`goodsId`、`imageId`、`imageVersion` 存在；
- Git 分支已推送且平台有权限读取；
- `mainCodeUri` 与 `startScript` 使用 clone 后的仓库路径；
- `hparamsPath` 包含仓库目录前缀；
- 恢复训练的 checkpoint 来自 `model list`，不要猜测对象路径；
- 先执行 `--dry-run`，确认后再正式提交。
