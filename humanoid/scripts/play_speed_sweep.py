# SPDX-FileCopyrightText: Copyright (c) 2021 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2021 ETH Zurich, Nikita Rudin
# SPDX-FileCopyrightText: Copyright (c) 2024 Beijing RobotEra TECHNOLOGY CO.,LTD. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause

# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
# list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

# Copyright (c) 2024, AgiBot Inc. All rights reserved.


import os
import csv
import math
import cv2
import numpy as np
from isaacgym import gymapi
from humanoid import LEGGED_GYM_ROOT_DIR

# import isaacgym
from humanoid.envs import *
from humanoid.utils import  get_args, export_policy_as_jit, task_registry, Logger
from isaacgym.torch_utils import *

import torch
from datetime import datetime

import pygame
from threading import Thread


x_vel_cmd, y_vel_cmd, yaw_vel_cmd = 0.0, 0.0, 0.0
joystick_use = True
joystick_opened = False

# =========== 速度阶梯（控制步数@100Hz, command_x [m/s]）：0.1→0.8（exp1.11 速度扫描口径） ===========
# §21d 口径更正：1 行 = 1 控制步 = 10ms（dt=0.001×decimation10），750 步 = 7.5s/档（注释"15s"为旧 50Hz 误记）
VEL_PROFILE = [
    (750, 0.1),
    (750, 0.2),
    (750, 0.3),
    (750, 0.4),
    (750, 0.5),
    (750, 0.6),
    (750, 0.7),
    (750, 0.8),
]
# §21b: 起步站立缓冲——训练分布是"先站稳再走"（stand 段 3~5s），spawn 即给速度属分布外空中起步
STAND_BUFFER_STEPS = 150   # 1.5s @100Hz
EFFECTIVE_PROFILE = [(STAND_BUFFER_STEPS, 0.0)] + VEL_PROFILE
TOTAL_PLAY_STEPS = sum(steps for steps, _ in EFFECTIVE_PROFILE)


def current_command(step_idx):
    """返回控制步 step_idx 对应的 command_x（含起步站立缓冲）。"""
    acc = 0
    for steps, vel in EFFECTIVE_PROFILE:
        if step_idx < acc + steps:
            return vel
        acc += steps
    return 0.0
# ==============================================================================

if joystick_use:
    pygame.init()
    try:
        # get joystick
        joystick = pygame.joystick.Joystick(0)
        joystick.init()
        joystick_opened = True
    except Exception as e:
        print(f"无法打开手柄：{e}")
    # joystick thread exit flag
    exit_flag = False

    def handle_joystick_input():
        global exit_flag, x_vel_cmd, y_vel_cmd, yaw_vel_cmd, head_vel_cmd
        
        
        while not exit_flag:
            # get joystick input
            pygame.event.get()
            # update robot command
            x_vel_cmd = -joystick.get_axis(1) * 1
            y_vel_cmd = -joystick.get_axis(0) * 1
            yaw_vel_cmd = -joystick.get_axis(3) * 1
            pygame.time.delay(100)

    if joystick_opened and joystick_use:
        joystick_thread = Thread(target=handle_joystick_input)
        joystick_thread.start()

def play(args):
    env_cfg, train_cfg = task_registry.get_cfgs(name=args.task)
    # §21c: PLAY_MATCH_TRAIN=1（默认）→ 下方全部"回放 override"被撤销，改用训练域评估（与 play.py 同口径）。
    # 先在覆盖前深拷贝训练域三项（覆盖是就地 mutate，引用快照无效）。
    import copy as _copy
    MATCH_TRAIN = os.environ.get("PLAY_MATCH_TRAIN", "1") != "0"
    _train_domain_rand = _copy.deepcopy(env_cfg.domain_rand)
    _train_noise = _copy.deepcopy(env_cfg.noise)
    _train_terrain = _copy.deepcopy(env_cfg.terrain)
    # override some parameters for testing
    env_cfg.env.num_envs = min(env_cfg.env.num_envs, 10)
    # env_cfg.terrain.mesh_type = 'trimesh'
    env_cfg.terrain.mesh_type = 'plane'
    env_cfg.terrain.num_rows = 5
    env_cfg.terrain.num_cols = 5
    env_cfg.terrain.max_init_terrain_level = 5
    env_cfg.env.episode_length_s = 1000
    env_cfg.noise.add_noise = False
    # headless 下保留 graphics device，供相机传感器离屏录制视频
    if RENDER:
        env_cfg.env.enable_headless_render = True
    # 回放动力学保真：关闭随机化后，把 armature/damping 固定为训练用校准中心值
    # （否则关节回退 URDF 默认 armature=0，有效惯量比训练时轻，策略在与训练不一致的动力学上被评测）
    env_cfg.domain_rand.randomize_joint_armature = False   # 随机关闭，改用下方固定值
    env_cfg.domain_rand.fixed_armature = {
        'left_hip_pitch_joint': 0.16,  'right_hip_pitch_joint': 0.16,   # legacy exp1.5 [0.09,0.23] 对称中心
        'left_hip_yaw_joint': 0.0105,  'right_hip_yaw_joint': 0.0105,   # legacy exp1.5 [0.003,0.018] 中心
        'left_knee_pitch_joint': 0.25, 'right_knee_pitch_joint': 0.25,  # legacy exp1.5 [0.18,0.32] CORE 中心
        # §21c: 踝 / 髋 roll 必须补全——旧版缺键 → 回退 URDF（无 armature 字段）+ asset.armature=0
        # → 物理 armature=0，训练范围踝 [0.003,0.04]、髋roll [0.0001,0.05]：0 在训练分布之外（前冲根因）
        'left_hip_roll_joint': 0.025,   'right_hip_roll_joint': 0.025,
        'left_ankle_pitch_joint': 0.0215, 'right_ankle_pitch_joint': 0.0215,
        'left_ankle_roll_joint': 0.0215,  'right_ankle_roll_joint': 0.0215,
        # ---- 29DOF 上半身（exp0 [0.003,0.04] 覆盖随机化中心；12DOF 任务下多余键自动无效）----
        'lumbar_yaw_joint': 0.0215,   'lumbar_roll_joint': 0.0215,   'lumbar_pitch_joint': 0.0215,
        'left_shoulder_pitch_joint': 0.0215,  'right_shoulder_pitch_joint': 0.0215,
        'left_shoulder_roll_joint': 0.0215,   'right_shoulder_roll_joint': 0.0215,
        'left_shoulder_yaw_joint': 0.0215,    'right_shoulder_yaw_joint': 0.0215,
        'left_elbow_pitch_joint': 0.0215,     'right_elbow_pitch_joint': 0.0215,
        'left_elbow_yaw_joint': 0.0215,       'right_elbow_yaw_joint': 0.0215,
        'left_wrist_pitch_joint': 0.0215,     'right_wrist_pitch_joint': 0.0215,
        'left_wrist_roll_joint': 0.0215,      'right_wrist_roll_joint': 0.0215,
    }
    # §21c: 该字段是 PhysX 的**被动关节阻尼**，不是 PD 的 D 增益！旧版误填 control.damping
    # （髋 3/膝 8/踝 1.5）→ 训练真实范围是 URDF damping=1.0 × U[0.3,1.5] = 0.3~1.5、中心 0.9，
    # 旧值 2~9x 越界（膝 8.0 vs 0.9）→ 关节迟滞跟不上参考。现值统一取训练中心 0.9。
    env_cfg.domain_rand.fixed_joint_damping = {
        n: 0.9 for n in env_cfg.domain_rand.fixed_armature
    }
    env_cfg.domain_rand.randomize_friction = False
    env_cfg.domain_rand.push_robots = False 
    env_cfg.domain_rand.continuous_push = False 
    env_cfg.domain_rand.randomize_base_mass = False 
    env_cfg.domain_rand.randomize_com = False 
    env_cfg.domain_rand.randomize_gains = False 
    env_cfg.domain_rand.randomize_torque = False 
    env_cfg.domain_rand.randomize_link_mass = False 
    env_cfg.domain_rand.randomize_motor_offset = False 
    env_cfg.domain_rand.randomize_joint_friction = False
    env_cfg.domain_rand.randomize_joint_damping = False
    env_cfg.domain_rand.randomize_joint_armature = False
    env_cfg.domain_rand.randomize_lag_timesteps = False
    # ---- train/play 延迟对齐（exp1.12 排查 §21，与 play.py 同款）----
    # 陷阱：randomize_lag_timesteps=False 时 else 分支取 range[1]=40 步钉最大延迟；
    # 且 randomize_dof_lag_timesteps 漏关会逐 reset 重抽。修正：两路延迟钉回训练中值。
    env_cfg.domain_rand.lag_timesteps_range = [22, 22]       # action 延迟 ~训练中值
    env_cfg.domain_rand.dof_lag_timesteps_range = [20, 20]   # q/dq 观测延迟 ~训练中值
    env_cfg.domain_rand.randomize_dof_lag_timesteps = False  # 防 reset 重抽
    env_cfg.noise.curriculum = False
    env_cfg.commands.heading_command = False

    # §21c: 撤销上面的域覆盖（保留 num_envs / episode_length_s / 延迟对齐）
    if MATCH_TRAIN:
        env_cfg.domain_rand = _train_domain_rand
        env_cfg.noise = _train_noise
        env_cfg.terrain = _train_terrain
        print("[sweep] MATCH_TRAIN: 域已还原为训练配置 "
              f"(terrain={env_cfg.terrain.mesh_type} {env_cfg.terrain.num_rows}x{env_cfg.terrain.num_cols}, "
              f"add_noise={env_cfg.noise.add_noise}, "
              f"friction_rand={env_cfg.domain_rand.randomize_friction}, "
              f"armature_rand={env_cfg.domain_rand.randomize_joint_armature})")

    train_cfg.seed = 123145
    print("train_cfg.runner_class_name:", train_cfg.runner_class_name)

    # prepare environment
    env, _ = task_registry.make_env(name=args.task, args=args, env_cfg=env_cfg)


    if RENDER:
        # 仅录制模式需要相机视角（set_camera 依赖 viewer，headless 下不可调用）
        env.set_camera(env_cfg.viewer.pos, env_cfg.viewer.lookat)


    # ---- 云端回放模式：--checkpoint_url_b64 = 签名下载 URL 的 URL-safe Base64 ----
    # 约定：checkpoint 与 model_isaac_csv.pt 都落在 logs/<experiment_name>/gm_play/（SDK 已识别的 PT 目录）
    gm_mode = getattr(args, "checkpoint_url_b64", None) is not None
    gm_play_dir = os.path.join(LEGGED_GYM_ROOT_DIR, 'logs', train_cfg.runner.experiment_name, 'gm_play')

    if gm_mode:
        import base64 as _b64
        import re as _re
        import urllib.request as _urlreq
        os.makedirs(gm_play_dir, exist_ok=True)
        ckpt_url = _b64.urlsafe_b64decode(args.checkpoint_url_b64.encode()).decode()
        m = _re.search(r"model_(\d+)\.pt", ckpt_url)
        ckpt_num = int(m.group(1)) if m else 0
        gm_ckpt_path = os.path.join(gm_play_dir, f"model_{ckpt_num}.pt")
        if not os.path.exists(gm_ckpt_path):
            print(f"[gm] downloading checkpoint -> {gm_ckpt_path}")
            _urlreq.urlretrieve(ckpt_url, gm_ckpt_path)
        print(f"[gm] checkpoint ready: {gm_ckpt_path}")

    # load policy
    if gm_mode:
        # 下载路径不在 exported_data 下，绕过 make_alg_runner 内部 resume，手动加载
        train_cfg.runner.resume = False
        ppo_runner, train_cfg, _ = task_registry.make_alg_runner(env=env, name=args.task, args=args, train_cfg=train_cfg, log_root=None)
        ppo_runner.load(gm_ckpt_path, load_optimizer=False)
    else:
        train_cfg.runner.resume = True
        ppo_runner, train_cfg, _ = task_registry.make_alg_runner(env=env, name=args.task, args=args, train_cfg=train_cfg)
    policy = ppo_runner.get_inference_policy(device=env.device)
    
    # export policy as a jit module (used to run it from C++)
    current_date_str = datetime.now().strftime('%Y-%m-%d')
    current_time_str = datetime.now().strftime('%H-%M-%S')
    if EXPORT_POLICY:
        path = os.path.join(LEGGED_GYM_ROOT_DIR, 'logs', train_cfg.runner.experiment_name, '0_exported', 'policies')
        export_policy_as_jit(ppo_runner.alg.actor_critic, path)
        print('Exported policy as jit script to: ', path)

    logger = Logger(env_cfg.sim.dt * env_cfg.control.decimation)
    robot_index = 0 # which robot is used for logging
    joint_index = 5 # which joint is used for logging
    stop_state_log = 1000 # number of steps before plotting states
    if RENDER:
        camera_properties = gymapi.CameraProperties()
        camera_properties.width = 1920
        camera_properties.height = 1080
        # camera_properties.width = 1280   # 原值: 1920
        # camera_properties.height = 720   # 原值: 1080
        h1 = env.gym.create_camera_sensor(env.envs[0], camera_properties)
        # camera_offset = gymapi.Vec3(1, -1, 0.5)
        # 修改视角把 Z 从 0.5 提高到 1.5，同时把 X,Y 距离拉大到 2.0
        camera_offset = gymapi.Vec3(2.0, -2.0, 1.5)
        camera_rotation = gymapi.Quat.from_axis_angle(gymapi.Vec3(-0.3, 0.2, 1),
                                                    np.deg2rad(135))
        actor_handle = env.gym.get_actor_handle(env.envs[0], 0)
        body_handle = env.gym.get_actor_rigid_body_handle(env.envs[0], actor_handle, 0)
        env.gym.attach_camera_to_body(
            h1, env.envs[0], body_handle,
            gymapi.Transform(camera_offset, camera_rotation),
            gymapi.FOLLOW_POSITION)

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")

        # 视频/CSV 输出到 logs/<experiment_name>/play_output/
        run_name_str = args.run_name if args.run_name is not None else "test"
        custom_save_path = os.path.join(LEGGED_GYM_ROOT_DIR, 'logs', train_cfg.runner.experiment_name, 'play_output')
        file_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{run_name_str}.mp4"
        video_filepath = os.path.join(custom_save_path, file_name)

        # 如果文件夹不存在，自动创建
        if not os.path.exists(custom_save_path):
            os.makedirs(custom_save_path, exist_ok=True)

        print(f"Recording video to: {video_filepath}")
        # 每隔 1 个控制步写 1 帧（实际 25fps），故 fps 标 25 保证 1:1 真实速度
        video = cv2.VideoWriter(video_filepath, fourcc, 25.0, (1920, 1080))
        # video = cv2.VideoWriter(video_filepath, fourcc, 25.0, (1280, 720))


        # video_dir = os.path.join(LEGGED_GYM_ROOT_DIR, 'videos')
        # experiment_dir = os.path.join(LEGGED_GYM_ROOT_DIR, 'videos', train_cfg.runner.experiment_name)
        # dir = os.path.join(experiment_dir, datetime.now().strftime('%b%d_%H-%M-%S')+ args.run_name + '.mp4')
        # if not os.path.exists(video_dir):
        #     os.makedirs(video_dir,exist_ok=True)
        # if not os.path.exists(experiment_dir):
        #     os.makedirs(experiment_dir,exist_ok=True)
        # video = cv2.VideoWriter(dir, fourcc, 50.0, (1920, 1080))
    
    obs = env.get_observations()
    frame_count = 0
    np.set_printoptions(formatter={'float': '{:0.4f}'.format})

    # 足部刚体索引（用于诊断与视频叠加的接触力，替代硬编码索引）
    left_foot_idx = env.feet_indices[0].item()
    right_foot_idx = env.feet_indices[1].item()

    # 诊断输出目录（CSV 不依赖 RENDER，始终输出）
    diag_out_dir = os.path.join(LEGGED_GYM_ROOT_DIR, 'logs', train_cfg.runner.experiment_name, 'play_output')
    os.makedirs(diag_out_dir, exist_ok=True)
    # 对齐真机 walk_diag 列（czy/real_data/13rt/walk_diag_*.csv）：基座 + 逐关节 action/pos/vel/effort/pos_des_raw
    # 保留 base_vel_x/y/z 旧列（isaac-diag-eval 与既有分析依赖）
    dof_names = [n[:-6] if n.endswith('_joint') else n for n in env.dof_names]  # 去掉 _joint 后缀做列名
    diag = {k: [] for k in ["phase_sin", "phase_cos", "cycle_time", "smoothed_speed", "active_stage",
                            "cmd_linear_x", "cmd_linear_y", "cmd_angular_z",
                            "base_euler_x", "base_euler_y", "base_euler_z",
                            "base_ang_vel_x", "base_ang_vel_y", "base_ang_vel_z",
                            "base_vel_x", "base_vel_y", "base_vel_z",
                            "base_height", "base_pos_x", "base_pos_y", "base_yaw",
                            "foot_z_l", "foot_z_r", "foot_force_l", "foot_force_r",
                            "command_x"]}
    for jn in dof_names:
        for q in ["action", "pos", "vel", "effort", "pos_des_raw"]:
            diag[f"{q}_{jn}_joint"] = []
    clip_count = 0  # 力矩限幅累计计数（对应真机 clip_count）

    # =========== 新增：初始化速度累加器 ===========
    vel_sum = 0.0       # 速度总和
    step_accum = 0      # 步数计数器
    # ===========================================

    for i in range(TOTAL_PLAY_STEPS):

        actions = policy(obs.detach()) # * 0.

        if FIX_COMMAND:
            # 速度阶梯：0 → 0.6 → 0
            env.commands[:, 0] = current_command(i)
            env.commands[:, 1] = 0
            env.commands[:, 2] = 0
            env.commands[:, 3] = 0.

        else:
            env.commands[:, 0] = x_vel_cmd
            env.commands[:, 1] = y_vel_cmd
            env.commands[:, 2] = yaw_vel_cmd
            env.commands[:, 3] = 0.
        # 定义一个计数器在循环外
        
        obs, critic_obs, rews, dones, infos = env.step(actions.detach())
        # =========== 新增：每一帧都更新统计数据 ===========
        # 即使不录制这一帧，也要统计这一帧的数据，这样平均值才准确
        current_vel_x = env.base_lin_vel[0, 0].item()
        vel_sum += current_vel_x
        step_accum += 1
        # ===============================================

        # =========== 每步诊断采集（与 RENDER 无关） ===========
        real_cmd_x = env.commands[robot_index, 0].item()
        bq = env.root_states[robot_index, 3:7]
        # 四元数 (x,y,z,w) -> roll/pitch/yaw（与 ang_vel 一同对齐真机 imu 列）
        qx, qy, qz, qw = bq[0].item(), bq[1].item(), bq[2].item(), bq[3].item()
        roll = math.atan2(2.0 * (qw * qx + qy * qz), 1.0 - 2.0 * (qx * qx + qy * qy))
        pitch = math.asin(max(-1.0, min(1.0, 2.0 * (qw * qy - qz * qx))))
        base_yaw = torch.atan2(2.0 * (bq[3] * bq[2] + bq[0] * bq[1]),
                               1.0 - 2.0 * (bq[1] * bq[1] + bq[2] * bq[2]))
        # 步态相位：直接用 env._get_phase（exp0.2 逐段周期 + 站立归零，与观测同源）
        ph = env._get_phase()[robot_index].item() % 1.0
        diag["phase_sin"].append(math.sin(2 * math.pi * ph))
        diag["phase_cos"].append(math.cos(2 * math.pi * ph))
        # 有效周期：mocap 行走段 = 段周期/缩放（exp1.7 自适应步频后为 _current_cycle_time）；
        # 站立/回退 = 全局 cycle_time
        eff_cycle = env_cfg.rewards.cycle_time
        if getattr(env, "use_mocap_ref", False):
            walking = torch.norm(env.commands[robot_index, :3]).item() > env_cfg.commands.stand_com_threshold
            if walking:
                env.seg_id = env._current_seg_id()
                eff_cycle = float(env._current_cycle_time()[robot_index].item())
        diag["cycle_time"].append(eff_cycle)
        diag["smoothed_speed"].append(0.0)
        diag["active_stage"].append(0)
        diag["cmd_linear_x"].append(real_cmd_x)
        diag["cmd_linear_y"].append(env.commands[robot_index, 1].item())
        diag["cmd_angular_z"].append(env.commands[robot_index, 2].item())
        diag["command_x"].append(real_cmd_x)
        diag["base_euler_x"].append(roll)
        diag["base_euler_y"].append(pitch)
        diag["base_euler_z"].append(base_yaw.item())
        diag["base_ang_vel_x"].append(env.base_ang_vel[robot_index, 0].item())
        diag["base_ang_vel_y"].append(env.base_ang_vel[robot_index, 1].item())
        diag["base_ang_vel_z"].append(env.base_ang_vel[robot_index, 2].item())
        diag["base_vel_x"].append(current_vel_x)
        diag["base_vel_y"].append(env.base_lin_vel[robot_index, 1].item())
        diag["base_vel_z"].append(env.base_lin_vel[robot_index, 2].item())
        diag["base_height"].append(env.root_states[robot_index, 2].item())
        diag["base_pos_x"].append(env.root_states[robot_index, 0].item())
        diag["base_pos_y"].append(env.root_states[robot_index, 1].item())
        diag["base_yaw"].append(base_yaw.item())
        diag["foot_z_l"].append(env.rigid_state[robot_index, left_foot_idx, 2].item())
        diag["foot_z_r"].append(env.rigid_state[robot_index, right_foot_idx, 2].item())
        diag["foot_force_l"].append(env.contact_forces[robot_index, left_foot_idx, 2].item())
        diag["foot_force_r"].append(env.contact_forces[robot_index, right_foot_idx, 2].item())
        # 逐关节：策略输出（缩放前）、位置、速度、实际力矩、期望位置（lagged action + default）
        for k, jn in enumerate(dof_names):
            diag[f"action_{jn}_joint"].append(env.actions[robot_index, k].item())
            diag[f"pos_{jn}_joint"].append(env.dof_pos[robot_index, k].item())
            diag[f"vel_{jn}_joint"].append(env.dof_vel[robot_index, k].item())
            tau = env.torques[robot_index, k].item()
            diag[f"effort_{jn}_joint"].append(tau)
            if abs(tau) >= env.torque_limits[k].item() - 1e-6:
                clip_count += 1
            pos_des = (env.lagged_actions_scaled[robot_index, k] + env.default_dof_pos[robot_index, k]).item()
            diag[f"pos_des_raw_{jn}_joint"].append(pos_des)
        # =====================================================
        if RENDER:
            frame_count += 1
            env.gym.fetch_results(env.sim, True)
            env.gym.step_graphics(env.sim)
            env.gym.render_all_camera_sensors(env.sim)

            if frame_count % 2 == 0:
                img = env.gym.get_camera_image(env.sim, env.envs[0], h1, gymapi.IMAGE_COLOR)
                # img = np.reshape(img, (720, 1280, 4))
                img = np.reshape(img, (1080, 1920, 4))
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

                # # ==================== 添加前进速度记录 ====================

                # # 1. 获取数据
                # target_vel = env.commands[0, 0].item()
                
                # # 计算平均速度 (防止除以0)
                # avg_vel = vel_sum / step_accum if step_accum > 0 else 0.0
                
                # # 2. 准备显示的文本 (稍微长一点)
                # # 格式：CMD(指令) | REAL(瞬时) | AVG(平均)
                # info_text = f"CMD: {target_vel:.2f} | REAL: {current_vel_x:.2f} | AVG: {avg_vel:.2f}"
                
                # # 3. 计算文字位置
                # # 因为文字变长了，为了不跑出画面，我们需要把起始位置往左移
                # img_h, img_w = img.shape[:2]
                # text_pos = (img_w - 950, 60)  # 从 -550 改为 -750，留出更多空间

                # # 4. 绘制文字 (黑边 + 青字)
                # cv2.putText(img, info_text, text_pos, 
                #             cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 4, cv2.LINE_AA)
                # cv2.putText(img, info_text, text_pos, 
                #             cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 0), 2, cv2.LINE_AA)
                # # ==================== 前进速度结束 ====================
                # ==================== 1. 获取基础数据 ====================
                # 速度数据
                target_vel = env.commands[0, 0].item()
                current_vel_x = env.base_lin_vel[0, 0].item()
                avg_vel = vel_sum / step_accum if step_accum > 0 else 0.0

                # y/z 方向与偏航速度（诊断缓冲区最新值）
                current_vel_y = diag["base_vel_y"][-1]
                current_vel_z = diag["base_vel_z"][-1]
                current_vel_yaw = diag["base_ang_vel_z"][-1]

                # 接触力数据（使用 feet_indices，与诊断一致）
                left_force = diag["foot_force_l"][-1]
                right_force = diag["foot_force_r"][-1]
                
                # 接触判断 (阈值 1.0 N)
                l_on = left_force > 1.0
                r_on = right_force > 1.0

                # ==================== 2. 定义显示布局 ====================
                img_h, img_w = img.shape[:2]
                base_x = img_w - 1150  # 起始 X 坐标
                base_y = 60           # 起始 Y 坐标
                line_height = 50      # 行高

                # 辅助函数：快速绘制带描边的文字
                def draw_outlined_text(image, text, pos, color, scale=0.9):
                    # 黑描边
                    cv2.putText(image, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4, cv2.LINE_AA)
                    # 彩色字
                    cv2.putText(image, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2, cv2.LINE_AA)

                # ==================== 3. 绘制第一行：x 速度信息 ====================
                speed_text = f"CMD: {target_vel:.2f} | REAL: {current_vel_x:.2f} | AVG: {avg_vel:.2f}"
                draw_outlined_text(img, speed_text, (base_x, base_y), (255, 255, 0), 1.0) # 青色

                # ==================== 3.1 绘制第二行：y/z 方向与偏航速度 ====================
                vel_yz_text = f"VEL_Y: {current_vel_y:+.2f} | VEL_Z: {current_vel_z:+.2f} | VEL_YAW: {current_vel_yaw:+.2f}"
                draw_outlined_text(img, vel_yz_text, (base_x, base_y + line_height), (0, 255, 255), 0.9) # 黄色

                # ==================== 4. 绘制第三、四行：单脚状态 ====================
                # 左脚
                l_color = (0, 255, 0) if l_on else (0, 0, 255) # 绿/红
                l_text = f"L-FOOT: {'ON ' if l_on else 'OFF'} ({left_force:.1f} N)"
                draw_outlined_text(img, l_text, (base_x, base_y + line_height * 2), l_color)

                # 右脚
                r_color = (0, 255, 0) if r_on else (0, 0, 255) # 绿/红
                r_text = f"R-FOOT: {'ON ' if r_on else 'OFF'} ({right_force:.1f} N)"
                draw_outlined_text(img, r_text, (base_x, base_y + line_height * 3), r_color)

                # ==================== 5. 绘制第五行：步态全局状态 (新增) ====================
                
                state_text = "STATE: SINGLE SUPPORT" # 默认单支撑
                state_color = (200, 200, 200)        # 默认灰色

                if l_on and r_on:
                    # 双脚着地 (Double Support)
                    state_text = "STATE: *** DOUBLE SUPPORT ***"
                    state_color = (0, 255, 255) # 黄色 (BGR: Yellow)
                
                elif not l_on and not r_on:
                    # 双脚离地 (Flight Phase)
                    state_text = "STATE: >>> FLIGHT PHASE <<<"
                    state_color = (255, 0, 255) # 紫色 (BGR: Magenta)

                # 绘制状态
                draw_outlined_text(img, state_text, (base_x, base_y + line_height * 4), state_color, 1.0)

                # ==================== 结束绘制 ====================
               

                video.write(img[..., :3])
        real_cmd_x = env.commands[robot_index, 0].item()

        if i > stop_state_log*0.2 and i < stop_state_log:
            dict = {
                    'base_height' : env.root_states[robot_index, 2].item(),
                    'foot_z_l' : env.rigid_state[robot_index,4,2].item(),
                    'foot_z_r' : env.rigid_state[robot_index,9,2].item(),
                    'foot_forcez_l' : env.contact_forces[robot_index,4,2].item(),
                    'foot_forcez_r' : env.contact_forces[robot_index,9,2].item(),
                    'base_vel_x': env.base_lin_vel[robot_index, 0].item(),
                    # 'command_x': x_vel_cmd,
                    'command_x': real_cmd_x,
                    'base_vel_y':  env.base_lin_vel[robot_index, 1].item(),
                    'command_y': y_vel_cmd,
                    'base_vel_z':  env.base_lin_vel[robot_index, 2].item(),
                    'base_vel_yaw':  env.base_ang_vel[robot_index, 2].item(),
                    'command_yaw': yaw_vel_cmd,
                    'dof_pos_target': actions[robot_index, 0].item() * env.cfg.control.action_scale,
                    'dof_pos': env.dof_pos[robot_index, 0].item(),
                    'dof_vel': env.dof_vel[robot_index, 0].item(),
                    'dof_torque': env.torques[robot_index, 0].item(),
                    'command_sin': obs[0,0].item(),
                    'command_cos': obs[0,1].item(),
                }

            # add dof_pos_target
            for i in range(env_cfg.env.num_actions):
                dict[f'dof_pos_target[{i}]'] = actions[robot_index, i].item() * env.cfg.control.action_scale,

            # add dof_pos
            for i in range(env_cfg.env.num_actions):
                dict[f'dof_pos[{i}]'] = env.dof_pos[robot_index, i].item(),

            # add dof_torque
            for i in range(env_cfg.env.num_actions):
                dict[f'dof_torque[{i}]'] = env.torques[robot_index, i].item(),

            # add dof_vel
            for i in range(env_cfg.env.num_actions):
                dict[f'dof_vel[{i}]'] = env.dof_vel[robot_index, i].item(),

            logger.log_states(dict=dict)
        
        elif _== stop_state_log:
            logger.plot_states()
        elif i == stop_state_log:
            logger.plot_states()

        # ====================== Log states ======================
        if infos["episode"]:
            num_episodes = torch.sum(env.reset_buf).item()
            if num_episodes>0:
                logger.log_rewards(infos["episode"], num_episodes)

    # =========== 回放结束：写出诊断 CSV + 分段 Summary ===========
    dt = env_cfg.sim.dt * env_cfg.control.decimation
    csv_path = os.path.join(diag_out_dir, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{run_name_str if RENDER else 'test'}_isaac_diag.csv")
    base_cols = ["step", "time_s", "phase_sin", "phase_cos", "cycle_time", "smoothed_speed", "active_stage",
                 "cmd_linear_x", "cmd_linear_y", "cmd_angular_z",
                 "base_euler_x", "base_euler_y", "base_euler_z",
                 "base_ang_vel_x", "base_ang_vel_y", "base_ang_vel_z",
                 "base_vel_x", "base_vel_y", "base_vel_z",
                 "base_height", "base_pos_x", "base_pos_y", "base_yaw",
                 "foot_z_l", "foot_z_r", "foot_force_l", "foot_force_r", "command_x", "clip_count"]
    joint_cols = [f"{q}_{jn}_joint" for jn in dof_names for q in ["action", "pos", "vel", "effort", "pos_des_raw"]]
    header = base_cols + joint_cols
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for i in range(len(diag["command_x"])):
            row = [i, round(i * dt, 6)] + [diag[c][i] for c in base_cols[2:] if c != "clip_count"]
            row.append(clip_count)  # 累计限幅计数（每行重复累计值）
            row += [diag[c][i] for c in joint_cols]
            writer.writerow(row)
    print(f"Saved diagnostic CSV -> {csv_path}")
    print(f"Torque clip count (total, all dofs x steps): {clip_count}")

    print("\n===== Speed Profile Summary =====")
    acc = 0
    for seg_i, (steps, vel) in enumerate(EFFECTIVE_PROFILE):
        seg_vels = diag["base_vel_x"][acc:acc + steps]
        tag = "stand_buffer" if seg_i == 0 else f"cmd={vel:.2f} m/s"
        print(f"  Segment {seg_i} ({tag}): avg_real={np.mean(seg_vels):.3f} m/s")
        acc += steps

    if RENDER:
        video.release()

    # ---- 云端回放（gm）模式产物打包：视频平铺 + CSV 打包为 model_isaac_csv.pt ----
    if gm_mode:
        import shutil
        import time as _time
        if RENDER and os.path.exists(video_filepath):
            flat_video = os.path.join(LEGGED_GYM_ROOT_DIR, 'logs', train_cfg.runner.experiment_name, 'play_output.mp4')
            shutil.copyfile(video_filepath, flat_video)
            print(f"[gm] video copied -> {flat_video}")
        pack_path = os.path.join(gm_play_dir, "model_isaac_csv.pt")
        with open(csv_path, "rb") as f:
            torch.save({"bytes": f.read(), "filename": os.path.basename(csv_path)}, pack_path)
        print(f"[gm] packed CSV -> {pack_path}")
        print("[gm] keeping files for SDK scan/upload (60s)...")
        _time.sleep(60)

if __name__ == '__main__':
    EXPORT_POLICY = False
    # exp1.6 回放 workaround（2026-09-09）：本机 Vulkan/相机层段错误（×2 复现，CUDA 正常），
    # 临时经环境变量 PLAY_RENDER=0 关渲染先出 CSV；恢复视频再置 1 或走云端 gm_mode 回放
    RENDER = os.environ.get("PLAY_RENDER", "1") != "0"
    FIX_COMMAND = True
    args = get_args()
    play(args)
