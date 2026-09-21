# Copyright (c) 2024, AgiBot Inc. All rights reserved.
# exp1 DHPPOAMP：DHPPO + AMP 判别器（robolab ppo_amp.py 移植，notes §6.3 改造清单）
#
# 父类 199 行不动，仅三块扩展：
#   1) configure_amp()          —— runner 在 alg 构造后注入 obs 维/num_envs/dt，构建判别器+独立优化器+双缓冲
#   2) process_env_step() 覆写  —— 奖励融合点：站立 env 纯 task，行走 env lerp 融合（融合值进 GAE）
#   3) update() 覆写            —— PPO 标准 flow + 同 mini-batch 判别器 LSGAN 训练（demo-only 梯度惩罚）
#
# 工程要点（照抄 robolab）：
#   - 独立 Adam lr 恒定（KL 自适应只作用 PPO 优化器）；trunk/linear 分组 weight decay 1e-3/1e-1
#   - rollout 时 style reward 用旧判别器参数 no_grad 计算；训练时同批交替无冻结
#   - 归一化统计量事后更新（本批用旧统计量）；CircularBuffer 不清空跨迭代混合
#   - amp 关闭（env 不产 extras["amp"]）时自动退化为纯 task 基线（消融开关）

import torch
import torch.nn as nn
import torch.optim as optim

from .dh_ppo import DHPPO
from humanoid.algo.amp import AMPDiscriminator, CircularBuffer


class DHPPOAMP(DHPPO):

    def __init__(self, *args,
                 amp_enabled=True,
                 amp_disc_obs_steps=3,
                 amp_disc_hidden_dims=(1024, 512),
                 amp_disc_lr=1e-4,
                 amp_grad_penalty_scale=10.0,
                 amp_disc_buffer_size=100,
                 amp_buffer_min_episode_len=-1,   # exp1.5: agent buffer 门控，-1=关闭（旧行为），>=0 启用三重门控
                 amp_style_reward_scale=1.5,
                 amp_style_floor_eps=0.0,   # exp1.5: D<-1 负斜坡下界（0=旧 clamp）
                 amp_task_lerp=0.6,
                 amp_disc_trunk_weight_decay=1e-3,
                 amp_disc_linear_weight_decay=1e-1,
                 amp_disc_max_grad_norm=1.0,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.amp_enabled = bool(amp_enabled)
        self.amp_disc_obs_steps = int(amp_disc_obs_steps)
        self.amp_disc_hidden_dims = list(amp_disc_hidden_dims)
        self.amp_disc_lr = float(amp_disc_lr)
        self.amp_grad_penalty_scale = float(amp_grad_penalty_scale)
        self.amp_disc_buffer_size = int(amp_disc_buffer_size)
        self.amp_buffer_min_episode_len = int(amp_buffer_min_episode_len)
        self.amp_style_reward_scale = float(amp_style_reward_scale)
        self.amp_style_floor_eps = float(amp_style_floor_eps)
        self.amp_task_lerp = float(amp_task_lerp)
        self.amp_disc_trunk_weight_decay = float(amp_disc_trunk_weight_decay)
        self.amp_disc_linear_weight_decay = float(amp_disc_linear_weight_decay)
        self.amp_disc_max_grad_norm = float(amp_disc_max_grad_norm)

        # 由 runner 注入后构建（num_dof/dt 只有 env 知道；在 inference_mode 外构建，
        # 缓冲预分配为普通张量，避免 rollout 期 append 产生推理张量）
        self.amp_discriminator = None
        self.disc_optimizer = None
        self.disc_obs_buffer = None
        self.disc_demo_obs_buffer = None
        self.amp_dt = 0.02  # runner 用 env.dt 覆盖

        self.amp_stats = {}
        self._style_rew_sum = 0.0
        self._style_env_count = 0.0
        self._healthy_sum = 0.0    # exp1.5: buffer 门控健康样本占比监控
        self._healthy_total = 0.0

    def configure_amp(self, disc_obs_dim, num_envs, dt):
        """runner 在 alg 构造后调用（inference_mode 外）：按 env 实际维度构建 AMP 组件"""
        if not self.amp_enabled:
            return
        self.amp_dt = float(dt)
        self.amp_discriminator = AMPDiscriminator(
            disc_obs_dim=int(disc_obs_dim),
            disc_obs_steps=self.amp_disc_obs_steps,
            hidden_dims=self.amp_disc_hidden_dims,
            style_reward_scale=self.amp_style_reward_scale,
            style_floor_eps=self.amp_style_floor_eps,
            device=self.device,
        ).to(self.device)
        # 独立优化器：lr 恒定不被 KL 自适应波及；线性输出层重正则防 logit 漂移
        self.disc_optimizer = optim.Adam(
            [
                {"params": self.amp_discriminator.disc_trunk.parameters(),
                 "weight_decay": self.amp_disc_trunk_weight_decay},
                {"params": self.amp_discriminator.disc_linear.parameters(),
                 "weight_decay": self.amp_disc_linear_weight_decay},
            ],
            lr=self.amp_disc_lr,
        )
        obs_shape = (self.amp_disc_obs_steps, int(disc_obs_dim))
        self.disc_obs_buffer = CircularBuffer(
            self.amp_disc_buffer_size, num_envs, obs_shape, self.device)
        self.disc_demo_obs_buffer = CircularBuffer(
            self.amp_disc_buffer_size, num_envs, obs_shape, self.device)

    def process_env_step(self, rewards, dones, infos):
        if not (self.amp_enabled and self.amp_discriminator is not None and "amp" in infos):
            super().process_env_step(rewards, dones, infos)
            return
        amp = infos["amp"]
        disc_obs = amp["disc_obs"]            # (N, S, D) 原始特征
        disc_demo_obs = amp["disc_demo_obs"]  # (N, S, D)
        stand_mask = amp["stand_mask"]        # (N,) bool

        # 旧参 no_grad 算风格分（eval 语义；值域 [0, dt*scale]）
        style_rewards, disc_score = self.amp_discriminator.predict_style_reward(
            disc_obs, dt=self.amp_dt)

        # 站立 env 纯 task（demo 库全是行走，不 mask 会与 stand_still 打架）；
        # 行走 env：lerp·task + (1-lerp)·style —— 融合值直接进 GAE
        fused = torch.where(stand_mask,
                            rewards,
                            self.amp_task_lerp * rewards
                            + (1.0 - self.amp_task_lerp) * style_rewards)

        # agent 侧三重门控入 buffer（exp1.5 主攻）：站立/终止/复位初期样本不进 D 训练集。
        # 剥掉 D 的平凡可分样本——exp1.3 死锁头号嫌疑：gait 调度 26% 站立段样本 +
        # 复位静止窗 vs 100% 行走 demo，"速度幅度"一维秒分（与 exp1 的 demo 静立窗
        # 问题互为镜像，此番反向修复：agent 侧去站立，无需手造数据）。
        # 开关语义：min_episode_len=-1 完全关闭（旧行为纯 append）；>=0 启用门控
        # （~stand & ~done 恒开，>0 时叠加 episode_length 条件）。demo 侧不门控。
        ep_len = amp.get("episode_length")
        if self.amp_buffer_min_episode_len < 0:
            self.disc_obs_buffer.append(disc_obs)
        else:
            healthy = (~stand_mask) & (~dones.bool())
            if self.amp_buffer_min_episode_len > 0 and ep_len is not None:
                healthy = healthy & (ep_len > self.amp_buffer_min_episode_len)
            self.disc_obs_buffer.append_masked(disc_obs, healthy)
            self._healthy_sum += float(healthy.sum().item())
            self._healthy_total += float(healthy.shape[0])
        self.disc_demo_obs_buffer.append(disc_demo_obs)

        # 监控：style 只统计行走 env（站立 env 无风格梯度）
        walk = ~stand_mask
        self._style_rew_sum += float(style_rewards[walk].sum().item())
        self._style_env_count += float(walk.sum().item())

        super().process_env_step(fused, dones, infos)

    def update(self):
        mean_value_loss = 0
        mean_surrogate_loss = 0
        mean_state_estimator_loss = 0
        use_amp = (self.amp_enabled and self.amp_discriminator is not None
                   and self.disc_obs_buffer is not None
                   and self.disc_obs_buffer.filled_steps > 0)
        mean_disc_loss = 0
        mean_disc_grad_penalty = 0
        mean_disc_score = 0
        mean_disc_demo_score = 0

        generator = self.storage.mini_batch_generator(self.num_mini_batches, self.num_learning_epochs)
        if use_amp:
            # 判别器与 PPO 同频同批：fetch_length = rollout 窗（24 < 缓冲 100）
            disc_obs_gen = self.disc_obs_buffer.mini_batch_generator(
                self.storage.num_transitions_per_env, self.num_mini_batches, self.num_learning_epochs)
            disc_demo_obs_gen = self.disc_demo_obs_buffer.mini_batch_generator(
                self.storage.num_transitions_per_env, self.num_mini_batches, self.num_learning_epochs)
            batches = zip(generator, disc_obs_gen, disc_demo_obs_gen)
        else:
            batches = ((g, None, None) for g in generator)

        for samples, disc_obs_batch, disc_demo_obs_batch in batches:
            (obs_batch, critic_obs_batch, actions_batch, target_values_batch, advantages_batch,
             returns_batch, old_actions_log_prob_batch, old_mu_batch, old_sigma_batch,
             hid_states_batch, masks_batch) = samples

            # ---------------- PPO 标准 flow（与父类逐行一致） ----------------
            self.actor_critic.act(obs_batch, masks=masks_batch, hidden_states=hid_states_batch[0])
            state_estimator_input = obs_batch[:, -self.num_short_obs:]
            est_lin_vel = self.actor_critic.state_estimator(state_estimator_input)
            ref_lin_vel = critic_obs_batch[:, self.lin_vel_idx:self.lin_vel_idx + 3].clone()
            actions_log_prob_batch = self.actor_critic.get_actions_log_prob(actions_batch)
            value_batch = self.actor_critic.evaluate(critic_obs_batch, masks=masks_batch, hidden_states=hid_states_batch[1])
            mu_batch = self.actor_critic.action_mean
            sigma_batch = self.actor_critic.action_std
            entropy_batch = self.actor_critic.entropy

            # KL 自适应 lr（只作用 PPO 优化器，判别器 lr 恒定）
            if self.desired_kl != None and self.schedule == 'adaptive':
                with torch.inference_mode():
                    kl = torch.sum(
                        torch.log(sigma_batch / old_sigma_batch + 1.e-5) + (torch.square(old_sigma_batch) + torch.square(old_mu_batch - mu_batch)) / (2.0 * torch.square(sigma_batch)) - 0.5, axis=-1)
                    kl_mean = torch.mean(kl)

                    if kl_mean > self.desired_kl * 2.0:
                        self.learning_rate = max(1e-5, self.learning_rate / 1.5)
                    elif kl_mean < self.desired_kl / 2.0 and kl_mean > 0.0:
                        self.learning_rate = min(1e-2, self.learning_rate * 1.5)

                    for param_group in self.optimizer.param_groups:
                        param_group['lr'] = self.learning_rate

            ratio = torch.exp(actions_log_prob_batch - torch.squeeze(old_actions_log_prob_batch))
            surrogate = -torch.squeeze(advantages_batch) * ratio
            surrogate_clipped = -torch.squeeze(advantages_batch) * torch.clamp(ratio, 1.0 - self.clip_param,
                                                                               1.0 + self.clip_param)
            surrogate_loss = torch.max(surrogate, surrogate_clipped).mean()

            if self.use_clipped_value_loss:
                value_clipped = target_values_batch + (value_batch - target_values_batch).clamp(-self.clip_param,
                                                                                                self.clip_param)
                value_losses = (value_batch - returns_batch).pow(2)
                value_losses_clipped = (value_clipped - returns_batch).pow(2)
                value_loss = torch.max(value_losses, value_losses_clipped).mean()
            else:
                value_loss = (returns_batch - value_batch).pow(2).mean()

            loss = (surrogate_loss +
                    self.value_loss_coef * value_loss -
                    self.entropy_coef * entropy_batch.mean() +
                    torch.nn.MSELoss()(est_lin_vel, ref_lin_vel))

            self.optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(self.actor_critic.parameters(), self.max_grad_norm)
            self.optimizer.step()

            state_estimator_loss = torch.nn.MSELoss()(est_lin_vel, ref_lin_vel)

            # ---------------- AMP 判别器训练（同 mini-batch，PPO step 之后） ----------------
            if disc_obs_batch is not None:
                with torch.no_grad():  # 本批用旧统计量归一化
                    agent_normed = self.amp_discriminator.normalize_disc_obs(disc_obs_batch)
                    demo_normed = self.amp_discriminator.normalize_disc_obs(disc_demo_obs_batch)
                mb_size = agent_normed.shape[0]
                agent_flat = agent_normed.reshape(mb_size, -1)
                demo_flat = demo_normed.reshape(mb_size, -1)

                disc_score = self.amp_discriminator(agent_flat)
                disc_demo_score = self.amp_discriminator(demo_flat)
                mse = torch.nn.MSELoss()
                # LSGAN: D(agent)→-1, D(demo)→+1
                disc_loss = 0.5 * (mse(disc_score, -torch.ones_like(disc_score))
                                   + mse(disc_demo_score, torch.ones_like(disc_demo_score)))
                disc_grad_penalty = self.amp_discriminator.compute_grad_penalty(
                    demo_flat, scale=self.amp_grad_penalty_scale)

                self.disc_optimizer.zero_grad()
                (disc_loss + disc_grad_penalty).backward()
                nn.utils.clip_grad_norm_(self.amp_discriminator.parameters(),
                                         self.amp_disc_max_grad_norm)
                self.disc_optimizer.step()
                # 事后更新统计量（agent 侧，robolab 同款）
                with torch.no_grad():
                    self.amp_discriminator.update_normalization(disc_obs_batch)

                mean_disc_loss += disc_loss.item()
                mean_disc_grad_penalty += disc_grad_penalty.item()
                mean_disc_score += disc_score.mean().item()
                mean_disc_demo_score += disc_demo_score.mean().item()

            mean_value_loss += value_loss.item()
            mean_surrogate_loss += surrogate_loss.item()
            mean_state_estimator_loss += state_estimator_loss.item()

        num_updates = self.num_learning_epochs * self.num_mini_batches
        mean_value_loss /= num_updates
        mean_surrogate_loss /= num_updates
        mean_state_estimator_loss /= num_updates
        self.storage.clear()  # CircularBuffer 不清空（滑窗跨迭代混合）

        self.amp_stats = {}
        if use_amp:
            self.amp_stats = {
                "disc_loss": mean_disc_loss / num_updates,
                "disc_grad_penalty": mean_disc_grad_penalty / num_updates,
                "disc_score": mean_disc_score / num_updates,
                "disc_demo_score": mean_disc_demo_score / num_updates,
                "style_reward": (self._style_rew_sum / self._style_env_count
                                 if self._style_env_count > 0 else 0.0),
                # exp1.5: 门控健康率（agent 步入 buffer 占比；预期 ~0.5-0.7，趋 0 = 门控过严）
                "buffer_healthy": (self._healthy_sum / self._healthy_total
                                   if self._healthy_total > 0 else -1.0),
            }
        self._style_rew_sum = 0.0
        self._style_env_count = 0.0
        self._healthy_sum = 0.0
        self._healthy_total = 0.0

        return mean_value_loss, mean_surrogate_loss, mean_state_estimator_loss
