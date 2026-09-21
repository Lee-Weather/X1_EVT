# X1_EVT · 人形运动论文算法验证底座

## 项目定位与 Baseline

本仓库由智元灵犀 X1 官方强化学习训练代码改造而来，定位为**人形运动论文算法的验证底座**：

- **算法底座**：`humanoid/` —— Isaac Gym 上的 X1 29DOF 全身行走栈
  - 任务 `x1_dh_stand`：PPO（KL 自适应）+ 状态估计器 + mocap 查表参考 + AMP 风格奖励
- **Baseline**：`exp2.1` 纯减法配置，checkpoint 见 `czy/baseline/exp2.1/model_40996.pt`
  - 对照基线数值（512env × 3ep 训练域预算表协议，详见 `czy/exp1/exp_FW.md` §6）：

    | 指标 | 基线值 |
    | --- | --- |
    | 提前终止率 | **12.8%**（198/1551） |
    | 终止原因主因 | h<0.45 占 84%（h 线是最早探测器，非误判） |
    | 腾空占行走时间 | 7.83%（终止前 0.5s 激增 3 倍 = 因果签名） |
    | AMP style | ~0.15（良性旁观区） |

- **验证流程**：同环境、同预算、只换算法 → `train.py` 训练 → `stab_budget.py` 评测 → 对照上表
- **算法插入边界**：
  - 只动 `humanoid/algo/` 层（PPO 变体、正则化、奖励重加权等）→ 可直接做
  - 替换/增强 AMP 契约的算法（ASE/CALM 类，env 内嵌 `_sample_amp`）→ 建议先完成 env 解耦，避免污染对照组（单变量原则，同 exp 记录纪律）
- 代码现状快照：`czy/exp1/exp_FW.md`；完整实验史与验收纪律：`czy/exp1/exp1.md`、`exp2.md`

## 代码运行

### 安装依赖
1. 创建一个新的 python3.8 虚拟环境:
   - `conda create -n myenv python=3.8`
2. 安装 pytorch 1.13 和 cuda-11.7:
   - `conda install pytorch==1.13.1 torchvision==0.14.1 torchaudio==0.13.1 pytorch-cuda=11.7 -c pytorch -c nvidia`
3. 安装 numpy-1.23:
   - `conda install numpy=1.23`
4. 安装 Isaac Gym:
   - 下载并安装 Isaac Gym Preview 4 https://developer.nvidia.com/isaac-gym
   - `cd isaacgym/python && pip install -e .`
5. 安装本仓库：
   - `pip install -e .`

### 训练
```bash
python humanoid/scripts/train.py --task=x1_dh_stand --run_name=<run_name> --headless
```
从 baseline 续训：
```bash
python humanoid/scripts/train.py --task=x1_dh_stand --headless --resume \
    --ckpt_path=czy/baseline/exp2.1/model_40996.pt --max_iterations=3000
```
- 模型存于 `logs/<experiment_name>/<date_time>_<run_name>/model_<iteration>.pt`

### 回放与评测
```bash
# 策略回放
python humanoid/scripts/play.py --task=x1_dh_stand --load_run=<date_time>_<run_name>

# 稳定性预算表（对照 baseline 的标准仪器，512env×3ep）
SB_CKPT=<checkpoint路径> SB_OUT=<输出目录> python humanoid/scripts/stab_budget.py
python humanoid/scripts/stab_budget_report.py --csv <输出目录>/stab_budget.csv

# 速度阶梯回放
python humanoid/scripts/play_speed_sweep.py --task=x1_dh_stand ...
```

### 导出
```bash
python humanoid/scripts/export_policy_dh.py --task=x1_dh_stand --load_run=<date_time>_<run_name>   # JIT
python humanoid/scripts/export_onnx_dh.py   --task=x1_dh_stand --load_run=<date_time>_<run_name>   # ONNX
```

### 数据管线（scripts/tools）
```bash
python scripts/tools/prep_mocap_ref.py    # resources/x1_gmr → ref_lib.pt（3 段）
python scripts/tools/prep_yz_ref.py       # resources/motions/raw/yz_walk.csv → ref_lib.pt 第 4 段
python scripts/tools/urdf2mjcf.py         # URDF → MJCF 场景
python scripts/tools/play_motion_mujoco.py --motion 0000_treadmill_norm   # mocap 回放（可 --record 录屏）
```
> 注：策略 sim2sim 脚本本仓暂缺，参考实现见 `czy/diff/roboparty_train/robolab/scripts/mujoco/`。

### 参数说明
- `task`: 任务名（当前注册：`x1_dh_stand`）
- `resume`: 从 checkpoint 续训；`ckpt_path`: 直接指定 checkpoint
- `experiment_name` / `run_name` / `load_run` / `checkpoint`: 实验与加载命名
- `num_envs` / `seed` / `max_iterations`: 并行数 / 随机种子 / 最大轮数

### 添加新环境
1. 在 `humanoid/envs/` 下新建文件夹，创建 `<your_env>_config.py` 与 `<your_env>_env.py`，分别继承 `LeggedRobotCfg` 和 `LeggedRobot`
2. 新机器的 urdf / mesh / mjcf 放入 `resources/robots/`
3. 在 `humanoid/envs/__init__.py` 注册新任务

## 目录结构
```
.
├── humanoid/            # 底座主代码
│   ├── algo/            #   算法层（DHPPO / DHPPO-AMP / 判别器 / Runner）
│   ├── envs/            #   环境层（base 基类 + x1 任务）
│   ├── scripts/         #   train / play / stab_budget 评测 / export
│   └── utils/           #   task_registry / 工具
├── scripts/tools/       # 数据管线（mocap 预处理、URDF→MJCF、MuJoCo 回放）
├── resources/           # 运行资产（urdf/mjcf/mesh/mocap 正本/ref_lib.pt/retarget 配置）
├── czy/                 # 参考与档案区（不参与运行链路）
│   ├── baseline/        #   exp2.1 基线 checkpoint + 评测数据
│   ├── exp1/            #   实验记录（exp_FW.md = 代码现状快照）
│   ├── plan/            #   方案与算法笔记
│   ├── diff/            #   Isaac Lab 迁移参考（roboparty_train，读代码用）
│   └── skills/          #   云训练/实验工作流技能（用法见 czy/skills/README.md）
├── logs/                # 训练输出（gitignore）
└── setup.py
```

## 参考

* [legged_gym](https://github.com/leggedrobotics/legged_gym) · [rsl_rl](https://github.com/leggedrobotics/rsl_rl) · [humanoid-gym](https://github.com/roboterax/humanoid-gym)
* 上游：[智元灵犀 X1](https://www.zhiyuan-robot.com/qzproduct/169.html)（AimRT 中间件 + RL 运动控制）
