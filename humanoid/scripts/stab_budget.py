#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""exp1.13 Step 1：训练域多 env 稳定性诊断 → "稳定性预算表"（exp1.md §13.4）

训练域原样（plane + 全套 domain_rand + noise + gait 调度 + 推力），**不做任何 override**。
区别 play.py：play 钉命令/手工标定动力学，本脚本要的就是训练分布。

指标口径（与 §13.1 保持可比）：
- 接触判据：foot_contact_force_z > 5N（同 env 的 _reward_feet_contact_number 与 play.py 导出的 foot_force_*）
- 行走段：command_x > 0.05（同 §13.1）
- 双支撑/单支撑/腾空：行走段内 双脚接触 / 恰一脚接触 / 双脚均无接触
- 腾空事件：连续腾空 ≥5 个控制步（= ≥50ms @100Hz）
- 终止原因互斥优先级：base 接触力 > |roll|>0.8 > |pitch|>0.8 > h<0.45 > timeout

用法：
  PATH=<F1>/bin:$PATH PYTHONPATH=<repo>:<isaacgym>/python DISPLAY=:1 \
    XAUTHORITY=/run/user/1000/gdm/Xauthority <F1>/bin/python humanoid/scripts/stab_budget.py
环境变量：SB_ENVS(512) SB_EPS(3) SB_OUT(czy/data/exp1.13) SB_CKPT(exp1.12/model_37997.pt)
"""
import os
import sys
import csv
import time

from humanoid.envs import task_registry
from humanoid.utils import get_args
import numpy as np
import torch

LEGGED_GYM_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NUM_ENVS = int(os.environ.get("SB_ENVS", 512))
N_EP = int(os.environ.get("SB_EPS", 3))
SEED = 123145
OUT_DIR = os.environ.get("SB_OUT", os.path.join(LEGGED_GYM_ROOT_DIR, "czy", "data", "exp1.13"))
CKPT = os.environ.get("SB_CKPT", os.path.join(LEGGED_GYM_ROOT_DIR, "czy", "data", "exp1.12", "model_37997.pt"))
WIN = 50          # 终止前窗：50 控制步 = 0.5s @100Hz
HIST = 200        # 判别 pass 的多尺度缓冲：200 控制步 = 2.0s
HEAD_W = 100      # exp2.0：行走片段"头部窗" = 首 1.0s（用于"段首水平"与"段内斜率"）
HEAD_MIN = 30     # 头部窗最小样本数（0.3s）——不足则不计斜率，避免短片段噪声
PITCH_SIGN_NOTE = "正=前倾，负=后仰"   # pitch = asin(2(qw·qy − qz·qx))，绕 +y 轴转角
FLIGHT_MIN = 5    # 腾空事件门限：5 控制步 = 50ms
WALK_CMD_X = 0.05  # 行走段判据（同 §13.1）

# 终止原因编码
R_BASE, R_ROLL, R_PITCH, R_H, R_TIMEOUT = 0, 1, 2, 3, 4
REASON_NAME = {R_BASE: "base_contact", R_ROLL: "roll>0.8", R_PITCH: "pitch>0.8",
               R_H: "h<0.45", R_TIMEOUT: "timeout"}


def build_env():
    args = get_args()
    args.task = os.environ.get("SB_TASK", "x1_dh_stand")
    args.headless = True
    args.sim_device = "cuda:0"
    args.num_envs = NUM_ENVS
    env_cfg, train_cfg = task_registry.get_cfgs(name=args.task)
    env_cfg.env.num_envs = NUM_ENVS
    env_cfg.seed = SEED
    print(f"[sb] mesh_type={env_cfg.terrain.mesh_type} curriculum={env_cfg.terrain.curriculum} "
          f"episode_length_s={env_cfg.env.episode_length_s} num_envs={env_cfg.env.num_envs}")
    env, env_cfg = task_registry.make_env(name=args.task, args=args, env_cfg=env_cfg)
    train_cfg.runner.resume = False
    ppo_runner, train_cfg, _ = task_registry.make_alg_runner(
        env=env, name=args.task, args=args, train_cfg=train_cfg, log_root=None)
    print(f"[sb] loading checkpoint: {CKPT}")
    ppo_runner.load(CKPT, load_optimizer=False)
    policy = ppo_runner.get_inference_policy(device=env.device)
    print(f"[sb] env ready: num_envs={env.num_envs} max_episode_length={env.max_episode_length} "
          f"dt={env.dt} feet={env.feet_indices.tolist()}")
    return env, policy


def main():
    env, policy = build_env()
    dev = env.device
    N = env.num_envs
    zero = lambda: torch.zeros(N, device=dev)

    st = {
        "n_walk": zero(), "n_ds": zero(), "n_ss": zero(), "n_fl": zero(),
        "h_min": torch.full((N,), 1e9, device=dev),
        "er_max": zero(), "ep_max": zero(), "wz_max": zero(),
        "fl_run": zero(), "fl_ev": zero(), "fl_max": zero(),
        "vx_sum": zero(), "cmd_sum": zero(), "vy2_sum": zero(),
        "yaw_prev": zero(), "yaw_drift": zero(),
        # 曝光量（行走样本计数）——用于把"终止条件切片"从"终止时刻取值"升级为"条件终止率"，
        # 否则会被"timeout 恒在结尾 stand 段结束（cmd≈0）"这个选择效应污染
        "wz_gt05": zero(), "wz_gt15": zero(), "wz_gt30": zero(),
        "vy_gt05": zero(), "vy_gt15": zero(), "vx_gt08": zero(),
        # ---- exp2.0 修改四：躯干俯仰（带符号）----
        # 背景：历轮预算表只存 |pitch|max（pitch_max），符号与段内漂移全丢，
        # 导致"持续后仰"这一最强失稳信号长期不可见（详见 czy/exp1/exp2.md §1）。
        "pitch_sum": zero(),                              # Σpitch（行走样本）→ 行走段水平
        "pitch_hd_sum": zero(), "pitch_hd_n": zero(),      # 片段头 1.0s 累加 → 段首（起步）水平
        "ws_sum": zero(), "ws_tp": zero(), "ws_n": zero(),  # 当前行走片段 Σp / Σt·p / n（整段斜率）
        "slope_sum": zero(), "slope_cnt": zero(),          # 已结算片段斜率累加 → 段内斜率(rad/s)
        "seg_first": zero(), "seg_last": zero(),           # 片段首 / 末时刻 pitch
        "span_sum": zero(), "span_cnt": zero(),            # 片段首末 pitch 差累加 → 段内跨度
        "w_age": zero(),                                   # 行走片段年龄（步）
    }
    fl_hist = torch.zeros(N, WIN, device=dev)
    ds_hist = torch.zeros(N, WIN, device=dev)
    wk_hist = torch.zeros(N, WIN, device=dev)   # 窗内行走掩码（末窗只按行走样本归一）
    h_hist = torch.zeros(N, 25, device=dev)     # 高度回溯 0.25s（区分"蹲下"与"塌陷"）
    # ---- 判别 pass（§13.4c）：多时间尺度滚动缓冲 B[:, :, k] + 腾空事件性质 ----
    # k: 0=walk 1=flight 2=ds 3=|roll| 4=|roll_rate| 5=|pitch| 6=h 7=τ饱和(任一) 8=τ饱和(腿)
    #    9=pitch(带符号)  ← exp2.0 修改四：躯干俯仰方向（0.0 语义：正=前倾、负=后仰）
    KB = 10
    B = torch.zeros(N, HIST, KB, device=dev)
    prev_contact = torch.zeros(N, 2, dtype=torch.bool, device=dev)
    prev_none = torch.zeros(N, dtype=torch.bool, device=dev)
    walk_prev = torch.zeros(N, dtype=torch.bool, device=dev)   # 上一步是否在行走（取片段下降沿）
    for k in ("fo_n", "fo_h_sum", "fo_h_min", "fo_h_lt052", "fo_roll_sum", "fo_roll_max",
              "fo_absin_sum", "fo_lost_support", "fo_prev_both",
              "fo_last_h", "fo_last_roll", "fo_last_absin",
              "fl_ev_100", "fl_ev_150", "sat_any_sum", "sat_leg_sum"):
        st[k] = zero()
    st["fo_h_min"] = torch.full((N,), 1e9, device=dev)
    tq_lim = env.torque_limits.unsqueeze(0)                       # (1, num_dof)
    leg_idx = env.leg_dof_indices
    ep_count = zero()          # 已完成 episode 数
    records = []

    orig_check = env.check_termination

    def stat_reset(ids):
        for k, v in st.items():
            if k in ("h_min", "fo_h_min"):
                st[k][ids] = 1e9
            else:
                st[k][ids] = 0.
        fl_hist[ids] = 0.
        ds_hist[ids] = 0.
        wk_hist[ids] = 0.
        h_hist[ids] = 0.
        B[ids] = 0.
        walk_prev[ids] = False

    def wrapped_check():
        nonlocal prev_contact, prev_none, walk_prev   # 跨步保持"上一控制步的接触态 / 行走标志"
        # ---- 本步量（复位前的终止态）----
        contact = env.contact_forces[:, env.feet_indices, 2] > 5.          # (N,2)
        both = contact.all(dim=1)
        none = ~contact.any(dim=1)
        single = ~both & ~none
        walk = env.commands[:, 0] > WALK_CMD_X
        yaw = env.base_euler_xyz[:, 2]
        h = env.root_states[:, 2]
        # 相位（判别 pass 需要，提前算；断言幂等，_get_phase 纯读）
        phase = env._get_phase()
        sin_pos = torch.sin(2 * torch.pi * phase)
        # 力矩饱和（同 play.py clip_count 判据：|τ| ≥ limit-1e-6）
        sat = env.torques.abs() >= (tq_lim - 1e-6)
        sat_any = sat.any(dim=1)
        sat_leg = sat[:, leg_idx].any(dim=1)

        # 刚复位的 env：清空累积量、对齐 yaw 基准
        fresh = env.episode_length_buf <= 1
        if fresh.any():
            fid = fresh.nonzero(as_tuple=False).flatten()
            stat_reset(fid)
            st["yaw_prev"][fid] = yaw[fid]

        # 滚动窗（行走样本 + 行走掩码 + 高度）
        fl_hist[:, :-1] = fl_hist[:, 1:].clone()
        fl_hist[:, -1] = (none & walk).float()
        ds_hist[:, :-1] = ds_hist[:, 1:].clone()
        ds_hist[:, -1] = (both & walk).float()
        wk_hist[:, :-1] = wk_hist[:, 1:].clone()
        wk_hist[:, -1] = walk.float()
        h_hist[:, :-1] = h_hist[:, 1:].clone()
        h_hist[:, -1] = h

        # ---- 判别 pass：多尺度缓冲 B ----
        B[:, :-1, :] = B[:, 1:, :].clone()
        B[:, -1, 0] = walk.float()
        B[:, -1, 1] = (none & walk).float()
        B[:, -1, 2] = (both & walk).float()
        B[:, -1, 3] = env.base_euler_xyz[:, 0].abs()
        B[:, -1, 4] = env.base_ang_vel[:, 0].abs()      # 体轴 roll 角速度
        B[:, -1, 5] = env.base_euler_xyz[:, 1].abs()
        B[:, -1, 9] = env.base_euler_xyz[:, 1] * walk.float()  # exp2.0：带符号 pitch（正=前倾，负=后仰）
        B[:, -1, 6] = h
        B[:, -1, 7] = sat_any.float()
        B[:, -1, 8] = sat_leg.float()

        # ---- 判别 pass：腾空"发生时刻"的性质（区分真 bound vs 塌陷卸载）----
        onset = walk & none & (~prev_none)
        if onset.any():
            o = onset.float()
            aroll = env.base_euler_xyz[:, 0].abs()
            absin = sin_pos.abs()
            st["fo_n"] += o
            st["fo_h_sum"] += h * o
            st["fo_h_min"] = torch.where(onset, torch.minimum(st["fo_h_min"], h), st["fo_h_min"])
            st["fo_h_lt052"] += (onset & (h < 0.52)).float()
            st["fo_roll_sum"] += aroll * o
            st["fo_roll_max"] = torch.where(onset, torch.maximum(st["fo_roll_max"], aroll), st["fo_roll_max"])
            st["fo_absin_sum"] += absin * o
            # 支撑丢失：上一控制步只有一只脚在接触、且那只脚是钟上的"摆动"脚
            # （= 钟指定该支撑的那只脚先离地）→ 先失去支撑；反之 = 正常离地（摆动脚先抬）
            pL = prev_contact[:, 0] & ~prev_contact[:, 1]
            pR = ~prev_contact[:, 0] & prev_contact[:, 1]
            clock_right = sin_pos < 0
            st["fo_lost_support"] += (onset & ((pL & clock_right) | (pR & ~clock_right))).float()
            st["fo_prev_both"] += (onset & prev_contact.all(dim=1)).float()
            st["fo_last_h"] = torch.where(onset, h, st["fo_last_h"])
            st["fo_last_roll"] = torch.where(onset, aroll, st["fo_last_roll"])
            st["fo_last_absin"] = torch.where(onset, absin, st["fo_last_absin"])
        prev_contact = contact.clone()
        prev_none = none.clone()

        wf = walk.float()
        st["n_walk"] += wf
        st["n_ds"] += (both & walk).float()
        st["n_ss"] += (single & walk).float()
        st["n_fl"] += (none & walk).float()
        # 曝光量（行走样本，按指令条件分桶）
        awz = env.commands[:, 2].abs()
        avy = env.commands[:, 1].abs()
        st["wz_gt05"] += (walk & (awz > 0.05)).float()
        st["wz_gt15"] += (walk & (awz > 0.15)).float()
        st["wz_gt30"] += (walk & (awz > 0.30)).float()
        st["vy_gt05"] += (walk & (avy > 0.05)).float()
        st["vy_gt15"] += (walk & (avy > 0.15)).float()
        st["vx_gt08"] += (walk & (env.commands[:, 0] > 0.8)).float()

        # ---- exp2.0 修改四：躯干俯仰（带符号）累积 ----
        # 三个量：
        #   ① 行走段水平 pitch_sum/n_walk      —— 全程均值（含累积效应）
        #   ② 段首水平  pitch_hd_sum/pitch_hd_n —— 各行走片段首 1.0s（= "起步姿态"）
        #   ③ 段内斜率  slope_sum/slope_cnt     —— 各**完整行走片段**整体最小二乘斜率
        # 关键：必须**按行走片段各自拟合**，不能跨片段整段拟合一个斜率
        #（exp2.md §1 证据 7：同代两个速度段斜率符号可相反，跨片段拟合会被污染）。
        # 片段内掩码恒真（实测每 episode 约 1 个片段，slope_n≈1）→ t = 0..n−1，
        # Σt 与 Σt² 有解析式，只需额外累计 Σt·p。
        pitch = env.base_euler_xyz[:, 1]
        st["pitch_sum"] += pitch * wf
        w_age_new = torch.where(walk, st["w_age"] + 1., torch.zeros_like(st["w_age"]))
        t_idx = (w_age_new - 1.).clamp(min=0.)
        hf = (walk & (w_age_new <= HEAD_W)).float()
        st["pitch_hd_sum"] += pitch * hf
        st["pitch_hd_n"] += hf
        st["ws_sum"] += pitch * wf
        st["ws_tp"] += pitch * wf * t_idx
        st["ws_n"] += wf
        # 片段首末 pitch（跨度 = 末 − 首，直接量化"越走越后仰"的总量，不受非单调影响）
        st["seg_first"] = torch.where(walk & ~walk_prev, pitch, st["seg_first"])
        st["seg_last"] = torch.where(walk, pitch, st["seg_last"])
        # 片段结束（行走掩码下降沿）→ 结算该片段整体斜率（单位 rad/步 → 转 rad/s）
        seg_end = walk_prev & ~walk & (st["ws_n"] >= HEAD_MIN)
        if seg_end.any():
            n = st["ws_n"][seg_end]
            sp = st["ws_sum"][seg_end]
            stp = st["ws_tp"][seg_end]
            sum_t = n * (n - 1.) / 2.
            sum_tt = n * (n - 1.) * (2. * n - 1.) / 6.
            den = n * sum_tt - sum_t ** 2
            slope = torch.where(den > 1e-6, (n * stp - sum_t * sp) / den.clamp(min=1e-6),
                                torch.zeros_like(den)) / env.dt      # rad/步 → rad/s
            st["slope_sum"][seg_end] += slope
            st["slope_cnt"][seg_end] += 1.
            st["span_sum"][seg_end] += st["seg_last"][seg_end] - st["seg_first"][seg_end]
            st["span_cnt"][seg_end] += 1.
        # 片段结束（含样本不足未计斜率者）→ 清空整段累加器
        clear_ws = (seg_end | (~walk & (st["ws_n"] > 0))).nonzero(as_tuple=False).flatten()
        if len(clear_ws) > 0:
            st["ws_sum"][clear_ws] = 0.
            st["ws_tp"][clear_ws] = 0.
            st["ws_n"][clear_ws] = 0.
        st["w_age"] = w_age_new
        walk_prev = walk.clone()
        # 腾空事件（连续段；50/100/150ms 三档桶）
        run = torch.where(none & walk, st["fl_run"] + 1., torch.zeros_like(st["fl_run"]))
        closed = ~(none & walk)
        st["fl_ev"] += ((st["fl_run"] >= FLIGHT_MIN) & closed).float()
        st["fl_ev_100"] += ((st["fl_run"] >= 10) & closed).float()
        st["fl_ev_150"] += ((st["fl_run"] >= 15) & closed).float()
        st["fl_max"] = torch.maximum(st["fl_max"], run)
        st["fl_run"] = run
        # 余量
        st["h_min"] = torch.minimum(st["h_min"], env.root_states[:, 2])
        st["er_max"] = torch.maximum(st["er_max"], env.base_euler_xyz[:, 0].abs())
        st["ep_max"] = torch.maximum(st["ep_max"], env.base_euler_xyz[:, 1].abs())
        st["wz_max"] = torch.maximum(st["wz_max"], env.base_ang_vel[:, 2].abs())
        # 速度 / 侧移 / 航向漂移（行走样本）
        st["vx_sum"] += env.base_lin_vel[:, 0] * wf
        st["cmd_sum"] += env.commands[:, 0] * wf
        st["vy2_sum"] += env.base_lin_vel[:, 1] ** 2 * wf
        dyaw = yaw - st["yaw_prev"]
        dyaw = (dyaw + np.pi) % (2 * np.pi) - np.pi
        st["yaw_drift"] += torch.where(walk, dyaw, torch.zeros_like(dyaw))
        st["yaw_prev"] = yaw.clone()

        # ---- 四项终止判据（同一终止态并行求值，之后按优先级取原因）----
        c_base = torch.any(torch.norm(
            env.contact_forces[:, env.termination_contact_indices, :], dim=-1) > 1., dim=1)
        cut = env.cfg.termination.roll_pitch_cutoff
        c_roll = env.base_euler_xyz[:, 0].abs() > cut
        c_pitch = env.base_euler_xyz[:, 1].abs() > cut
        c_h = env.root_states[:, 2] < env.cfg.termination.base_height_cutoff

        # 分段 / 段序（终止时刻；phase/sin_pos 已在上面算过）
        seg_id = env._current_seg_id()
        stage = (env.episode_length_buf.unsqueeze(1) > env.gait_time).sum(dim=1)

        orig_check()   # 设置 env.reset_buf / env.time_out_buf
        done = env.reset_buf.clone()

        ids = done.nonzero(as_tuple=False).flatten()
        if len(ids) > 0:
            w_wk = wk_hist[ids].sum(dim=1)                       # 末窗内行走样本数
            w_ds = ds_hist[ids].sum(dim=1) / w_wk.clamp(min=1.)
            w_fl = fl_hist[ids].sum(dim=1) / w_wk.clamp(min=1.)
            dh_025 = h_hist[ids][:, -1] - h_hist[ids][:, 0]      # 0.25s 内高度变化（区分蹲下 vs 塌陷）
            # ---- 判别 pass：多时间尺度窗口（各量在行走样本上归一）----
            sub = B[ids]                                          # (M,HIST,KB)
            HZ = ((HIST, "2000ms"), (100, "1000ms"), (WIN, "500ms"), (10, "100ms"))
            hz = {}
            for W, tagname in HZ:
                cw = sub[:, -W:, 0].sum(dim=1)
                cn = cw.clamp(min=1.)
                hz[tagname] = {
                    "n": cw,
                    "fl": sub[:, -W:, 1].sum(dim=1) / cn,
                    "ds": sub[:, -W:, 2].sum(dim=1) / cn,
                    "aroll": sub[:, -W:, 3].sum(dim=1) / cn,
                    "adroll": sub[:, -W:, 4].sum(dim=1) / cn,
                    "apitch": sub[:, -W:, 5].sum(dim=1) / cn,
                    "h": sub[:, -W:, 6].sum(dim=1) / cn,
                    "sat": sub[:, -W:, 7].sum(dim=1) / cn,
                    "satleg": sub[:, -W:, 8].sum(dim=1) / cn,
                    "pitch_signed": sub[:, -W:, 9].sum(dim=1) / cn,   # exp2.0：窗口内带符号 pitch 均值
                }
            for k, eid in enumerate(ids.tolist()):
                t = ids[k]
                if bool(c_base[t]):
                    reason = R_BASE
                elif bool(c_roll[t]):
                    reason = R_ROLL
                elif bool(c_pitch[t]):
                    reason = R_PITCH
                elif bool(c_h[t]):
                    reason = R_H
                elif bool(env.time_out_buf[t]):
                    reason = R_TIMEOUT
                else:
                    reason = R_TIMEOUT
                nw = float(st["n_walk"][t])
                fo_n = float(st["fo_n"][t])
                rec = dict(
                    env_id=eid,
                    ep=int(ep_count[eid].item()) + 1,
                    reason=REASON_NAME[reason], reason_id=reason,
                    ep_len=int(env.episode_length_buf[t].item()),
                    terminated=reason != R_TIMEOUT,
                    n_walk=int(nw),
                    walk_time_s=round(nw * env.dt, 2),
                    ds_pct=round(100 * float(st["n_ds"][t]) / nw, 2) if nw else np.nan,
                    ss_pct=round(100 * float(st["n_ss"][t]) / nw, 2) if nw else np.nan,
                    fl_pct=round(100 * float(st["n_fl"][t]) / nw, 2) if nw else np.nan,
                    fl_ev_50ms=int(st["fl_ev"][t].item()),
                    fl_ev_100ms=int(st["fl_ev_100"][t].item()),
                    fl_ev_150ms=int(st["fl_ev_150"][t].item()),
                    fl_max_ms=int(st["fl_max"][t].item()) * 10,
                    fl_pct_last0p5s=round(100 * float(w_fl[k]), 2),
                    ds_pct_last0p5s=round(100 * float(w_ds[k]), 2),
                    n_walk_last0p5s=int(w_wk[k].item()),
                    # ---- 判别 pass：腾空"发生时刻"的性质 ----
                    fo_n=int(fo_n),
                    fo_h_mean=round(float(st["fo_h_sum"][t]) / fo_n, 4) if fo_n else np.nan,
                    fo_h_min=round(float(st["fo_h_min"][t]), 4) if fo_n else np.nan,
                    fo_h_lt052_pct=round(100 * float(st["fo_h_lt052"][t]) / fo_n, 1) if fo_n else np.nan,
                    fo_roll_mean=round(float(st["fo_roll_sum"][t]) / fo_n, 4) if fo_n else np.nan,
                    fo_roll_max=round(float(st["fo_roll_max"][t]), 4),
                    fo_absin_mean=round(float(st["fo_absin_sum"][t]) / fo_n, 4) if fo_n else np.nan,
                    fo_lost_support_pct=round(100 * float(st["fo_lost_support"][t]) / fo_n, 1) if fo_n else np.nan,
                    fo_prev_both_pct=round(100 * float(st["fo_prev_both"][t]) / fo_n, 1) if fo_n else np.nan,
                    fo_last_h=round(float(st["fo_last_h"][t]), 4) if fo_n else np.nan,
                    fo_last_roll=round(float(st["fo_last_roll"][t]), 4) if fo_n else np.nan,
                    fo_last_absin=round(float(st["fo_last_absin"][t]), 4) if fo_n else np.nan,
                    # 曝光量（行走样本计数）→ 条件终止率的分母
                    wz_gt05=int(st["wz_gt05"][t].item()), wz_gt15=int(st["wz_gt15"][t].item()),
                    wz_gt30=int(st["wz_gt30"][t].item()),
                    vy_gt05=int(st["vy_gt05"][t].item()), vy_gt15=int(st["vy_gt15"][t].item()),
                    vx_gt08=int(st["vx_gt08"][t].item()),
                    h_min=round(float(st["h_min"][t]), 4),
                    roll_max=round(float(st["er_max"][t]), 4),
                    pitch_max=round(float(st["ep_max"][t]), 4),
                    # ---- exp2.0 修改四：躯干俯仰（正=前倾，负=后仰；历轮只有 pitch_max 绝对值）----
                    walk_pitch_mean=round(float(st["pitch_sum"][t]) / nw, 4) if nw else np.nan,
                    walk_pitch_start=round(float(st["pitch_hd_sum"][t]) / float(st["pitch_hd_n"][t]), 4)
                    if float(st["pitch_hd_n"][t]) > 0 else np.nan,
                    walk_pitch_slope=round(float(st["slope_sum"][t]) / float(st["slope_cnt"][t]), 5)
                    if float(st["slope_cnt"][t]) > 0 else np.nan,
                    walk_pitch_span=round(float(st["span_sum"][t]) / float(st["span_cnt"][t]), 4)
                    if float(st["span_cnt"][t]) > 0 else np.nan,
                    walk_pitch_slope_n=int(st["slope_cnt"][t].item()),
                    wz_max=round(float(st["wz_max"][t]), 4),
                    vx_mean=round(float(st["vx_sum"][t]) / nw, 3) if nw else np.nan,
                    cmd_x_mean=round(float(st["cmd_sum"][t]) / nw, 3) if nw else np.nan,
                    speed_ratio=round(float(st["vx_sum"][t]) / float(st["cmd_sum"][t]), 3)
                    if float(st["cmd_sum"][t]) > 1e-3 else np.nan,
                    vy_rms=round(float((st["vy2_sum"][t] / max(nw, 1)) ** 0.5), 4),
                    yaw_drift=round(float(st["yaw_drift"][t]) / (nw * env.dt), 4) if nw else np.nan,
                    # 终止时刻状态
                    vx_end=round(float(env.base_lin_vel[t, 0]), 3),
                    vy_end=round(float(env.base_lin_vel[t, 1]), 3),
                    vz_end=round(float(env.base_lin_vel[t, 2]), 3),
                    dh_025s=round(float(dh_025[k]), 4),
                    wz_end=round(float(env.base_ang_vel[t, 2]), 3),
                    cmd_x_end=round(float(env.commands[t, 0]), 3),
                    cmd_y_end=round(float(env.commands[t, 1]), 3),
                    cmd_wz_end=round(float(env.commands[t, 2]), 3),
                    roll_end=round(float(env.base_euler_xyz[t, 0]), 3),
                    pitch_end=round(float(env.base_euler_xyz[t, 1]), 3),
                    h_end=round(float(env.root_states[t, 2]), 3),
                    sin_end=round(float(sin_pos[t]), 3),
                    seg_id=int(seg_id[t].item()),
                    gait_stage=int(stage[t].item()),
                )
                # 多尺度窗口列（fl/ds/sat/satleg 记 %，其余记原值）
                _pct = {"fl", "ds", "sat", "satleg"}
                for tagname in hz:
                    rec[f"n_{tagname}"] = int(hz[tagname]["n"][k].item())
                    for key in ("fl", "ds", "aroll", "adroll", "apitch", "pitch_signed",
                                "h", "sat", "satleg"):
                        v = float(hz[tagname][key][k])
                        rec[f"{key}_{tagname}"] = round(100 * v, 2) if key in _pct else round(v, 4)
                records.append(rec)
            ep_count[ids] += 1
            stat_reset(ids)

    env.check_termination = wrapped_check

    # ---------------- 主循环 ----------------
    max_steps = int(N_EP * (env.max_episode_length + 2) + 100)
    env.reset()
    obs = env.get_observations()
    t0 = time.time()
    step = 0
    while step < max_steps and int(ep_count.min().item()) < N_EP:
        with torch.no_grad():
            actions = policy(obs.detach())
        obs, _, _, _, _ = env.step(actions.detach())
        step += 1
        if step % 250 == 0:
            el = time.time() - t0
            print(f"[sb] step {step}/{max_steps} ({el:.0f}s, {step/el:.1f} step/s) "
                  f"episodes={len(records)} min_ep_done={int(ep_count.min().item())}", flush=True)
    print(f"[sb] 采集完成：{step} 步 / {time.time()-t0:.0f}s / {len(records)} episodes")

    # ---------------- 落盘 + 汇总 ----------------
    os.makedirs(OUT_DIR, exist_ok=True)
    csv_path = os.path.join(OUT_DIR, "stab_budget.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0].keys()))
        w.writeheader()
        w.writerows(records)
    print(f"[sb] CSV -> {csv_path}")

    # 汇总需 pandas，而 isaacgym 环境（py38 F1）无 pandas → 拆到 stab_budget_report.py
    print(f"[sb] 汇总请用带 pandas 的解释器（如 /home/robot/Anaconda/bin/python）：\n"
          f"     /home/robot/Anaconda/bin/python humanoid/scripts/stab_budget_report.py --csv {csv_path}")
    return


if __name__ == "__main__":
    main()
