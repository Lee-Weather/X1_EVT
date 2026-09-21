# Copyright (c) 2024, AgiBot Inc. All rights reserved.
# exp1 AMP 判别器：robolab rsl_rl/modules/amp.py 移植（LSGAN 专用精简版）
#
# - 输入 (N, disc_obs_steps, disc_obs_dim)，逐单步 EmpiricalNormalization 后展平进 MLP
#   61 维/步 = root_ang_vel(3, 体轴) + dof_pos(29, 绝对角) + dof_vel(29)，×3 步窗 = 183
# - style reward = clamp(1 - (D-1)^2/4, min=0) × dt × scale（LSGAN 映射：有界、免指数、
#   乘 dt 后与控制频率解耦，换频率免重调 scale）
# - 梯度惩罚只加 demo 侧（AMP 论文标准），见 compute_grad_penalty

import torch
import torch.nn as nn
from torch import autograd


class EmpiricalNormalization(nn.Module):
    """逐维经验归一化（robolab networks/normalization.py 移植）

    统计量以 buffer 注册，随 state_dict 一起保存/恢复；update 仅在 train 模式生效，
    count 超过 until 后冻结（robolab 用 1e8：约前 200 iter 积累，之后固定统计量）。
    """

    def __init__(self, shape, eps=1e-2, until=1e8):
        super().__init__()
        self.eps = eps
        self.until = until
        self.register_buffer("_mean", torch.zeros(shape).unsqueeze(0))
        self.register_buffer("_var", torch.ones(shape).unsqueeze(0))
        self.register_buffer("_std", torch.ones(shape).unsqueeze(0))
        self.register_buffer("count", torch.tensor(0, dtype=torch.long))

    def forward(self, x):
        return (x - self._mean) / (self._std + self.eps)

    @torch.jit.unused
    def update(self, x):
        if not self.training:
            return
        if self.until is not None and self.count >= self.until:
            return
        count_x = x.shape[0]
        self.count += count_x
        rate = count_x / self.count
        var_x = torch.var(x, dim=0, unbiased=False, keepdim=True)
        mean_x = torch.mean(x, dim=0, keepdim=True)
        delta_mean = mean_x - self._mean
        self._mean += rate * delta_mean
        self._var += rate * (var_x - self._var + delta_mean * (mean_x - self._mean))
        self._std = torch.sqrt(self._var)


class AMPDiscriminator(nn.Module):
    """LSGAN 判别器：trunk MLP + 线性输出层（分层 weight decay 由 optimizer 负责）"""

    def __init__(self,
                 disc_obs_dim,          # 单步特征维（29DOF: 3+29+29=61）
                 disc_obs_steps=3,      # 时间窗控制步数
                 hidden_dims=(1024, 512),
                 style_reward_scale=1.5,
                 style_floor_eps=0.0,   # exp1.5: D<-1 区负斜坡下界系数（0=旧 clamp 行为）
                 device="cpu"):
        super().__init__()
        self.disc_obs_dim = int(disc_obs_dim)
        self.disc_obs_steps = int(disc_obs_steps)
        self.input_dim = self.disc_obs_dim * self.disc_obs_steps
        self.style_reward_scale = style_reward_scale
        self.style_floor_eps = float(style_floor_eps)
        self.device = device

        # 逐单步归一化（61 维），与 MLP 输入展平解耦
        self.disc_obs_normalizer = EmpiricalNormalization(self.disc_obs_dim).to(device)

        layers = []
        in_dim = self.input_dim
        for h in hidden_dims:
            layers.append(nn.Linear(in_dim, h))
            layers.append(nn.ELU())
            in_dim = h
        self.disc_trunk = nn.Sequential(*layers)
        self.disc_linear = nn.Linear(in_dim, 1)
        print("[AMP] Discriminator MLP: {} -> {}".format(
            self.disc_trunk, self.disc_linear))

    def forward(self, x):
        """x: (N, steps*dim) 已归一化展平特征 → logit (N, 1)"""
        return self.disc_linear(self.disc_trunk(x))

    def normalize_disc_obs(self, disc_obs):
        """(N, S, D) 用当前统计量归一化（不更新统计量、不记梯度）"""
        assert disc_obs.dim() == 3, "判别器观测须为 (N, steps, dim) 三维"
        assert disc_obs.shape[1] == self.disc_obs_steps and disc_obs.shape[2] == self.disc_obs_dim, \
            "判别器观测维度错位: 期望 ({}, {}), 实际 {}".format(
                self.disc_obs_steps, self.disc_obs_dim, tuple(disc_obs.shape[1:]))
        n = disc_obs.shape[0]
        flat = disc_obs.reshape(-1, self.disc_obs_dim)
        return self.disc_obs_normalizer(flat).reshape(n, self.disc_obs_steps, self.disc_obs_dim)

    def update_normalization(self, disc_obs):
        """事后更新统计量（本批训练用旧统计量，避免同批既训练又定义归一化）"""
        flat = disc_obs.reshape(-1, self.disc_obs_dim)
        self.disc_obs_normalizer.update(flat)

    def compute_grad_penalty(self, demo_data, scale=10.0):
        """demo_data: (N, steps*dim) 已归一化。梯度惩罚只加 demo 侧（AMP 论文标准）"""
        demo_data_copy = demo_data.clone().detach().requires_grad_(True)
        disc = self.forward(demo_data_copy)
        ones = torch.ones_like(disc)
        grad = autograd.grad(
            outputs=disc, inputs=demo_data_copy,
            grad_outputs=ones, create_graph=True,
            retain_graph=True, only_inputs=True)[0]
        return scale * grad.norm(2, dim=1).pow(2).mean()

    def predict_style_reward(self, disc_obs, dt):
        """rollout 期风格分：旧参 no_grad 计算

        exp1.5: rew = maximum(clamp 曲线, eps*(D+1) 负斜坡)——
        D ∈ (-1,1) 与旧公式逐点一致（量纲零扰动）；D < -1 旧公式 clamp 平顶梯度为 0
        （D 过冲自信时 policy 完全失联），负斜坡保证任何 D 值下梯度通道不断流，
        且 D 越负 style 越负（连续惩罚，经 alg 层融合直接进 GAE，不受 env 侧
        only_positive_rewards 截断）。诚实定位：保险丝——exp1.3 死锁值 -0.994 在
        梯度区（rew≈0.006 是淹没级而非零级），主攻是 buffer 门控与 D 重置。

        Returns:
            style_reward (N,): dt × scale × maximum(1-(D-1)²/4, eps·(D+1))
            disc_score (N,):   判别器原始 logit（监控用）
        """
        assert disc_obs.dim() == 3
        was_training = self.training
        with torch.no_grad():
            self.eval()
            normed = self.normalize_disc_obs(disc_obs).reshape(-1, self.input_dim)
            disc_score = self.forward(normed)
            rew = 1 - 0.25 * torch.square(disc_score - 1)
            if self.style_floor_eps > 0.0:
                rew = torch.maximum(rew, self.style_floor_eps * (disc_score + 1))
            else:
                rew = torch.clamp(rew, min=0)
            style_reward = dt * self.style_reward_scale * rew
            if was_training:
                self.train()
        return style_reward.squeeze(-1), disc_score.squeeze(-1)
