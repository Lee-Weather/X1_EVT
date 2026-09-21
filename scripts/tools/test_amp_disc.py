#!/usr/bin/env python3
# Copyright (c) 2024, AgiBot Inc. All rights reserved.
# exp1 AMP 离线单测（torch-only，无需 isaacgym/GPU）
# 运行：python3 scripts/tools/test_amp_disc.py（仓库根目录）
#
# 覆盖：
#   1. EmpiricalNormalization   统计收敛 / eval 不更新 / until 冻结
#   2. CircularBuffer           FIFO 淘汰 / 采样形状与可整除校验 / fetch 越界拒绝
#   3. AMPDiscriminator         维度错位断言 / style reward 值域 [0, dt*scale]
#   4. LSGAN 收敛 sanity        可分簇合成数据 → D(demo)→+1, D(agent)→-1（含 demo-only 梯度惩罚）
#   5. DHPPOAMP 端到端迷你训练  inference_mode 采集（同 runner.learn）→ update() 反向：
#                              验证缓冲无推理张量污染、站立掩码融合数学、amp_stats 产出、缓冲 FIFO

import os
import sys
import types

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _ROOT)

# algo 包 __init__ 链会拉入 runner → wandb；本地无 wandb 时打桩（算法侧单测用不到）
try:
    import wandb  # noqa: F401
except ImportError:
    sys.modules["wandb"] = types.ModuleType("wandb")

import torch

from humanoid.algo.amp import AMPDiscriminator, CircularBuffer, EmpiricalNormalization
from humanoid.algo.ppo.actor_critic_dh import ActorCriticDH
from humanoid.algo.ppo.dh_ppo_amp import DHPPOAMP

torch.manual_seed(0)
_RESULTS = []


def check(name, cond):
    _RESULTS.append((name, bool(cond)))
    print("[{}] {}".format("PASS" if cond else "FAIL", name))


# ---------------------------------------------------------------- 1. 归一化
def test_normalization():
    norm = EmpiricalNormalization(4)
    x = torch.randn(4096, 4) * 2.0 + 3.0
    norm.update(x)
    check("norm.mean ≈ 3", torch.allclose(norm._mean.squeeze(0), torch.full((4,), 3.0), atol=0.05))
    check("norm.std ≈ 2", torch.allclose(norm._std.squeeze(0), torch.full((4,), 2.0), rtol=0.05))
    y = norm(x)
    check("norm 后均值≈0/标准差≈1",
          y.mean().abs() < 0.05 and (y.std() - 1.0).abs() < 0.05)

    cnt = int(norm.count)
    norm.eval()
    norm.update(torch.randn(64, 4))
    check("eval 模式不更新统计量", int(norm.count) == cnt)

    frozen = EmpiricalNormalization(2, until=100)
    frozen.update(torch.randn(60, 2))
    frozen.update(torch.randn(60, 2))   # 跨过 until=100
    m = frozen._mean.clone()
    frozen.update(torch.randn(60, 2) + 50.0)
    check("until 冻结统计量", torch.equal(frozen._mean, m))


# ---------------------------------------------------------------- 2. 环形缓冲
def test_buffer():
    buf = CircularBuffer(max_len=4, batch_size=2, obs_shape=(3,), device="cpu")
    for t in range(6):   # 追加 0..5，容量 4 → 滚动淘汰 0,1
        buf.append(torch.full((2, 3), float(t)))
    check("filled_steps 封顶 max_len", buf.filled_steps == 4)
    marks = sorted(set(buf._buffer[:, :, 0].flatten().tolist()))
    check("FIFO 淘汰最旧（剩 2,3,4,5）", marks == [2.0, 3.0, 4.0, 5.0])

    count = 0
    shapes = set()
    for batch in buf.mini_batch_generator(fetch_length=4, num_mini_batches=2, num_epochs=2):
        shapes.add(tuple(batch.shape))
        count += 1
    check("mini_batch 数 = epochs×mb（2×2）", count == 4)
    check("mini_batch 形状 (batch×fetch/mb, 3)", shapes == {(4, 3)})

    try:
        next(buf.mini_batch_generator(fetch_length=8, num_mini_batches=1, num_epochs=1))
        ok = False
    except ValueError:
        ok = True
    check("fetch_length 超有效步数被拒绝", ok)


# ---------------------------------------------------------------- 3. 判别器
def test_discriminator():
    disc = AMPDiscriminator(disc_obs_dim=61, disc_obs_steps=3,
                            hidden_dims=[32, 16], style_reward_scale=1.5)
    obs = torch.randn(8, 3, 61)
    style, score = disc.predict_style_reward(obs, dt=0.02)
    check("style 形状 (N,)", style.shape == (8,))
    check("score 形状 (N,)", score.shape == (8,))
    check("style 值域 [0, dt*scale=0.03]",
          (style >= 0).all().item() and (style <= 0.02 * 1.5 + 1e-6).all().item())

    try:
        disc.predict_style_reward(torch.randn(8, 2, 61), dt=0.02)
        ok = False
    except AssertionError:
        ok = True
    check("窗步数错位触发断言", ok)

    gp = disc.compute_grad_penalty(torch.randn(8, 3 * 61), scale=10.0)
    check("梯度惩罚为正标量", gp.dim() == 0 and gp.item() > 0)


# ---------------------------------------------------------------- 4. LSGAN 收敛
def test_lsgan_convergence():
    disc = AMPDiscriminator(disc_obs_dim=4, disc_obs_steps=1,
                            hidden_dims=[64, 32], style_reward_scale=1.5)
    opt = torch.optim.Adam(disc.parameters(), lr=1e-3)
    agent = torch.randn(2048, 1, 4)          # 簇 A：均值 0
    demo = torch.randn(2048, 1, 4) + 3.0     # 簇 B：均值 3（线性可分）
    mse = torch.nn.MSELoss()
    disc.train()
    for _ in range(300):
        with torch.no_grad():
            an = disc.normalize_disc_obs(agent)
            dn = disc.normalize_disc_obs(demo)
        d_a = disc(an.reshape(-1, 4))
        d_d = disc(dn.reshape(-1, 4))
        loss = 0.5 * (mse(d_a, -torch.ones_like(d_a)) + mse(d_d, torch.ones_like(d_d)))
        gp = disc.compute_grad_penalty(dn.reshape(-1, 4), scale=10.0)
        opt.zero_grad()
        (loss + gp).backward()
        opt.step()
        with torch.no_grad():
            disc.update_normalization(agent)
    with torch.no_grad():
        s_demo, _ = disc.predict_style_reward(demo[:64], dt=0.02)
        s_agent, _ = disc.predict_style_reward(agent[:64], dt=0.02)
        d_demo = disc(disc.normalize_disc_obs(demo[:256]).reshape(-1, 4)).mean()
        d_agent = disc(disc.normalize_disc_obs(agent[:256]).reshape(-1, 4)).mean()
    check("D(demo) → +1（≥0.5）", d_demo.item() > 0.5)
    check("D(agent) → -1（≤-0.5）", d_agent.item() < -0.5)
    check("demo 风格分高于 agent（>0.02 vs ≈0）",
          s_demo.mean().item() > 0.02 and s_agent.mean().item() < 0.005)


# ---------------------------------------------------------------- 5. DHPPOAMP 端到端
def test_dhppoamp_e2e():
    N_ENV, N_STEPS, DIM, STEPS = 16, 24, 61, 3
    DT = 0.02
    ac = ActorCriticDH(
        num_short_obs=20, num_proprio_obs=16, num_critic_obs=40, num_actions=6,
        actor_hidden_dims=[32], critic_hidden_dims=[32], state_estimator_hidden_dims=[16],
        in_channels=66, kernel_size=[6, 4], filter_size=[8, 8], stride_size=[3, 2],
        lh_output_dim=16, init_noise_std=1.0,
    )
    alg = DHPPOAMP(ac, num_learning_epochs=1, num_mini_batches=2,
                   lin_vel_idx=10, learning_rate=3e-4, entropy_coef=0.001,
                   amp_disc_obs_steps=STEPS, amp_disc_hidden_dims=[32, 16],
                   amp_disc_buffer_size=32, amp_task_lerp=0.6,
                   amp_style_reward_scale=1.5, device="cpu")
    alg.configure_amp(disc_obs_dim=DIM, num_envs=N_ENV, dt=DT)
    check("configure_amp 构建判别器/优化器/双缓冲",
          alg.amp_discriminator is not None and alg.disc_optimizer is not None
          and alg.disc_obs_buffer is not None and alg.disc_demo_obs_buffer is not None)
    alg.init_storage(N_ENV, N_STEPS, [66 * 16], [40], [6])

    obs = torch.randn(N_ENV, 66 * 16)   # act() 将整个 obs view 成 (66,16) 进 CNN；short(20) 为其尾段
    critic_obs = torch.randn(N_ENV, 40)

    def rollout(n_steps, with_amp=True, check_fusion=False):
        """同 runner.learn：inference_mode 下采集，amp 张量在块内现算（最严苛的推理张量场景）"""
        o, c = obs, critic_obs
        for i in range(n_steps):
            actions = alg.act(o, c)
            rewards = torch.rand(N_ENV)
            dones = torch.zeros(N_ENV, dtype=torch.bool)
            if with_amp:
                stand = torch.zeros(N_ENV, dtype=torch.bool)
                if check_fusion and i == 0:
                    stand[3] = True
                infos = {"amp": {
                    "disc_obs": torch.randn(N_ENV, STEPS, DIM),
                    "disc_demo_obs": torch.randn(N_ENV, STEPS, DIM) + 3.0,
                    "stand_mask": stand,
                }}
                if check_fusion and i == 0:
                    disc_obs_used = infos["amp"]["disc_obs"]
                    stand_used = stand
                    alg.process_env_step(rewards, dones, infos)
                    stored = alg.storage.rewards[0, :, 0].clone()
                    with torch.no_grad():
                        style, _ = alg.amp_discriminator.predict_style_reward(disc_obs_used, dt=DT)
                    exp_walk = 0.6 * rewards + 0.4 * style
                    check("站立 env 融合=纯 task", torch.allclose(stored[3], rewards[3]))
                    check("行走 env 融合=lerp·task+(1-lerp)·style",
                          torch.allclose(stored[~stand_used], exp_walk[~stand_used], atol=1e-6))
                    o, c = torch.randn_like(o), torch.randn_like(c)
                    continue
            else:
                infos = {}
            alg.process_env_step(rewards, dones, infos)
            o, c = torch.randn_like(o), torch.randn_like(c)

    # 迭代 1：24 步全 amp（首步验证融合数学）→ update
    rollout(N_STEPS, with_amp=True, check_fusion=True)
    check("缓冲步数=rollout 窗", alg.disc_obs_buffer.filled_steps == N_STEPS
          and alg.disc_demo_obs_buffer.filled_steps == N_STEPS)
    alg.compute_returns(critic_obs)
    v, s, es = alg.update()   # inference_mode 外：若缓冲被推理张量污染此处会抛错
    check("update() 返回 3 元组", all(isinstance(x, float) for x in (v, s, es)))
    check("amp_stats 含 5 指标", set(alg.amp_stats.keys()) ==
          {"disc_loss", "disc_grad_penalty", "disc_score", "disc_demo_score", "style_reward"})

    # 迭代 2-9：多轮 rollout+update 让判别器收敛（合成簇 demo=agent+3 线性可分）
    for _ in range(8):
        rollout(N_STEPS)
        alg.compute_returns(critic_obs)
        alg.update()
    check("demo score > agent score（合成簇可分）",
          alg.amp_stats["disc_demo_score"] > alg.amp_stats["disc_score"])

    # 迭代 10：追加超过缓冲容量 → FIFO 封顶；storage 每 24 步一 update 防溢出
    rollout(8)
    check("缓冲 FIFO 封顶（224 步追加 → 32）", alg.disc_obs_buffer.filled_steps == 32)
    pushes = alg.disc_obs_buffer._num_pushes
    check("累计追加计数 = 224", pushes == 24 * 9 + 8)

    # 消融退化：env 不产 extras["amp"] → 纯 task 路径，缓冲不再追加
    rollout(1, with_amp=False)
    check("无 extras[amp] 时缓冲不追加", alg.disc_obs_buffer._num_pushes == pushes)


def main():
    test_normalization()
    test_buffer()
    test_discriminator()
    test_lsgan_convergence()
    test_dhppoamp_e2e()
    failed = [n for n, ok in _RESULTS if not ok]
    print("\n===== {} / {} 项通过 =====".format(
        len(_RESULTS) - len(failed), len(_RESULTS)))
    if failed:
        print("失败项:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
