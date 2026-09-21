#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Step2 env 查表逻辑单测（不依赖 Isaac Gym，mock 最小接口）

验证：
  1. _current_seg_id 指令映射
  2. compute_ref_state 查表：上半身随相位变化、腿部保留正弦、站立回默认
  3. 相位连续性：查表 ref 随 phase 平滑（相邻步差小）
  4. ref_action 公式（相对默认增量）
"""
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

DEVICE = "cpu"
DT = 0.02

# 与 env [DOF] 表一致的 Isaac Gym dof 序（同 prep_mocap_ref.ISAAC_GYM_DOF_ORDER）
DOF_NAMES = [
    "left_hip_pitch_joint", "left_hip_roll_joint", "left_hip_yaw_joint",
    "left_knee_pitch_joint", "left_ankle_pitch_joint", "left_ankle_roll_joint",
    "lumbar_yaw_joint", "lumbar_roll_joint", "lumbar_pitch_joint",
    "left_shoulder_pitch_joint", "left_shoulder_roll_joint", "left_shoulder_yaw_joint",
    "left_elbow_pitch_joint", "left_elbow_yaw_joint", "left_wrist_pitch_joint",
    "left_wrist_roll_joint", "right_shoulder_pitch_joint", "right_shoulder_roll_joint",
    "right_shoulder_yaw_joint", "right_elbow_pitch_joint", "right_elbow_yaw_joint",
    "right_wrist_pitch_joint", "right_wrist_roll_joint",
    "right_hip_pitch_joint", "right_hip_roll_joint", "right_hip_yaw_joint",
    "right_knee_pitch_joint", "right_ankle_pitch_joint", "right_ankle_roll_joint",
]
LEG_NAMES = [
    "left_hip_pitch_joint", "left_hip_roll_joint", "left_hip_yaw_joint",
    "left_knee_pitch_joint", "left_ankle_pitch_joint", "left_ankle_roll_joint",
    "right_hip_pitch_joint", "right_hip_roll_joint", "right_hip_yaw_joint",
    "right_knee_pitch_joint", "right_ankle_pitch_joint", "right_ankle_roll_joint",
]


class MockCfg:
    class commands:
        stand_com_threshold = 0.05
        sw_switch = True
    class rewards:
        cycle_time = 0.7
        use_mocap_ref = True
        mocap_full_body = False
        mocap_ref_file = os.path.join(
            os.path.dirname(__file__), "../../resources/motions/processed/ref_lib.pt")


class MockEnv:
    """复刻 env 的查表逻辑（与 x1_dh_stand_env.py 保持同一实现路径）"""
    def __init__(self, num_envs=8):
        self.cfg = MockCfg()
        self.device = DEVICE
        self.dt = DT
        self.num_envs = num_envs
        self.num_actions = len(DOF_NAMES)
        self.dof_names = DOF_NAMES
        self.dof_pos = torch.zeros(num_envs, self.num_actions, device=DEVICE)
        self.default_dof_pos = torch.zeros(num_envs, self.num_actions, device=DEVICE)
        self.commands = torch.zeros(num_envs, 3, device=DEVICE)
        self.phase_length_buf = torch.arange(num_envs, device=DEVICE, dtype=torch.long) * 3
        self.gait_start = torch.zeros(num_envs, device=DEVICE)

        self.leg_dof_indices = torch.tensor(
            [DOF_NAMES.index(n) for n in LEG_NAMES], dtype=torch.long, device=DEVICE)
        swing = torch.tensor([0.25, 0.05, -0.11, 0.35, -0.16, 0.0,
                              -0.25, -0.05, 0.11, 0.35, 0.16, 0.0], device=DEVICE)
        self.swing_delta_left = swing[:6]
        self.swing_delta_right = swing[6:]

        # 与 env._init_mocap_lib 相同
        path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "../../resources/motions/processed/ref_lib.pt"))
        lib = torch.load(path, map_location=DEVICE)
        assert list(lib["walk_norm"]["dof_names"]) == DOF_NAMES, "dof_names 不匹配"
        self.seg_names = sorted(lib.keys())
        self.upper_dof_indices = torch.tensor(
            [i for i, n in enumerate(DOF_NAMES)
             if "hip" not in n and "knee" not in n and "ankle" not in n],
            dtype=torch.long, device=DEVICE)
        T_max = max(lib[s]["dof_pos"].shape[0] for s in self.seg_names)
        self.mocap_q = torch.zeros(T_max, len(self.seg_names), len(DOF_NAMES), device=DEVICE)
        self.seg_period_frames = torch.zeros(len(self.seg_names), dtype=torch.long, device=DEVICE)
        self.seg_fps = torch.zeros(len(self.seg_names), dtype=torch.float, device=DEVICE)
        self.seg_anchor = torch.zeros(len(self.seg_names), dtype=torch.long, device=DEVICE)
        self.seg_len = torch.zeros(len(self.seg_names), dtype=torch.long, device=DEVICE)
        for k, s in enumerate(self.seg_names):
            q = lib[s]["dof_pos"]
            self.seg_len[k] = q.shape[0]
            # 周期帧数按【库帧率 fps】换算（与 anchor/查表索引同单位）；勿用 policy dt（会 2 倍速）
            self.seg_fps[k] = float(lib[s].get("fps", 50))
            self.seg_period_frames[k] = int(round(lib[s]["gait_period"] * float(lib[s].get("fps", 50))))
            self.seg_anchor[k] = int(lib[s]["phase_anchor_frame"])
            self.mocap_q[:q.shape[0], k] = q
        self.use_mocap_ref = True
        self.mocap_full_body = True   # 与 config 一致（2b 全身）

    def _current_seg_id(self):
        # exp1.6 同步：|wz|>0.15→walk_turn；其余行走→walk_yz（前进全走 yz，slow/norm 出路由）
        wz = self.commands[:, 2]
        turn = self.seg_names.index("walk_turn")
        yz = self.seg_names.index("walk_yz")
        seg_id = torch.full_like(self.phase_length_buf, yz)
        seg_id[torch.abs(wz) > 0.15] = turn
        return seg_id

    def _get_phase(self):
        cycle_time = self.cfg.rewards.cycle_time
        stand_command = (torch.norm(self.commands[:, :3], dim=1) <= self.cfg.commands.stand_com_threshold)
        self.phase_length_buf[stand_command] = 0
        ct = torch.full_like(self.phase_length_buf, cycle_time, dtype=torch.float)
        # 相位周期（秒）= 段周期帧数 / 库帧率（与 env._get_phase 同公式）
        sid = self._current_seg_id()
        ct[~stand_command] = self.seg_period_frames[sid][~stand_command].float() \
            / self.seg_fps[sid][~stand_command]
        return (self.phase_length_buf * self.dt / ct + self.gait_start) * (~stand_command)

    def compute_ref_state(self):
        phase = self._get_phase()
        sin_pos = torch.sin(2 * torch.pi * phase)
        sin_pos_l = sin_pos.clone(); sin_pos_r = sin_pos.clone()
        self.ref_dof_pos = torch.zeros_like(self.dof_pos)
        sin_pos_l[sin_pos_l > 0] = 0
        self.ref_dof_pos[:, self.leg_dof_indices[:6]] = -sin_pos_l.unsqueeze(1) * self.swing_delta_left
        sin_pos_r[sin_pos_r < 0] = 0
        self.ref_dof_pos[:, self.leg_dof_indices[6:]] = sin_pos_r.unsqueeze(1) * self.swing_delta_right
        self.ref_dof_pos[torch.abs(sin_pos) < 0.1] = 0.

        if self.use_mocap_ref:
            stand_command = (torch.norm(self.commands[:, :3], dim=1) <= self.cfg.commands.stand_com_threshold)
            walk = ~stand_command
            if walk.any():
                seg_id = self._current_seg_id()
                frames = phase[walk] * self.seg_period_frames[seg_id[walk]].float() \
                    + self.seg_anchor[seg_id[walk]].float()
                frames = torch.remainder(frames.long(), self.seg_len[seg_id[walk]])
                q_ref = self.mocap_q[frames, seg_id[walk]]
                if self.mocap_full_body:   # 2b：全身查表（与 env 同路径）
                    self.ref_dof_pos[walk] = q_ref
                else:                      # 2a：只覆盖上半身，腿部保留正弦
                    tmp = self.ref_dof_pos[walk]
                    tmp[:, self.upper_dof_indices] = q_ref[:, self.upper_dof_indices]
                    self.ref_dof_pos[walk] = tmp
                self.last_seg_id = seg_id

        self.ref_action = 2 * (self.ref_dof_pos - self.default_dof_pos)
        self.ref_dof_pos += self.default_dof_pos
        return phase


def main():
    env = MockEnv(num_envs=6)
    upper = env.upper_dof_indices
    leg = env.leg_dof_indices
    N = env.num_envs

    print("=== 1. 指令→段映射（exp1.6：前进全走 walk_yz）===")
    env.commands[:, :] = 0
    env.commands[:, 0] = 0.4
    env.phase_length_buf += 1
    seg = env._current_seg_id()
    assert (seg == env.seg_names.index("walk_yz")).all(), "vx=0.4 应→walk_yz（exp1.6 前进全指 yz）"
    env.commands[:, 0] = 0.1
    seg = env._current_seg_id()
    assert (seg == env.seg_names.index("walk_yz")).all(), "vx=0.1 应→walk_yz（exp1.6 不再分 slow 桶）"
    env.commands[:, 0] = 0.4; env.commands[:, 2] = 0.3
    seg = env._current_seg_id()
    assert (seg == env.seg_names.index("walk_turn")).all(), "wz=0.3 应→walk_turn"
    print("  [OK] yz/turn 分档正确")

    print("=== 2. 行走查表（2b 全身）：ref 全列 = mocap 帧（腿臂同源同拍）===")
    env.commands[:, :] = 0
    env.commands[:, 0] = 0.4
    env.phase_length_buf = torch.arange(N, device=DEVICE, dtype=torch.long) * 5 + 1
    phase = env.compute_ref_state()
    seg_id = env.last_seg_id
    # 与 env 同序复算帧号：先 phase*P 再截断（先 .long() 会差帧）
    walk_frames = torch.remainder(
        (phase * env.seg_period_frames[seg_id].float() + env.seg_anchor[seg_id].float()).long(),
        env.seg_len[seg_id])
    q_expect = env.mocap_q[walk_frames, seg_id]   # default=0，2b 覆盖后 ref 应逐列等于查表帧
    assert torch.allclose(env.ref_dof_pos, q_expect, atol=1e-5), \
        "2b 全身 ref 应与 mocap 查表帧逐列一致（腿臂同源）"
    var = env.ref_dof_pos.std(dim=0)
    # exp1.6: walk_yz 手部 4 关节全常数——wrist_roll×2 为填充（无传感器），wrist_pitch×2
    # 源数据本身全 0（yz 手腕未动）。排除后其余 25 列应有动态，常数列应严格恒定
    wr = [env.dof_names.index(n) for n in
          ("left_wrist_pitch_joint", "left_wrist_roll_joint",
           "right_wrist_pitch_joint", "right_wrist_roll_joint")]
    mask = torch.ones_like(var, dtype=torch.bool); mask[wr] = False
    var_dyn = var[mask]
    assert var_dyn.min() > 1e-4, f"非 wrist 列应有动态，min std={var_dyn.min():.2e}"
    if seg_id[0].item() == env.seg_names.index("walk_yz"):
        assert all(var[i].item() == 0 for i in wr), "yz 段 wrist×4 应恒为常数（源数据特性）"
        print(f"  [OK] 29 列与查表帧一致，非 wrist std∈[{var_dyn.min():.3f},{var_dyn.max():.3f}]"
              f"（wrist×4 常数 [源数据特性]）")
    else:
        print(f"  [OK] 全身 29 列与查表帧一致，std∈[{var.min():.3f},{var.max():.3f}]")

    print("=== 3. 站立回默认 ===")
    env.commands[:, :] = 0  # 站立
    env.compute_ref_state()
    assert torch.allclose(env.ref_dof_pos, env.default_dof_pos), "站立应回默认位姿"
    assert torch.allclose(env.ref_action, torch.zeros_like(env.ref_action)), "站立 ref_action=0"
    print("  [OK] 站立 ref=default，ref_action=0")

    print("=== 4. 相位连续性（同段相邻步查表 = 数据原生帧差）===")
    env.commands[:, :] = 0; env.commands[:, 0] = 0.4
    env.phase_length_buf = torch.zeros(N, dtype=torch.long, device=DEVICE)
    diffs = []
    prev = None
    for _ in range(20):
        env.phase_length_buf += 1
        env.compute_ref_state()
        cur = env.ref_dof_pos[:, upper].clone()
        if prev is not None:
            diffs.append((cur - prev).abs().max().item())
        prev = cur
    dmax = max(diffs)
    # 判据：跳变不超过数据源原生相邻帧差的 p99.9（exp1.6 路由后行走查 walk_yz 段）
    q = env.mocap_q[:, env.seg_names.index("walk_yz"), :].numpy()
    dq = np.abs(np.diff(q[:, env.upper_dof_indices.numpy()], axis=0))
    native_p999 = float(np.percentile(dq, 99.9))
    assert dmax <= max(0.05, native_p999), f"跳变 {dmax:.4f} 超数据原生 p99.9 {native_p999:.4f}"
    print(f"  [OK] 20 步相邻最大跳变 {dmax:.4f} rad ≤ 数据原生 p99.9 {native_p999:.4f}"
          f"（GMR 源右肘 yaw 毛刺属数据特性）")

    print("=== 5. ref_action 公式（相对默认增量）===")
    env.commands[:, :] = 0; env.commands[:, 0] = 0.4
    env.default_dof_pos[:, upper] = 0.1  # 人为设非零 default
    env.compute_ref_state()
    # ref_action = 2*(ref_before_add_default - default) = 2*(ref_after - 2*default)
    lhs = env.ref_action[:, upper]
    rhs = 2 * (env.ref_dof_pos[:, upper] - 2 * env.default_dof_pos[:, upper])
    assert torch.allclose(lhs, rhs, atol=1e-5), "ref_action 公式不符"
    print("  [OK] ref_action = 2*(ref - default) 验证通过")

    print("=== 6. 周期语义：相位周期=步频（查表帧随相位与 −sin 同相，防 2 倍速回归）===")
    for k, s in enumerate(env.seg_names):
        P, A, T = int(env.seg_period_frames[k]), int(env.seg_anchor[k]), int(env.seg_len[k])
        fps = float(env.seg_fps[k])
        # 帧数-秒换算自洽：P/fps 应回到检测周期 gait_period（±1 帧舍入）
        gp = torch.load(os.path.abspath(os.path.join(
            os.path.dirname(__file__), "../../resources/motions/processed/ref_lib.pt")),
            map_location=DEVICE)[s]["gait_period"]
        assert abs(P / fps - gp) <= 1.0 / fps + 1e-6, f"{s}: P/fps={P/fps:.3f}s vs T_gait={gp:.3f}s"
        # 端到端同相验收（env 侧复刻 prep ④b）：一个相位单位扫过的查表帧，
        # 其左髋 pitch 应与 −sin(2πφ) 正相关；若周期错 2 倍相关会跌到 ≈0
        frames = (torch.arange(P, device=DEVICE) + A) % T
        hip = env.mocap_q[frames, k, env.dof_names.index("left_hip_pitch_joint")].numpy()
        hip = hip - hip.mean()
        ref = -np.sin(2 * np.pi * np.arange(P) / P)
        c = float(np.dot(hip, ref) / (np.linalg.norm(hip) * np.linalg.norm(ref) + 1e-12))
        assert c > 0.5, f"{s}: 查表左髋与 −sin 相关 {c:.2f} 过低（周期/锚点错位）"
        print(f"  [OK] {s}: P={P}帧@{fps:.0f}Hz={P/fps:.3f}s, corr(查表左髋,−sin)={c:.2f}")

    print("\n全部单测通过 ✓")


if __name__ == "__main__":
    main()
