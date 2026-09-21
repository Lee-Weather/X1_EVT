#!/usr/bin/env python
"""Play retargeted X1 motion (x1_gmr / x1_lab pkl) in MuJoCo — 本仓库版。

模型: resources/robots/x1/mjcf/x1_29dof_scene.xml（由工作区 X1_29DOF_physically_mirrored.urdf
转换生成，见 scripts/tools/urdf2mjcf.py；freejoint 名 base_link_free_joint）

数据约定（承接 acceptance/play_motion_mujoco.py 实证）:
  x1_gmr pkl : root_rot 为 XYZW，加载时转 WXYZ；dof 带 dof_names，按名重排
  x1_lab pkl : root_rot 已是 WXYZ；dof 为 Isaac Lab 序，按 LAB_DOF_ORDER 重排

右半身符号翻转（FLIP_JOINTS）:
  前代 X1_29_AMP xml 的右臂/右踝为轴复制，当前 physically_mirrored URDF 为物理镜像，
  轴约定相反。数值搜索实证须对 6 关节取反（FK 位置 0.2mm / 姿态 0.03°）:
  right_shoulder_pitch/roll/yaw + right_elbow_pitch/yaw + right_ankle_pitch

用法（服务器无显示，用离屏录制）:
  xvfb-run -a -s "-screen 0 1280x720x24" python scripts/tools/play_motion_mujoco.py \
      0000_treadmill_norm --record resources/x1_gmr/video/0000_treadmill_norm.mp4
"""
import argparse
import os
import pickle
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_MODEL = os.path.join(ROOT, "resources/robots/x1/mjcf/x1_29dof_scene.xml")
DEFAULT_DATA_ROOTS = [
    os.path.join(ROOT, "resources/x1_gmr"),
    os.path.join(ROOT, "resources/x1_lab"),
]
FREEJOINT_NAME = "base_link_free_joint"

# 右半身符号翻转规则（数值搜索实证）
FLIP_JOINTS = [
    "right_shoulder_pitch_joint", "right_shoulder_roll_joint",
    "right_shoulder_yaw_joint", "right_elbow_pitch_joint",
    "right_elbow_yaw_joint", "right_ankle_pitch_joint",
]

# Isaac Lab x1_lab pkl dof 列序（文件无 dof_names）
LAB_DOF_ORDER = [
    "left_hip_pitch_joint", "lumbar_yaw_joint", "right_hip_pitch_joint",
    "left_hip_roll_joint", "lumbar_roll_joint", "right_hip_roll_joint",
    "left_hip_yaw_joint", "lumbar_pitch_joint", "right_hip_yaw_joint",
    "left_knee_pitch_joint", "left_shoulder_pitch_joint",
    "right_shoulder_pitch_joint", "right_knee_pitch_joint",
    "left_ankle_pitch_joint", "left_shoulder_roll_joint",
    "right_shoulder_roll_joint", "right_ankle_pitch_joint",
    "left_ankle_roll_joint", "left_shoulder_yaw_joint",
    "right_shoulder_yaw_joint", "right_ankle_roll_joint",
    "left_elbow_pitch_joint", "right_elbow_pitch_joint",
    "left_elbow_yaw_joint", "right_elbow_yaw_joint",
    "left_wrist_pitch_joint", "right_wrist_pitch_joint",
    "left_wrist_roll_joint", "right_wrist_roll_joint",
]

LAB_KEY_BODY_ORDER = [
    "left_knee_pitch_link", "right_knee_pitch_link",
    "left_ankle_roll_link", "right_ankle_roll_link",
    "left_elbow_yaw_link", "right_elbow_yaw_link",
]

import mujoco
import numpy as np


def find_motions(path):
    if os.path.isfile(path):
        return [path]
    if os.path.isdir(path):
        return sorted(
            os.path.join(dp, f) for dp, _, fs in os.walk(path)
            for f in fs if f.endswith(".pkl"))
    for root in DEFAULT_DATA_ROOTS:
        for dp, _, fs in os.walk(root):
            for f in fs:
                if f == path or f == path + ".pkl":
                    return [os.path.join(dp, f)]
    return []


def load_motion(path):
    with open(path, "rb") as f:
        m = pickle.load(f)
    fps = float(m.get("fps", 120.0))
    root_pos = np.asarray(m["root_pos"], dtype=np.float64)
    root_rot = np.asarray(m["root_rot"], dtype=np.float64)
    dof_pos = np.asarray(m["dof_pos"], dtype=np.float64)
    if "dof_names" in m:
        fmt = "gmr"
        root_rot = root_rot[:, [3, 0, 1, 2]]  # xyzw -> wxyz
        dof_names = list(m["dof_names"])
    else:
        fmt = "lab"
        dof_names = list(LAB_DOF_ORDER)
    return fps, root_pos, root_rot, dof_pos, dof_names, fmt, m


def remap_dof(model, dof_pos, dof_names, joint_names):
    """Reorder dof columns from data names to model qpos order."""
    idx = {n: i for i, n in enumerate(dof_names)}
    missing = [n for n in joint_names if n not in idx]
    if missing:
        sys.exit(f"data dof_names missing model joints: {missing}")
    cols = np.array([idx[n] for n in joint_names])
    return dof_pos[:, cols]


def verify_against_stored(model, data, motion, qpos, fmt):
    """Sanity-check conventions vs stored FK truth (if present)."""
    names_truth = None
    if fmt == "gmr" and "body_positions" in motion:
        truth = np.asarray(motion["body_positions"])       # (T,30,3)
        names_truth = list(motion["body_names"])
    elif fmt == "lab" and "key_body_pos" in motion:
        truth = np.asarray(motion["key_body_pos"])         # (T,6,3)
        names_truth = list(LAB_KEY_BODY_ORDER)
    else:
        return
    frames = np.linspace(0, qpos.shape[0] - 1, 8).astype(int)
    errs = []
    per_body = {}
    for t in frames:
        data.qpos[:] = qpos[t]
        mujoco.mj_forward(model, data)
        root = data.xpos[model.body("base_link").id]
        rel_mj = np.array([data.xpos[model.body(n).id] - root for n in names_truth])
        rel_tr = (truth[t] - truth[t, 0]) if fmt == "gmr" else \
            (truth[t] - np.asarray(motion["root_pos"])[t])
        e = np.linalg.norm(rel_mj - rel_tr, axis=1)
        errs.append(e.mean())
        for n, ei in zip(names_truth, e):
            per_body[n] = max(per_body.get(n, 0.0), ei)
    tag = "OK" if np.mean(errs) < 0.05 else "MISMATCH"
    print(f"[verify-{fmt}] FK vs stored: mean err {np.mean(errs):.4f} m  [{tag}]")
    for n in sorted(per_body, key=lambda k: -per_body[k])[:5]:
        if per_body[n] > 1e-3:
            print(f"    {n}: {per_body[n]*1000:.1f} mm")


def build_qpos(model, root_pos, root_rot, dof_pos, dof_names, flip=True):
    """Build (T, nq) qpos. Applies right-half flip unless flip=False."""
    joint_names = [model.joint(i).name for i in range(model.njnt)]
    hinge_names = [n for n in joint_names if n != FREEJOINT_NAME]
    dof_pos = remap_dof(model, dof_pos, dof_names, hinge_names)

    if flip:
        cols = [hinge_names.index(n) for n in FLIP_JOINTS]
        dof_pos = dof_pos.copy()
        dof_pos[:, cols] *= -1

    qpos = np.zeros((root_pos.shape[0], model.nq))
    qpos[:, 0:3] = root_pos
    qpos[:, 3:7] = root_rot
    addr = 0
    for i in range(model.njnt):
        if model.jnt_type[i] == mujoco.mjtJoint.mjJNT_FREE:
            continue
        qpos[:, model.jnt_qposadr[i]] = dof_pos[:, addr]
        addr += 1
    assert addr == dof_pos.shape[1]
    if not np.isfinite(qpos).all():
        bad = np.where(~np.isfinite(qpos).all(axis=1))[0]
        sys.exit(f"non-finite qpos at frames {bad[:5]} ... aborting")
    return qpos


def record_video(model, data, qpos, fps, out_path, width=640, height=360):
    """Stream frames to PNG temp dir, then ffmpeg-combine to mp4 (no imageio-ffmpeg)."""
    import imageio.v2 as imageio

    model.vis.global_.offwidth = width
    model.vis.global_.offheight = height
    rend = mujoco.Renderer(model, height=height, width=width)
    cam = mujoco.MjvCamera()
    cam.azimuth, cam.elevation, cam.distance = 130, -15, 4.5

    tmpdir = tempfile.mkdtemp(prefix="x1_replay_")
    n = qpos.shape[0]
    for t in range(n):
        data.qpos[:] = qpos[t]
        mujoco.mj_forward(model, data)
        rend.update_scene(data, camera=cam)
        img = rend.render()
        imageio.imwrite(os.path.join(tmpdir, f"f{t:06d}.png"), img)
        if (t + 1) % 200 == 0:
            print(f"  frame {t+1}/{n} ({100.0*(t+1)/n:.0f}%)", flush=True)

    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    pat = os.path.join(tmpdir, "f%06d.png")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(int(fps)),
         "-i", pat, "-pix_fmt", "yuv420p", out_path], check=True)
    print(f"recorded {n} frames -> {out_path}")
    # cleanup temp frames
    shutil_rmtree(tmpdir)


def shutil_rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("motion", help=".pkl file or bare name to search")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--record", metavar="MP4", help="offscreen render to mp4")
    ap.add_argument("--no-flip", action="store_true",
                    help="data already FLIP-corrected (e.g. extracted from ref_lib.pt)")
    args = ap.parse_args()

    model = mujoco.MjModel.from_xml_path(args.model)
    data = mujoco.MjData(model)

    motion = find_motions(args.motion)
    if not motion:
        sys.exit(f"no .pkl found for {args.motion}")
    path = motion[0]

    fps, root_pos, root_rot, dof_pos, dof_names, fmt, m = load_motion(path)
    qpos = build_qpos(model, root_pos, root_rot, dof_pos, dof_names, flip=not args.no_flip)
    verify_against_stored(model, data, m, qpos, fmt)

    print(f"\nmotion : {os.path.relpath(path, ROOT)}  [{fmt}]")
    print(f"frames: {qpos.shape[0]}  @ {fps:.0f} fps  ({qpos.shape[0]/fps:.1f}s)  "
          f"| nq={model.nq}")

    if args.record:
        record_video(model, data, qpos, fps, args.record)
    else:
        sys.exit("must pass --record (headless playback)")


if __name__ == "__main__":
    main()