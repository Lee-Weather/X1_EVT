#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Phase 2 Step1 预处理：x1_gmr pkl → Isaac Gym 序参考库 ref_lib.pt

流程（对应 czy/plan/plan.md Step1）：
  ① 重排   gmr dof_names → Isaac Gym 序（从 MJCF hinge 序读取，与 env [DOF] 表一致）
  ② 翻转   FLIP_JOINTS 6 关节取反（右肩 p/r/y + 右肘 p/y + 右踝 pitch，数值搜索实证 0.3mm）
  ③ FK校验 重排+翻转后与 gmr body_positions 对拍（首/中/尾帧，<5mm 通过）
  ④ 周期   左髋 pitch 自相关求 T_gait；锚点 = mocap 左髋 vs -sin(2πt/T) 互相关最大相位
           （与 env stance_mask 语义对齐：sin>=0 左支撑、左摆动在 sin<0 半周期）
  ⑤ 切段   方案 A：walk_norm←0000 / walk_turn←0026 / walk_slow←0002，中间稳态+整周期截断，
           120→50Hz 线性重采样，loop 缝检查，打包 ref_lib.pt

输出字段/每段：
  dof_pos (T,29) float32 gym序绝对关节角 @50Hz
  gait_period 秒 | phase_anchor_frame 50Hz帧号 | root_pos (T,3) | root_rot_wxyz (T,4)
  dof_names | fps=50 | source | n_cycles
"""
import os
import pickle
import sys

import numpy as np
import torch
import mujoco

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
GMR_DIR = os.path.join(ROOT, "resources/x1_gmr")
MJCF = os.path.join(ROOT, "resources/robots/x1/mjcf/x1_29dof_scene.xml")
OUT = os.path.join(ROOT, "resources/motions/processed/ref_lib.pt")

FLIP_JOINTS = [
    "right_shoulder_pitch_joint", "right_shoulder_roll_joint",
    "right_shoulder_yaw_joint", "right_elbow_pitch_joint",
    "right_elbow_yaw_joint", "right_ankle_pitch_joint",
]

# 方案 A 切段表：段名 → (源文件, 起始稳态秒, 端部余量秒)
GYM_SEG = {
    "walk_norm": ("0000_treadmill_norm", 2.0, 2.0),
    "walk_turn": ("0026_circle_walk", 1.0, 1.0),
    "walk_slow": ("0002_treadmill_slow", 2.0, 2.0),
}

FPS_SRC, FPS_DST = 120.0, 50.0

# Isaac Gym dof 序（权威源：env 启动 [DOF] 日志，gym.get_asset_dof_names 的 URDF 解析序）
# 注意：≠ MJCF hinge 枚举序（XML 定义序），也 ≠ URDF 纯 DFS 序——Isaac Gym 自有启发式排序。
# 每次更换 URDF 后必须人工核对 env [DOF] 日志与本表！
ISAAC_GYM_DOF_ORDER = [
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


def load_gmr(name):
    with open(os.path.join(GMR_DIR, name + ".pkl"), "rb") as f:
        m = pickle.load(f)
    dof_pos = np.asarray(m["dof_pos"], dtype=np.float64)          # (T,29) gmr 序
    root_pos = np.asarray(m["root_pos"], dtype=np.float64)        # (T,3)
    root_rot = np.asarray(m["root_rot"], dtype=np.float64)[:, [3, 0, 1, 2]]  # xyzw→wxyz
    body_pos = np.asarray(m["body_positions"], dtype=np.float64)  # (T,nbody,3) gmr body 序
    body_names = list(m["body_names"])
    dof_names = list(m["dof_names"])
    assert float(m["fps"]) == FPS_SRC, f"fps={m['fps']} != 120"
    return dof_pos, root_pos, root_rot, body_pos, body_names, dof_names


def gym_hinge_order():
    """FK 用 MJCF model + Isaac Gym dof 序常量（两者分离：MJCF 仅供 FK，排序以常量为准）"""
    model = mujoco.MjModel.from_xml_path(MJCF)
    names = list(ISAAC_GYM_DOF_ORDER)
    hinge = [model.joint(i).name for i in range(model.njnt)
             if model.jnt_type[i] == mujoco.mjtJoint.mjJNT_HINGE]
    assert sorted(names) == sorted(hinge), "ISAAC_GYM_DOF_ORDER 与 MJCF hinge 集合不一致"
    return model, names


def remap_flip(dof_pos, dof_names, hinge_names):
    """①重排 gmr→gym 序 + ②FLIP 6 关节取反"""
    idx = [dof_names.index(n) for n in hinge_names]
    q = dof_pos[:, idx].copy()
    for n in FLIP_JOINTS:
        q[:, hinge_names.index(n)] *= -1.0
    return q


def fk_check(model, hinge_names, q, root_pos, root_rot, body_pos, body_names, frames):
    """③FK 对拍：双方都转成"相对 base_link"局部坐标（gmr body_positions 为世界系，
    且其 base_link 存储位置 ≠ root_pos，直接世界系对比会差 ~0.5m）"""
    data = mujoco.MjData(model)
    jadr = {model.joint(i).name: model.jnt_qposadr[i] for i in range(model.njnt)}
    badr = {model.body(i).name: model.body(i).id for i in range(model.nbody)}
    i_base = body_names.index("base_link")
    errs = []
    for fi in frames:
        data.qpos[:] = 0.0
        data.qpos[jadr["base_link_free_joint"]:jadr["base_link_free_joint"] + 3] = root_pos[fi]
        wxyz = root_rot[fi] / np.linalg.norm(root_rot[fi])
        data.qpos[jadr["base_link_free_joint"] + 3: jadr["base_link_free_joint"] + 7] = wxyz
        for k, n in enumerate(hinge_names):
            data.qpos[jadr[n]] = q[fi, k]
        mujoco.mj_forward(model, data)
        p_base_sim = data.xpos[badr["base_link"]]
        e = []
        for bn in body_names:
            p_ref = body_pos[fi, body_names.index(bn)] - body_pos[fi, i_base]
            p_sim = data.xpos[badr[bn]] - p_base_sim
            e.append(np.linalg.norm(p_sim - p_ref))
        errs.append((np.mean(e), np.max(e)))
    return errs


def gait_period_autocorr(x, fps):
    """④a 左髋 pitch 自相关求主周期（0.5~2.0s 窗，抛物线细化）"""
    x = x - x.mean()
    ac = np.correlate(x, x, "full")[len(x) - 1:]
    ac /= ac[0]
    lo, hi = int(0.5 * fps), int(2.0 * fps)
    seg = ac[lo:hi]
    peaks = [i + lo for i in range(1, len(seg) - 1)
             if seg[i] > seg[i - 1] and seg[i] > seg[i + 1] and seg[i] > 0.3]
    assert peaks, "自相关无显著峰"
    p = peaks[0]
    y0, y1, y2 = ac[p - 1], ac[p], ac[p + 1]
    dp = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)
    return (p + dp) / fps, ac[p]


def phase_anchor(q, T_sec, fps, i_lhip, i_rhip):
    """④b 锚点：mocap 左髋 vs -sin(2πt/T) 滑动互相关最大相位（与 stance_mask 对齐）"""
    h_l = q[:, i_lhip] - q[:, i_lhip].mean()
    h_r = q[:, i_rhip] - q[:, i_rhip].mean()
    n = len(h_l)
    ttau = np.arange(n) / fps
    best_tau, best_c = 0, -2.0
    for tau in np.arange(0, T_sec, 1.0 / fps):
        m = -np.sin(2 * np.pi * (ttau - tau) / T_sec)
        c = float(np.dot(h_l, m) / (np.linalg.norm(h_l) * np.linalg.norm(m) + 1e-12))
        if c > best_c:
            best_c, best_tau = c, tau
    # 交叉验证：物理镜像 URDF 下左右关节角数值同相（左右髋 corr≈+0.99），
    # 故 R 也应与 −sin 同相（env 右腿 swing_delta 全反号，ref 与 −sin 同相，约定自洽）
    m_r = -np.sin(2 * np.pi * (ttau - best_tau) / T_sec)
    c_r = float(np.dot(h_r, m_r) / (np.linalg.norm(h_r) * np.linalg.norm(m_r) + 1e-12))
    return best_tau, best_c, c_r


def resample(q, rp, rr, fps_src, fps_dst):
    """②线性重采样（时长对齐到目标 fps 整数帧）"""
    T = q.shape[0]
    t_src = np.arange(T) / fps_src
    t_end = (T - 1) / fps_src
    n_dst = int(np.floor(t_end * fps_dst)) + 1
    t_dst = np.arange(n_dst) / fps_dst
    out = [np.stack([np.interp(t_dst, t_src, q[:, k]) for k in range(q.shape[1])], axis=1)]
    out.append(np.stack([np.interp(t_dst, t_src, rp[:, k]) for k in range(3)], axis=1))
    out.append(np.stack([np.interp(t_dst, t_src, rr[:, k]) for k in range(4)], axis=1))
    out.append(t_dst)
    return out


def main():
    model, hinge_names = gym_hinge_order()
    i_lhip, i_rhip = hinge_names.index("left_hip_pitch_joint"), hinge_names.index("right_hip_pitch_joint")
    lib = {}
    print(f"gym hinge 序（=env [DOF] 表）: {hinge_names[:6]} ... {hinge_names[-3:]}")

    for seg, (src, t_start, margin) in GYM_SEG.items():
        print(f"\n===== {seg} ← {src} =====")
        dof_pos, root_pos, root_rot, body_pos, body_names, dof_names = load_gmr(src)

        # ①② 重排 + 翻转
        q = remap_flip(dof_pos, dof_names, hinge_names)

        # ③ FK 抽查（原始 120Hz 首/中/尾帧）
        T_src_total = q.shape[0]
        frames = [0, T_src_total // 2, T_src_total - 1]
        errs = fk_check(model, hinge_names, q, root_pos, root_rot, body_pos, body_names, frames)
        for fi, (me, xe) in zip(frames, errs):
            print(f"  ③FK 帧{fi}: mean={me*1000:.2f}mm max={xe*1000:.2f}mm")
        # 阈值：mean<2mm；max<8mm（right_hip_yaw_link 固有 ~6mm 连杆长微差，见 verify-gmr）
        worst = max(errs, key=lambda e: e[1])
        assert worst[0] < 0.002 and worst[1] < 0.008, f"FK 异常: {worst}"

        # ④a 周期（切段前用整段原始 120Hz 检测）
        T_gait, ac_pk = gait_period_autocorr(q[:, i_lhip], FPS_SRC)
        print(f"  ④周期: T_gait={T_gait:.3f}s ({1/T_gait:.2f}Hz, r={ac_pk:.2f})")

        # ⑤ 切段：中间稳态 + 整周期截断（原始 120Hz 上切）
        dur = T_src_total / FPS_SRC
        n_cycles = int((dur - t_start - margin) / T_gait)
        f0, f1 = int(t_start * FPS_SRC), int(t_start * FPS_SRC) + int(round(n_cycles * T_gait * FPS_SRC))
        qs, rps, rrs = q[f0:f1], root_pos[f0:f1], root_rot[f0:f1]
        print(f"  ⑤切段: [{t_start:.1f}s, {f1/FPS_SRC:.2f}s] {n_cycles}整周期 {qs.shape[0]}帧@120Hz")

        # ④b 锚点（切段后信号上扫描一个周期）
        tau, c_l, c_r = phase_anchor(qs, T_gait, FPS_SRC, i_lhip, i_rhip)
        print(f"  ④锚点: tau={tau:.3f}s corr(L,−sin)={c_l:.2f} corr(R,−sin)={c_r:.2f}"
              f" {'[OK]' if c_l > 0.5 and c_r > 0.5 else '[WARN 相位弱]'}")

        # detrend：每关节去首尾线性漂移（治圆周走肩/腕漂移导致的 loop 缝，首尾严格相等）
        lag = np.linspace(0.0, 1.0, qs.shape[0])[:, None]
        qs = qs - lag * (qs[-1:, :] - qs[0:1, :])

        # 重采样 120→50Hz
        q50, rp50, rr50, t50 = resample(qs, rps, rrs, FPS_SRC, FPS_DST)

        # clip 到 URDF 声明限位（零星微超帧，如左膝过伸；打印统计）
        # 注意：model.jnt_range 行序 = MJCF hinge 枚举序 ≠ q50 列序（Isaac Gym 序），须按名→mjID 重排
        # ⚠ 用 mj_name2id（权威），勿用 model.joint(i).name 枚举序建映射（i 与 mjID 不一致）
        rows = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, n) for n in hinge_names]
        qlo, qhi = model.jnt_range[rows, 0], model.jnt_range[rows, 1]
        n_clipped = int(((q50 < qlo[None, :]) | (q50 > qhi[None, :])).sum())
        q50 = np.clip(q50, qlo[None, :], qhi[None, :])
        print(f"  ⑤clip: {n_clipped} 值超限已裁剪（限位经 exp0.2 修复：右肩roll/右肘pitch 已镜像）")

        # loop 缝检查（50Hz 首尾差，detrend 后应≈0）
        gap = np.abs(q50[0] - q50[-1]).max()
        print(f"  ⑤loop缝: max|q[0]-q[-1]|={gap:.4f}rad {'[OK]' if gap < 0.05 else '[WARN]'}")

        anchor50 = int(round(tau * FPS_DST))
        lib[seg] = dict(
            dof_pos=torch.from_numpy(q50.astype(np.float32)),
            root_pos=torch.from_numpy(rp50.astype(np.float32)),
            root_rot_wxyz=torch.from_numpy(rr50.astype(np.float32)),
            gait_period=float(T_gait),
            phase_anchor_frame=anchor50,
            fps=FPS_DST,
            dof_names=list(hinge_names),
            source=src,
            n_cycles=n_cycles,
        )
        print(f"  → {seg}: dof_pos{tuple(q50.shape)}@50Hz period={T_gait:.3f}s anchor={anchor50}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    torch.save(lib, OUT)
    total = sum(v["dof_pos"].shape[0] for v in lib.values())
    print(f"\n[SAVED] {OUT}  段数={len(lib)} 总帧={total} ({total/FPS_DST:.1f}s)")


if __name__ == "__main__":
    main()
