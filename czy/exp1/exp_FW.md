# exp_FW.md · X1_EVT 代码现状总结（底座化前快照）

> 写于 2026-09-21。用途：把 `czy/exp1/` 三份实验记录（exp1.md、exp2.md、exp1_12dof_legacy.md）
> 中与**代码现状**相关的信息收敛为一页，作为"改造为论文算法验证底座"的起点快照。
> 实验细节、判据、逐轮监控都在原三份记录里，本文只留结论和指针。

---

## 1. 一句话定位

本仓库是 AgiBot X1 官方 RL 训练代码（legged_gym + rsl_rl + humanoid-gym 血统）的深度改造版，
当前形态是 **"X1 29DOF 全身行走 + mocap 参考查表 + AMP 风格模仿"** 的单一任务实验项目
（`x1_dh_stand`，名字里的 stand 已是历史遗留，实际做行走）。
下一步目标：剥离实验性 hack，改造为**论文算法验证底座**（算法部分 = `humanoid/`）。

- 本地目录：`X1_EVT`；远端：`github.com/Lee-Weather/X1_29_amp`（公开仓，exp2.1 = commit 8ec2a59）
- 训练环境：Isaac Gym Preview 4 + py3.8（本机 F1 环境）；云端 Flux 4090D（`gm-run` 启动，git 内置 checkpoint 路线）
- 当前基线 checkpoint：`model_40996.pt`（exp2.1），归档在 `czy/baseline/exp2.1/`（含回放视频 + isaac_diag.csv）

## 2. 代码架构总览

```
humanoid/                     ← 算法底座本体（~9.5k 行）
├── envs/
│   ├── base/legged_robot.py          基类 1359 行（sim 构建/PD 控制/奖励调度/域随机化）
│   ├── base/legged_robot_config.py   配置基类（声明式 reward scales + _reward_* 命名约定）
│   └── x1/
│       ├── x1_dh_stand_env.py        1420 行：步态钟/mocap 查表/AMP 采样/33 项奖励（混杂，待拆）
│       └── x1_dh_stand_config.py     623 行：全部超参 + 逐条 exp 注释（决策史在注释里）
├── algo/
│   ├── ppo/dh_on_policy_runner.py    Runner 359 行：rollout 循环 + eval() 字符串注入算法/网络类
│   ├── ppo/dh_ppo.py                 标准 PPO（KL 自适应 lr + state_estimator MSE）
│   ├── ppo/dh_ppo_amp.py             AMP 版：style 奖励融合 + 判别器同批训练
│   ├── ppo/actor_critic_dh.py        ActorCriticDH（MLP + short 历史栈 + state_estimator）
│   ├── amp/amp_discriminator.py      LSGAN 判别器（3 步窗 × 61 维 = ang3+dof_pos29+dof_vel29）
│   └── amp/amp_buffers.py            CircularBuffer（滑窗 100 步，跨迭代混合）
├── utils/                            task_registry / helpers / logger / terrain / math
└── scripts/                          train / play / play_speed_sweep / stab_budget(+report) / export_*

scripts/tools/                ← 数据管线（离线，不进训练链路）
├── prep_mocap_ref.py         x1_gmr/*.npz → motions/processed/ref_lib.pt
├── prep_yz_ref.py            yz CSV → ref_lib.pt（exp1.9 修复版：慢放×4 + 右侧符号）
├── urdf2mjcf.py              URDF → MJCF（x1_29dof_raw/scene.xml）
└── play_motion_mujoco.py     mocap 回放 + 录屏（sim2sim 前置核查）

resources/                    ← 资产（详见根目录分析）
├── robots/x1/urdf/X1_29DOF_physically_mirrored.urdf   ← 训练实际加载（右臂限位镜像已修）
├── robots/x1/mjcf/xyber_x1_flat.xml                    ← sim2sim / play 用
├── motions/processed/ref_lib.pt                        ← 参考动作库（dict：walk_norm/turn/slow/yz 4 段）
└── x1_gmr/ x1_lab/                                     ← 14 段重定向 mocap（npz+pkl，可由管线再生）

czy/                          ← 参考区（不进 humanoid 链路）
├── plan/  diff/  skills/     方案 / 上游对比代码 / 工作流技能
├── baseline/exp2.1/          当前基线三件套（已从 gitignore 放行）
└── exp1/                     实验记录（本文件所在）
```

**维度口径**：obs 98（短历史栈）/ privileged 141 / action 29（腿 12 + 腰 3 + 臂 14）；
Isaac dof 序为字母序（左腿 0-5/腰 6-8/左臂 9-15/右臂 16-22/右腿 23-28），env 按关节名索引腿部。

## 3. 算法栈现状

| 组件 | 现状 | 关键点 |
| --- | --- | --- |
| PPO | DHPPO，KL 自适应 lr（1e-5 下限），clip + value clip + entropy | 标准 flow，无特殊改动 |
| 状态估计 | ActorCritic 内置 state_estimator（short obs → lin_vel），MSE 并入 PPO loss | critic 侧喂真值，actor 侧用估计 |
| AMP | DHPPOAMP：LSGAN 判别器 + style 奖励 | `rew = max(1-(D-1)²/4, eps·(D+1))`；行走 env `0.6·task + 0.4·style`，站立 env 纯 task；grad penalty 仅 demo 侧；D 独立 Adam（lr 恒定 + 分层 weight decay）；EMA 归一化统计事后更新 |
| AMP 门控 | agent buffer 三重门控（exp1.5） | 行走 & 未终止 & ep_len>50 才入 D 训练集；`--disc_fresh` 支持判别器从零重初始化 |
| 参考轨迹 | mocap 查表（use_mocap_ref=True） | ref_lib.pt 4 段，50Hz 全身查表（腿臂同源同拍），行走 env 的 ref 整表覆盖 ref_dof_pos |
| 步态钟 | 持久积分相位，周期随指令自适应 | `seg_demo_speed_table` + `gait_scale_clamp [0.5,1.6]`；双支撑窗 `double_support_k`（**当前=0.1**，exp1.13 曾加宽到 0.25、exp2.1 撤销） |
| gait 调度 | 出生站立 + [walk, stand, walk] | exp0.3 引入，治"出生必行走/停不住" |
| 域随机化 | 推力 + 摩擦 + 质量等全套 | 训练地形 **plane**（exp1.13 起，train/play 彻底一致） |
| 奖励 | 33 项生效（`torso_pitch_lpf` 已归零移除） | `feet_contact_number` 在 config 定义了两次（L429=2.0 / L450=2.4），生效 2.4 —— 已知 wart |

## 4. 当前代码配置状态（= exp2.1，HEAD）

相对上一代的关键开关（都在 `x1_dh_stand_config.py`，带 exp 注释）：

| 开关 | 当前值 | 来历 |
| --- | --- | --- |
| `terrain.mesh_type` | `plane` | exp1.13（此前 trimesh 20×20 + ±4m 出生抖动是主要扰动源） |
| `rewards.double_support_k` | `0.1` | exp2.1 撤销 exp1.13 的 0.25（纯减法基线） |
| `rewards.scales.torso_pitch_lpf` | `0.0`（保留实现） | exp2.1 归零，与 exp2.0 构成单变量对照 |
| `rewards.scales.ref_joint_pos` | `0.5` | exp1.3 半值恢复（全量会压制步态，全零保不住姿态） |
| action_scale / smoothness | 0.3 / ×2.5（clip 3） | exp0.3 治 bang-bang 前扑 |
| 手臂 EMA 滤波 | α=1.0（撤除） | exp1.6 云端 A/B 实锤无益 |
| 判别器 | 延续（不加 --disc_fresh） | exp1.13 起 |

## 5. 实验历程速览（细节看原记录）

| 阶段 | 记录 | 一句话结论 |
| --- | --- | --- |
| 12DOF 旧项目 | exp1_12dof_legacy.md | armature 逐关节对齐真机阶跃辨识 → 跟踪率 71%→99%；侧漂根因=髋 pitch armature 左右不对称 |
| exp0（29DOF 基线） | exp1.md | 按名索引腿部 + 29 维 config 立起来；回放摔、过冲、停不住 |
| exp0.2–0.3 | exp1.md | mocap 查表行走跑通；压幅度+出生站立后"站得住不摔"（0.4/0.6 段原地踏步） |
| exp1–1.5（AMP 死锁系列） | exp1.md | 判别器死锁三根因：**平凡可分**（站立样本 vs 全行走 demo）、**量纲淹没**（style 上限比 task 低 60 倍）、**静立窗位形错配**；破法=三重门控 + disc_fresh + 负斜坡下界；exp1.2 教训：监控三绿可能是"站立体化"假阳性 |
| exp1.7–1.12 | exp1.md | 速度自适应步频、髋交替发生器、yz 参考修复（慢放×4+右符号）、foot_place 落点锚、termination 收紧；§21 排查 train/play 割裂（action 延迟 400ms 之谜） |
| exp1.13（稳定性专项） | exp1.md §13 | 地形改 plane；512env 预算表确立：提前终止 12.8%、**84% 由 h<0.45 主导**；判别出"腾空×roll 摆动正反馈"，**腾空本身不足以致摔**（稳定组腾空发生在 h≈0.62 正常高度）；加宽双支撑 k=0.25 上云 |
| exp2.0（俯仰约束） | exp2.md | 加约束路线失败：均值有效、重尾恶化（终止率 21.3%，pitch 终止 4 倍） |
| **exp2.1（当前基线）** | exp2.md | **纯减法**：仅撤 k + torso_pitch_lpf 归零；底模 37997 续 3000 轮 → model_40996.pt；确立"多环境预算表终止率"为唯一有效稳定性仪器 |

## 6. 当前基线画像与已知问题

**基线协议**（exp2.1 起，所有新实验对照这组数）：512 env × 3 ep、同 seed 123145、训练域全开
（plane + domain_rand + noise + gait 调度 + push），采集用 `stab_budget.py` + `stab_budget_report.py`：

| 指标 | exp1.12 基线值 | 说明 |
| --- | --- | --- |
| 提前终止率 | **12.8%**（198/1551） | 主判据；Mean ep_len 因 79% timeout 稀释**不能作判据** |
| 终止原因 | h<0.45 占 84%，姿态线仅 16% | h 线是最早探测器，不是误判 |
| 腾空 | 占行走 7.83%，≥50ms 事件 4040 次 | 训练分布常态；终止前 0.5s 激增 3 倍（因果签名） |
| speed_ratio | 健康组 ~0.64，失败组 0.27–0.46 | 两极分化=鲁棒性方差问题，不是缺约束 |

**未解决的已知问题**（按优先级）：
1. **速度饱和 ~0.5 m/s**（§20）：指令 0.19→1.04 变 5 倍，实测只从 0.36→0.48；低档超速、高档欠速
2. **h<0.45 塌陷**：正反馈环（腾空无法调 roll × roll 摆动），加约束已两次失败，纯减法是唯一有正面证据的方向
3. **AMP style 仅 ~0.15**：D 处于"良性旁观"，风格通道未真正起作用（死锁教训完备但破局未完成）
4. 名义/训练域口径二分、profile 段步数 ×2、视频 fps 50 等口径遗留

## 7. 方法论资产（底座直接继承）

- **验收纪律**（lab-notebook skill）：实验编号制、预注册判据、单变量对照、"上一实验结果与教训"开头的归因链
- **稳定性仪器**：`stab_budget.py`（512env 预算表）> 单 env 回放（两次被证伪）> 训练日志 reward/ep_len（稀释+假阳性）
- **AMP 避坑清单**：平凡可分、量纲淹没、reset 污染、buffer 门控、监控假阳性（三绿 ≠ 健康）
- **sim2real 先验**：armature 阶跃辨识方法论（GENERAL_JOINT_STEP_DYNAMICS 文档，真机膝惯量≈URDF 3.2 倍）
- **云端训练流**：flux-cli 技能（git 内置 checkpoint、跨账号 clone、--dry-run 预检、曝光量归因统计）

## 8. 底座化改造待办（已识别，未实施）

1. `git init` 建基线（首个 commit 前完成 .gitignore 修正：`!ref_lib.pt` 白名单、mocap 大数据目录忽略）
2. env 去算法化：`infos["amp"]`、`_init_amp`、`_sample_amp` 从 x1_dh_stand_env 抽成可选 provider 接口
3. runner 泛化：log/save 里硬编码的 `state_estimator_loss`、AMP stats 改为通用 metrics dict
4. `x1_dh_stand_env.py`（1420 行）按 rewards / ref / gait-clock / amp 拆分
5. 新论文算法 = `algo/<name>/` 一个子包 + 一份 config（照抄 DHPPOAMP 的注入模式）
6. 评测标准化：stab_budget + play_speed_sweep 固化为默认验收工具
