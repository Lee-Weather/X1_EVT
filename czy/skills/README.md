# czy/skills 工作流技能指南

四个技能覆盖"克隆仓库 → 跑起实验"的完整链路。**标准使用顺序**：

```
① 注册账号（新机器必做） → ② lab-notebook 立项记录 → ③ 本地冒烟
    → ④a flux-cli 提交云端训练  或  ④b post-201-5 本地机训练/验证
    → 结果回写 ② 实验笔记
```

---

## ① register-limxdynamics-account · 账号注册

**什么时候用**：拉下代码后**必须先做**——仓库不含任何账号信息
（`flux-cli/api_key.json` 被 gitignore，`accounts.md` 凭据也不会随库分发）。

**做什么**：在 internal.limxdynamics.com 注册 **1~2 个**新账号（临时邮箱收验证码 →
设密码 → 配置 GitHub 信息 → 创建 CLI key）。

**产出**：账号 + CLI key → 供 ③ flux-cli 认证使用。
建议注册两个：云端训练按账号计费（额度约 ¥50/个），两个账号便于轮换与并行任务。

---

## ② lab-notebook · 实验笔记

**什么时候用**：每个实验**开题时与过程中**（强制纪律，不是可选）。

**规范**：
- 实验编号制（expN.N），记录文件在 `czy/exp1/*.md`
- 每个实验固定七段式：上一实验结果与教训 → 修改目标 → 修改内容 → 修改文件 →
  训练参数 → 预期与验收（**预注册，不得事后改**）→ 实验结果
- 数据归档约定：checkpoint/回放/诊断 CSV 三件套入 `czy/baseline/<实验编号>/`

**产出**：`czy/exp1/` 下的实验记录；底座状态快照见 `czy/exp1/exp_FW.md`。

---

## ③ flux-cli · 云端训练提交

**什么时候用**：本地冒烟通过后，提交/续训/监控云端训练任务（GM 云，4090D）。

**关键约束**（详见 `flux-cli/SKILL.md`）：
- 认证：`flux auth login`（用 ① 的 CLI key）
- 写操作先 `--dry-run` 预检再正式执行；Agent 非交互环境必须加 `--yes`
- 续训用 git 内置 checkpoint 路线（`--ckpt_path` 指向仓库内路径，跨账号 clone 自动到位）
- 账号额度轮换与镜像配置见 `flux-cli/references/`（accounts.md / git-mirror.md）

**典型命令**：`gm-run X1_EVT/humanoid/scripts/train.py --task=x1_dh_stand --headless --resume --ckpt_path=... --max_iterations=3000`

---

## ④ post-201-5 · 本地机验证 / 备用训练

**什么时候用**：需要把项目传到本地服务器（10.12.201.5，conda `F1` 环境）做
**本地验证**（stab_budget/play 评测）或作为**云端之外的备用训练机**。

**做什么**（详见 `post-201-5/SKILL.md`）：
- rsync 全仓到 `robot@10.12.201.5:~/czy/exp1/exp_<时间戳>/`，注意排除清单
  （`skills/` 凭据、`czy/baseline/`、`*.mp4`、`.git/` 等大件）
- 远程：`conda activate F1` → `pip install -e .` → `python humanoid/scripts/train.py ...`

---

## 注意

- `flux-cli/api_key.json` 是凭据，已被 .gitignore 拦截，**任何时候不得提交或外发**
- 四个技能中只有 ① 是"新环境必做"，② 是"每个实验必做"，③④ 按算力需要二选一或并用
