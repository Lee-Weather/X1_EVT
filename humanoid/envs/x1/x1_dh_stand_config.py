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

from humanoid.envs.base.legged_robot_config import LeggedRobotCfg, LeggedRobotCfgPPO

class X1DHStandCfg(LeggedRobotCfg):
    """
    Configuration class for the XBotL humanoid robot.
    """
    class env(LeggedRobotCfg.env):
        # change the observation dim
        frame_stack = 66      #all histroy obs num
        short_frame_stack = 5   #short history step
        c_frame_stack = 3  #all histroy privileged obs num
        num_single_obs = 98    # 29DOF: 5(cmd) + 3*29(q/dq/action) + 6(ang_vel/euler)
        num_observations = int(frame_stack * num_single_obs)
        single_num_privileged_obs = 141  # 29DOF: 5 + 4*29(q/dq/action/diff) + 20(其余特权量)
        single_linvel_index = 121  # 29DOF: 5 + 4*29（base_lin_vel 起始列）
        num_privileged_obs = int(c_frame_stack * single_num_privileged_obs)
        num_actions = 29
        num_envs = 4096
        episode_length_s = 24 #episode length in seconds
        use_ref_actions = False
        num_commands = 5 # sin_pos cos_pos vx vy vz

    class safety:
        # safety factors
        pos_limit = 1.0
        vel_limit = 1.0
        torque_limit = 0.85

    class termination:
        # exp1.12: 收紧 termination（§20，x1 env override check_termination 读取）——
        # base 判据 1.5rad=86° 过松，趴地扑腾段（pitch 30~75°、h~0.1m）大量进入训练分布，
        # 污染 PPO/AMP 样本（exp1.11 修正：训练 episode ~10.9s 即摔终止，timeout 24s 远未到）
        roll_pitch_cutoff = 0.8   # rad（46°）：exp1.11 摔倒 pitch 峰值 44~75°，拦住一半以上
        base_height_cutoff = 0.45 # m：站立基线 0.607，跌破即半摔（回放判据 h<0.455 同口径）


    class asset(LeggedRobotCfg.asset):
        # exp0：29DOF 全身 URDF（Isaac Gym dof 序：左腿0-5/腰6-8/左臂9-15/右臂16-22/右腿23-28，env 按名索引腿部）
        # 右踝 pitch 轴 (0 0 -1)@rpy(π,0,0)，与左踝世界轴反平行（原版 physically_mirrored 约定，exp0 验证）
        file = '{LEGGED_GYM_ROOT_DIR}/resources/robots/x1/urdf/X1_29DOF_physically_mirrored.urdf'
        xml_file = '{LEGGED_GYM_ROOT_DIR}/resources/robots/x1/mjcf/xyber_x1_flat.xml'

        name = "x1"
        foot_name = "ankle_roll"
        knee_name = "knee_pitch"

        terminate_after_contacts_on = ['base_link']
        penalize_contacts_on = ["base_link"]
        self_collisions = 0  # 1 to disable, 0 to enable...bitwise filter
        flip_visual_attachments = False
        replace_cylinder_with_capsule = False
        fix_base_link = False

    class terrain(LeggedRobotCfg.terrain):
        # exp1.13: 训练地形改为全平（真·无限平面）。原 trimesh 20x20 随机地形实测为
        # 30% flat + 20% rough flat(±1cm) + 40% ≤5.4° 缓坡 + 10% mm 级凸块，本身近乎平地，
        # 但 curriculum=False 时 reset 出生点按 U(-4,4)m 撒进 8m 格（86% 落在坡面/凹坑上），
        # 且 z 取中心 2m 窗口最大高度 → 与实际落点最多差 ±0.15m（凹格直接穿地），
        # 是每个 episode 周期性注入的强扰动源。改 plane 同时与 play.py/play_speed_sweep 一致。
        # 下方 num_rows/num_cols/terrain_dict/*_range 在 plane 下不再生效（仅 trimesh/heightfield 使用）。
        mesh_type = 'plane'
        curriculum = False
        # rough terrain only:
        measure_heights = False
        static_friction = 0.6
        dynamic_friction = 0.6
        terrain_length = 8.
        terrain_width = 8.
        num_rows = 20  # number of terrain rows (levels)
        num_cols = 20  # number of terrain cols (types)
        max_init_terrain_level = 5  # starting curriculum state
        platform = 3.
        terrain_dict = {"flat": 0.3, 
                        "rough flat": 0.2,
                        "slope up": 0.2,
                        "slope down": 0.2, 
                        "rough slope up": 0.0,
                        "rough slope down": 0.0, 
                        "stairs up": 0., 
                        "stairs down": 0.,
                        "discrete": 0.1, 
                        "wave": 0.0,}
        terrain_proportions = list(terrain_dict.values())

        rough_flat_range = [0.005, 0.01]  # meter
        slope_range = [0, 0.1]   # rad
        rough_slope_range = [0.005, 0.02]
        stair_width_range = [0.25, 0.25]
        stair_height_range = [0.01, 0.1]
        discrete_height_range = [0.0, 0.01]
        restitution = 0.

    class noise(LeggedRobotCfg.noise):
        add_noise = True
        noise_level = 1.5    # scales other values

        class noise_scales(LeggedRobotCfg.noise.noise_scales):
            dof_pos = 0.02
            dof_vel = 1.5 
            ang_vel = 0.2   
            lin_vel = 0.1   
            quat = 0.1
            gravity = 0.05
            height_measurements = 0.1


    class init_state(LeggedRobotCfg.init_state):
        pos = [0.0, 0.0, 0.7]

        default_joint_angles = {  # = target angles [rad] when action = 0.0
            # ---- 腿部（沿用 legacy exp1.5；右踝 pitch 反号：29DOF PM 轴与左踝世界轴反平行）----
            'left_hip_pitch_joint': 0.4,
            'left_hip_roll_joint': 0.05,
            'left_hip_yaw_joint': -0.31,
            'left_knee_pitch_joint': 0.49,
            'left_ankle_pitch_joint': -0.21,
            'left_ankle_roll_joint': 0.0,
            'right_hip_pitch_joint': -0.4,
            'right_hip_roll_joint': -0.05,
            'right_hip_yaw_joint': 0.31,
            'right_knee_pitch_joint': 0.49,
            'right_ankle_pitch_joint': 0.21,
            'right_ankle_roll_joint': 0.0,
            # ---- 上半身（amp CSV 均值左右对称化；符号约定回放目视校验）----
            'lumbar_yaw_joint': 0.0,
            'lumbar_roll_joint': 0.0,
            'lumbar_pitch_joint': 0.03,
            'left_shoulder_pitch_joint': 0.03,  'right_shoulder_pitch_joint': 0.03,
            'left_shoulder_roll_joint': -0.06,  'right_shoulder_roll_joint': 0.06,
            'left_shoulder_yaw_joint': 0.18,    'right_shoulder_yaw_joint': 0.18,
            # 右肩roll/右肘pitch：URDF 轴镜像但原 limit 未配套，exp0.2 修复 limit 后 default 同步镜像取反
            'left_elbow_pitch_joint': 0.34,     'right_elbow_pitch_joint': -0.34,
            'left_elbow_yaw_joint': 0.0,        'right_elbow_yaw_joint': 0.0,
            'left_wrist_pitch_joint': 0.0,      'right_wrist_pitch_joint': 0.0,
            'left_wrist_roll_joint': 0.0,       'right_wrist_roll_joint': 0.0,
        }

    class control(LeggedRobotCfg.control):
        # PD Drive parameters:
        control_type = 'P'

        stiffness = {'hip_pitch_joint': 30, 'hip_roll_joint': 40,'hip_yaw_joint': 35,
                     'knee_pitch_joint': 100, 'ankle_pitch_joint': 35, 'ankle_roll_joint': 35,
                     # exp0 29DOF 上半身（无真机辨识，量级建议值；缺键=被动悬摆）
                     'lumbar_yaw_joint': 60, 'lumbar_roll_joint': 60, 'lumbar_pitch_joint': 80,
                     'shoulder_pitch_joint': 40, 'shoulder_roll_joint': 40, 'shoulder_yaw_joint': 40,
                     'elbow_pitch_joint': 30, 'elbow_yaw_joint': 30,
                     'wrist_pitch_joint': 8, 'wrist_roll_joint': 8}
        damping = {'hip_pitch_joint': 3, 'hip_roll_joint': 3.0,'hip_yaw_joint': 4,
                   'knee_pitch_joint': 8, 'ankle_pitch_joint': 1.5, 'ankle_roll_joint': 1.5,
                   # exp0 29DOF 上半身
                   'lumbar_yaw_joint': 4, 'lumbar_roll_joint': 4, 'lumbar_pitch_joint': 5,
                   'shoulder_pitch_joint': 2, 'shoulder_roll_joint': 2, 'shoulder_yaw_joint': 2,
                   'elbow_pitch_joint': 1.5, 'elbow_yaw_joint': 1.5,
                   'wrist_pitch_joint': 0.5, 'wrist_roll_joint': 0.5}

        # action scale: target angle = actionScale * action + defaultAngle
        action_scale = 0.3  # exp0.3: 0.5→0.3 压制 bang-bang（exp0.2 des 半幅达 mocap 3-3.7 倍、corr(des,pos)≈0）
        # decimation: Number of control action updates @ sim DT per policy DT
        decimation = 10  # 50hz 100hz

        # exp1.4: 手臂/腰部(17 dof) action EMA 低通滤波系数 alpha
        # 依据 exp1.3 分布指纹：agent 手臂 dof_vel std 达 mocap 3.2~10.1 倍（右肩 roll 10.1x），
        # 腿部仅 1.8x、膝 1.0x——D 的分离面主要由手臂高频抖动支撑。
        # 位置类奖励(L2)罚不住高频小幅抖动（位置误差极小），必须频率维度手段治本。
        # 滤波: filt = alpha*prev + (1-alpha)*raw，EMA 凸组合输出不越 clip 边界
        # fc = (1-alpha)/(2*pi*alpha*dt), dt=0.01(100Hz 控制): alpha=0.85 -> fc≈2.8Hz, 群延迟≈0.057s
        # 手臂质量小不威胁平衡，0.057s 延迟可接受；alpha=1.0 关闭滤波
        # exp1.6（2026-09-09）: 0.85 -> 1.0 撤除滤波。云端 A/B 实锤（exp1.md §15.9）：
        # 同底模仅加 EMA 即加载即冻结（319 tracking 0.0006 vs 241 无 EMA 0.503）——
        # env 侧滤波在 resume 场景同时造成执行层冲击（腰部/手臂耦合反馈环断裂）
        # 与 PPO 一致性破坏（log_prob 记原始动作、env 执行滤波动作）。
        # 手臂抖动分离面若回归，改走 reward 侧（action-rate/dof_acc 惩罚）。
        arm_action_ema_alpha = 1.0

    class sim(LeggedRobotCfg.sim):
        dt = 0.001  # 200 Hz 1000 Hz
        substeps = 1  # 2
        up_axis = 1  # 0 is y, 1 is z
     
        class physx(LeggedRobotCfg.sim.physx):
            num_threads = 10
            solver_type = 1  # 0: pgs, 1: tgs
            num_position_iterations = 4
            num_velocity_iterations = 0
            contact_offset = 0.01  # [m]
            rest_offset = 0.0   # [m]
            bounce_threshold_velocity = 0.5  # 0.5 #0.5 [m/s]
            max_depenetration_velocity = 1.0
            max_gpu_contact_pairs = 2**23  # 2**24 -> needed for 8000 envs and more
            default_buffer_size_multiplier = 5
            # 0: never, 1: last sub-step, 2: all sub-steps (default=2)
            contact_collection = 2

    class domain_rand(LeggedRobotCfg.domain_rand):
        randomize_friction = True
        friction_range = [0.2, 1.3]
        restitution_range = [0.0, 0.4]

        # push
        push_robots = True
        push_interval_s = 4 # every this second, push robot
        update_step = 2000 * 24 # after this count, increase push_duration index
        push_duration = [0, 0.05, 0.1, 0.15, 0.2, 0.25] # increase push duration during training
        max_push_vel_xy = 0.2
        max_push_ang_vel = 0.2

        randomize_base_mass = True
        added_mass_range = [-3, 3] # base mass rand range, base mass is all fix link sum mass

        randomize_com = True
        com_displacement_range = [[-0.05, 0.05],
                                  [-0.05, 0.05],
                                  [-0.05, 0.05]]

        randomize_gains = True
        stiffness_multiplier_range = [0.8, 1.2]  # Factor
        damping_multiplier_range = [0.8, 1.2]    # Factor

        randomize_torque = True
        torque_multiplier_range = [0.8, 1.2]

        randomize_link_mass = True
        added_link_mass_range = [0.9, 1.1]

        randomize_motor_offset = True
        motor_offset_range = [-0.035, 0.035] # Offset to add to the motor angles
        
        randomize_joint_friction = True
        randomize_joint_friction_each_joint = False
        joint_friction_range = [0.01, 1.15]
        joint_1_friction_range = [0.01, 1.15]
        joint_2_friction_range = [0.01, 1.15]
        joint_3_friction_range = [0.01, 1.15]
        joint_4_friction_range = [0.5, 1.3]
        joint_5_friction_range = [0.5, 1.3]
        joint_6_friction_range = [0.01, 1.15]
        joint_7_friction_range = [0.01, 1.15]
        joint_8_friction_range = [0.01, 1.15]
        joint_9_friction_range = [0.5, 1.3]
        joint_10_friction_range = [0.5, 1.3]

        randomize_joint_damping = True
        randomize_joint_damping_each_joint = False
        joint_damping_range = [0.3, 1.5]
        joint_1_damping_range = [0.3, 1.5]
        joint_2_damping_range = [0.3, 1.5]
        joint_3_damping_range = [0.3, 1.5]
        joint_4_damping_range = [0.9, 1.5]
        joint_5_damping_range = [0.9, 1.5]
        joint_6_damping_range = [0.3, 1.5]
        joint_7_damping_range = [0.3, 1.5]
        joint_8_damping_range = [0.3, 1.5]
        joint_9_damping_range = [0.9, 1.5]
        joint_10_damping_range = [0.9, 1.5]

        randomize_joint_armature = True
        randomize_joint_armature_each_joint = True  # 必须开启，否则逐关节范围不生效
        joint_armature_range = [0.0001, 0.05]     # 统一回退值（each_joint=False 时使用）
        # exp0（29DOF）：Isaac Gym 实际 dof 顺序（字母序 DFS，冒烟实测打印的 [DOF] 表）：
        # 左腿(0-5)→腰(6-8)→左臂(9-15)→右臂(16-22)→右腿(23-28)，joint_N 对应 dof N-1
        # 腿部辨识值沿用 legacy exp1.5（29DOF 腿部与 12DOF physically_mirrored 同源）：
        # armature = 真机辨识J − M_ii：髋Pitch 0.196（左右对称化）、髋Yaw 0.0148/0.0060、膝 0.250/0.247
        joint_1_armature_range = [0.09, 0.23]     # dof0 L hip_pitch (id 0.196)：M_ii=0.271，左右对称化（legacy exp1.1 教训）
        joint_2_armature_range = [0.0001, 0.05]   # dof1 L hip_roll (id unreliable)
        joint_3_armature_range = [0.003, 0.018]   # dof2 L hip_yaw (id 0.0148)：M_ii=0.0309
        joint_4_armature_range = [0.18, 0.32]     # dof3 L knee (id 0.250) CORE：M_ii=0.1127
        joint_5_armature_range = [0.003, 0.04]    # dof4 L ankle_pitch: legacy exp1.4 覆盖随机化（无辨识数据，不猜中心）
        joint_6_armature_range = [0.003, 0.04]    # dof5 L ankle_roll: legacy exp1.4 同上（真机抖动关节，覆盖最关键）
        joint_7_armature_range = [0.003, 0.04]    # dof6 lumbar_yaw（无辨识，覆盖随机化）
        joint_8_armature_range = [0.003, 0.04]    # dof7 lumbar_roll
        joint_9_armature_range = [0.003, 0.04]    # dof8 lumbar_pitch
        joint_10_armature_range = [0.003, 0.04]   # dof9 L shoulder_pitch
        joint_11_armature_range = [0.003, 0.04]   # dof10 L shoulder_roll
        joint_12_armature_range = [0.003, 0.04]   # dof11 L shoulder_yaw
        joint_13_armature_range = [0.003, 0.04]   # dof12 L elbow_pitch
        joint_14_armature_range = [0.003, 0.04]   # dof13 L elbow_yaw
        joint_15_armature_range = [0.003, 0.04]   # dof14 L wrist_pitch
        joint_16_armature_range = [0.003, 0.04]   # dof15 L wrist_roll
        joint_17_armature_range = [0.003, 0.04]   # dof16 R shoulder_pitch
        joint_18_armature_range = [0.003, 0.04]   # dof17 R shoulder_roll
        joint_19_armature_range = [0.003, 0.04]   # dof18 R shoulder_yaw
        joint_20_armature_range = [0.003, 0.04]   # dof19 R elbow_pitch
        joint_21_armature_range = [0.003, 0.04]   # dof20 R elbow_yaw
        joint_22_armature_range = [0.003, 0.04]   # dof21 R wrist_pitch
        joint_23_armature_range = [0.003, 0.04]   # dof22 R wrist_roll
        joint_24_armature_range = [0.09, 0.23]    # dof23 R hip_pitch (id 0.128, symmetrized)：与左侧一致
        joint_25_armature_range = [0.0001, 0.05]  # dof24 R hip_roll (id unreliable)
        joint_26_armature_range = [0.003, 0.018]  # dof25 R hip_yaw (id 0.0060)：与左侧一致
        joint_27_armature_range = [0.18, 0.32]    # dof26 R knee (id 0.246) CORE：与左侧一致
        joint_28_armature_range = [0.003, 0.04]   # dof27 R ankle_pitch: legacy exp1.4 与左侧一致（覆盖随机化）
        joint_29_armature_range = [0.003, 0.04]   # dof28 R ankle_roll: legacy exp1.4 与左侧一致（真机抖动关节）

        add_lag = True
        randomize_lag_timesteps = True
        randomize_lag_timesteps_perstep = False
        lag_timesteps_range = [5, 40]
        
        add_dof_lag = True
        randomize_dof_lag_timesteps = True
        randomize_dof_lag_timesteps_perstep = False
        dof_lag_timesteps_range = [0, 40]
        
        add_dof_pos_vel_lag = False
        randomize_dof_pos_lag_timesteps = False
        randomize_dof_pos_lag_timesteps_perstep = False
        dof_pos_lag_timesteps_range = [7, 25]
        randomize_dof_vel_lag_timesteps = False
        randomize_dof_vel_lag_timesteps_perstep = False
        dof_vel_lag_timesteps_range = [7, 25]
        
        add_imu_lag = False
        randomize_imu_lag_timesteps = True
        randomize_imu_lag_timesteps_perstep = False
        imu_lag_timesteps_range = [1, 10]
        
        randomize_coulomb_friction = True
        joint_coulomb_range = [0.1, 0.9]
        joint_viscous_range = [0.05, 0.1]
        
    class commands(LeggedRobotCfg.commands):
        curriculum = True
        max_curriculum = 1.5
        # Vers: lin_vel_x, lin_vel_y, ang_vel_yaw, heading (in heading mode ang_vel_yaw is recomputed from heading error)
        num_commands = 4
        resampling_time = 25.  # time before command are changed[s]
        gait = ["stand","walk_omnidirectional","stand"] # gait type during training
        # exp0.3: 出生/结尾站立（原 [walk,stand,walk] 出生必行走 → "出生+cmd=0"零训练，恰是回放 S0 分布）
        # proportion during whole life time
        gait_time_range = {"walk_sagittal": [2,6],
                           "walk_lateral": [2,6],
                           "rotate": [2,3],
                           "stand": [3,5],   # exp0.3: [2,3]→[3,5] 站立段加长
                           "walk_omnidirectional": [6,9]}  # exp0.3: [4,6]→[6,9] 站立占比 ~20%→~26%

        heading_command = False  # if true: compute ang vel command from heading error
        stand_com_threshold = 0.05 # if (lin_vel_x, lin_vel_y, ang_vel_yaw).norm < this, robot should stand
        sw_switch = True # use stand_com_threshold or not

        class ranges:
            lin_vel_x = [-0.4, 1.2] # min max [m/s] 
            lin_vel_y = [-0.4, 0.4]   # min max [m/s]
            ang_vel_yaw = [-0.6, 0.6]    # min max [rad/s]
            heading = [-3.14, 3.14]

    class rewards:
        soft_dof_pos_limit = 0.98
        soft_dof_vel_limit = 0.9
        soft_torque_limit = 0.9
        base_height_target = 0.61
        foot_min_dist = 0.2
        foot_max_dist = 1.0

        # final_swing_joint_pos = final_swing_joint_delta_pos + default_pos
        # 12 元素按腿部顺序（env 的 leg_dof_names 解析索引；上半身不参与步态摆动，保持默认位姿）
        # 索引 10 = right_ankle_pitch：29DOF PM 轴 (0 0 -1) 与左踝世界轴反平行，摆幅反号（exp0 验证）
        final_swing_joint_delta_pos = [0.25, 0.05, -0.11, 0.35, -0.16, 0.0, -0.25, -0.05, 0.11, 0.35, 0.16, 0.0]
        target_feet_height = 0.03
        target_feet_height_max = 0.10  # exp1.9: 0.06→0.10 扩窗——foot_height 目标峰 0.08，
                                       # 旧上限 0.06 下"抬到位反而丢 feet_clearance 分"自相矛盾
        foot_height_target = 0.08      # exp1.9: 摆动相足高钟形目标峰值（A·|sin|，A 即此值）
        feet_to_ankle_distance = 0.041
        foot_place_sigma = 0.15        # exp1.12: 落点锚容差——|foot_x_fwd - tgt| 的 exp 核尺度（§20 快测校准）
        cycle_time = 0.7
        # ---- exp1.13: 相位钟的双支撑窗（§13.4b/§13.4c 实证）----
        # 钟上双支撑占比 = 2·asin(k)/π：k=0.1 → 6.38%，k=0.25 → 16.09%（过渡相位容差 58ms vs 147ms）
        # ⚠️ exp2.0 撤销回 0.1：exp1.13 加宽到 0.25 后，多环境预算表实测**回退**——
        #   提前终止率 12.8%→15.2%、姿态线终止 31→69（2.2x）、行走段后仰 −0.161→−0.190；
        #   决定性命中对照（exp1.12 模型 + 新代码）逐项复现旧基线 → k 只作用于奖励、
        #   不进入回放动力学，两轮差异全在策略侧。撤销后 exp2.0 相对 exp1.12 基线
        #   只差"新增躯干俯仰约束"这一个自变量（详见 czy/exp1/exp2.md §1 / §3 修改一）。
        # 历史护栏：上限 0.30（DS≤19.4%）防"贴地吸引子"（exp1.7/1.8 的老对手）。
        double_support_k = 0.1

        # ---- exp1.7: 速度自适应步频（劈叉滑行根治，§17）----
        # 机理：固定周期下指令速度越高步幅需求越大（0.6 m/s@4.78s 需 1.43 m/步，物理不可达）
        # → 策略弃跟拍滑行（exp1.6 回放：左右髋 corr +0.47 同相、feet_air_time 0.0015）。
        # 改法：cycle_eff = T_seg × clamp(v_demo/v_cmd)，保持 demo 步幅几何、节奏随指令缩放。
        gait_speed_adaptive = True
        gait_scale_clamp = [0.5, 1.6]   # scale 上下限：防极端步频（0.5≈2 倍速播放，1.6≈慢放）
        # 跑步机段 root 静止（实测速度 0），用体检表值兜底；yz/turn 真实地面按 root 位移实测
        seg_demo_speed_table = {"walk_norm": 1.23, "walk_slow": 0.10}

        # ---- Phase 2: mocap 参考轨迹（2b：全身查同一段轨迹，腿臂同帧推进天然同拍；False=2a 回退）----
        # 段周期来自 ref_lib.pt（walk_norm 1.143s / walk_turn 1.242s / walk_slow 1.484s），
        # use_mocap_ref=True 时行走 env 的 _get_phase 逐 env 用所在段周期，cycle_time 仅站立/回退时生效
        use_mocap_ref = True
        mocap_full_body = True    # 全身查表（决策 2026-09-03：跳过 2a 直接 2b，见 plan.md §4.2）
        mocap_ref_file = '{LEGGED_GYM_ROOT_DIR}/resources/motions/processed/ref_lib.pt'
        # if true negative total rewards are clipped at zero (avoids early termination problems)
        only_positive_rewards = True
        # tracking reward = exp(-error^2*sigma)
        tracking_sigma = 20  # exp1: 5→20 锐化——exp0.3 实测 cmd=0.4/v=0 踏步仍得 exp(-0.4²·5)=45% tracking 分；
        # σ=20 后同条件 exp(-0.4²·20)=exp(-3.2)=0.04，踏步白拿漏洞堵死（配合 low_speed too-slow -2 与 scale 1.0）
        max_contact_force = 700  # forces above this value are penalized

        # ---- exp2.0: 躯干俯仰（"持续后仰"）约束参数（详见 czy/exp1/exp2.md §3 修改二）----
        # 立项依据（多环境预算表 512env×3ep 实测，exp1.12 底模）：
        #   ① 行走段 pitch 均值 −0.177，**99.9% 的行走 episode 为后仰**（81% 强后仰 < −0.15）；
        #   ② 起步姿态仅 −0.056（近乎直立），但段末比段首再后仰 ≈0.20 rad → 后仰是**过程累积**；
        #   ③ 失稳主链 = 后仰 → 重心后移 → 反向迈步/摔倒；行走段终止中"后仰+反向"占 42%，
        #      pitch>0.8 组 100% 后仰且 100% 反向（vx_end −1.81 m/s）。
        # pitch 符号：asin(2(qw·qy − qz·qx))，绕 +y 轴 → **正=前倾、负=后仰**。
        # 用 EMA 低通量而非瞬时量：正常步态每步有 ≈0.05 rad 俯仰摆动，瞬时惩罚会误伤步态节律；
        # 低通后只保留"持续后仰"这一实测签名。pitch 的瞬时分量已由 `orientation` 覆盖（不动它）。
        # α 取 0.99（τ≈1.0s）而非 0.95（τ≈0.19s）：实测行走段 pitch 频谱能量分布为
        #   <0.1Hz 14.8% / 0.1–0.3Hz 33.0%（慢漂移=要保留）/ 0.3–0.5Hz 17.7% /
        #   0.5–1Hz 21.8% / 1–2Hz 8.4%（步态摆动=要滤掉）/ >2Hz 4.3%
        # 一阶 EMA 抑制比：α=0.95 在 0.5Hz 仅 0.85、1Hz 0.63 → **几乎不衰减，等于没低通**；
        # α=0.99 在 0.1Hz 为 0.85（漂移保留）、0.5Hz 0.31、1Hz 0.16（步态被压掉 70~84%），
        # 且对 0.03 rad/s 的漂移仅滞后 0.03 rad（可忽略）。α=0.995/0.999 已开始吃掉 0.1–0.3Hz
        # 的漂移带（时滞 0.06/0.30 rad）→ 过慢。
        pitch_lpf_alpha = 0.99     # EMA 系数 → τ≈1.0s @100Hz（由实测频谱定，非拍脑袋）
        pitch_target = 0.0         # 目标躯干俯仰（直立；可调为小前倾 +0.02）
        # σ 取 8 而非 20：本核是 |d| 形式（非 tracking 的 ‖e‖² 形式），σ=20 会在 d≈0.15 处
        # 就衰减到 0.05、d≈0.25 处梯度只剩 0.13/rad —— 而基线后仰恰落在 0.15~0.25 区间，
        # 等于**在唯一需要的区间饱和**。σ=8 → d=0.15/0.25 的梯度仍为 1.94/1.08 /rad；
        # 远端（d>0.3）由线性底接续，不依赖指数项。
        pitch_sigma = 8
        pitch_lin_coef = 0.2       # 线性底系数 [/rad]——**必需**，见 env 侧 _reward_torso_pitch_lpf
        pitch_lin_cap = 0.5        # 线性底截断 [rad]（同 _reward_ref_joint_pos 的 clamp(0,0.5)）
        
        class scales:
            # exp0.2: 2.2→1.8，上半身从常数变动态 mocap 目标，先降压防摆臂跟踪压制步态
            # exp0.3: 1.8→2.4 压幅度后参考可实现（des≈±0.6-0.9 vs mocap±0.45），升压让查表参考主导
            # exp1: 2.4→0.0 归零（用户拍板）——逐关节 L2 只管形态不管平移，恰给踏步发奖；
            # 风格监督移交 AMP 判别器（保留则踏步白拿漏洞仍在且与 style 双重计分打架）
            # exp1.3: 0→0.5 半值恢复——exp1.2 实测 AMP 标量 style 太粗保不住姿态（迁移期步态崩解），
            # 恢复半值作逐关节密集锚；不回 2.4 全值（避免重新主导、与 style 双重计分）
            ref_joint_pos = 0.5
            feet_clearance = 1.
            feet_contact_number = 2.0
            # gait
            feet_air_time = 1.5   # exp1.7: 1.2→1.5 加压抬腿（exp1.6 全程 0.0015，腿抬不起来是劈叉滑行的直接表现）
            # ---- exp1.8: 髋交替步态双锚（§18，死区/反向激励修复）----
            swing_air = 1.0       # 新增：摆动相离地逐步奖励——相位说该摆的脚真实离地即得分（无落地事件、无死区），
                                  # 直接教"相位-抬脚"耦合；站立 phase=0 落双支撑天然 0 分
            hip_ref = 1.0         # 新增：左右髋 pitch 对查表 ref 专项跟踪——交替波形 2 维直锚，
                                  # 不受 ref_joint_pos 29 维范数稀释（exp1.7 全身跟踪仅 0.18）
            # ---- exp1.9: yz 参考修复后的幅度激励（§19）----
            foot_height = 1.0     # 新增：摆动相足高对相位钟形目标（A·|sin|，A=foot_height_target=0.08）
                                  # 的连续跟踪 exp(-|h-tgt|/0.04)——攻 tap 试探（exp1.8 swing_air 二值
                                  # 奖励下"离地 1~2cm 即赚"，终值 0.219/2.0≈11%）；双支撑窗目标
                                  # 天然≈0，站立锁 1.0 不误伤
            # ---- exp1.12: 落点锚（§20）----
            foot_place = 1.0      # 新增：摆动腿落点对目标 root_x + 0.75·v_cmd·T/2 的连续跟踪
                                  # exp(-|Δ|/foot_place_sigma)——步幅按指令缩放（节奏+步幅双自由度），
                                  # 治"稳态速度饱和 ~0.5"（cycle_eff 只缩节奏，参考几何步幅 0.62m 固定）；
                                  # 落点进支撑多边形兼是防摔稳定器（exp1.11 修正：8~10s/摔为第一瓶颈）
            foot_slip = -0.25     # exp1.7: -0.1→-0.25 加压（滑行=脚在地面拖，触地脚水平速度惩罚翻倍以上；再升有滑步硬惩罚风险，见 §17 止损）
            feet_distance = 0.2   # exp0.3: 0.3→0.2 回退（exp0.2 证实带来 vx 过冲副作用，收益不明显）
            knee_distance = 0.2
            feet_contact_number = 2.4  # legacy exp1.3: 2.0→2.4 强化左右步节拍对称（治偏航离散累积）
            # lateral
            lat_vel = -2.0        # legacy exp1.1: -1.2->-2.0 加压（exp1 净漂 -0.10/-0.12 未压住）
            yaw_drift = -1.2      # exp1.7: -0.8→-1.2 加压（exp1.6 回放 0.6 m/s 段 yaw 累积漂移；步频自适应后漂移源应减弱，此为兜底）
            # contact 
            feet_contact_forces = -0.01
            # vel tracking
            tracking_lin_vel = 2.2  # legacy exp1.3: 1.8→2.2 提升跟踪优先级
            tracking_ang_vel = 1.1
            vel_mismatch_exp = 0.5  # lin_z; ang x,y
            low_speed = 2.0  # exp1: 0.2→1.0 配合 tracking σ 锐化与 too-slow -2 罚，踏步净收益转负
                            # exp1.3: 1.0→2.0——too_slow -2×2.0=-4 > 行走 env 站立正收益 ~3.4（姿态类+ang tracking+style 工资），
                            # 冻结净额触 only_positive_rewards 0 钳位，行走明确胜出（exp1.2 冻结核算，exp1.md §13）
            track_vel_hard = 0.5
            # base pos
            default_joint_pos = 1.0
            orientation = 1.2     # legacy exp1.1: 1.0->1.2 微调（-y 漂伴随左倾，roll 姿态保持协同纠偏）
            # ---- exp2.0: 躯干俯仰"持续分量"专项约束（新增；orientation 保持不动）----
            # 权重取与步态类同量级（foot_place 1.0 / foot_height 1.0 / stand_still 3.5 / feet_air_time 1.5），
            # 但仍低于它们——目的是"纠正偏置"而非主导步态，避免 exp1.2 那种量纲淹没/反客为主。
            # ⚠️ exp2.1 归零（纯减法方案）：exp2.0 云端 3000 轮验收 ❌ 未达标——
            #   提前终止率 12.8%→21.3%、姿态终止 31→89（其中 88% 为后仰）、pitch>0.8 由 19→76（4x），
            #   而 walk_pitch_mean 仅 −0.177→−0.149 → **均值改善、重尾恶化**；
            #   三代同协议对比显示"两极分化"：健康组 speed_ratio 0.64→0.66→0.70 逐代↑、
            #   而 pitch 终止组 0.46→0.33→0.27 逐代↓ → 问题是鲁棒性方差退化，非缺约束。
            # 归零而非删除：保留实现以便后续复用（本仓惯例，同 exp1 的 ref_joint_pos 2.4→0.0）；
            # 归零后 _prepare_reward_function 整项移除，_pitch_lpf 状态仍更新但不进梯度（无害）。
            # exp2.1 目的：确立"仅撤销 k 0.25→0.1"这一纯减法配置的长程稳定性基线。
            torso_pitch_lpf = 0.0
            feet_rotation = 0.3
            base_height = 0.2
            base_acc = 0.2
            # energy
            action_smoothness = -0.02  # exp0.3: -0.008→-0.02 压 bang-bang（含 |a| L1 + 一/二阶差分）；legacy exp1.4 曾 -0.002→-0.008 压真机踝振荡
            torques = -8e-9
            dof_vel = -2e-8
            dof_acc = -1e-7
            collision = -1.
            stand_still = 3.5  # exp0.3: 2.5→3.5 加强站立吸引子（仅 stand_command 时非零，不伤行走）
            # limits
            dof_vel_limits = -1
            dof_pos_limits = -10.
            dof_torque_limits = -0.1

    # ---- exp1: AMP 判别器（env 侧开关；算法侧超参见 X1DHStandCfgPPO.algorithm 的 amp_* 平铺键）----
    class amp:
        enabled = True      # 总开关：False → env 不产 extras["amp"]，DHPPOAMP 自动退化为纯 task 基线（消融用）
        disc_obs_steps = 3  # 判别器时间窗（控制步），与 algorithm.amp_disc_obs_steps 保持一致
        demo_file = ''      # 空 → resources/motions/processed/ref_lib.pt（与 use_mocap_ref 同源）
        # exp1.6: demo 段抽样权重（multinomial），顺序 = sorted 段名（walk_norm, walk_slow, walk_turn, walk_yz）。
        # yz 加倍：ref 路由已前进全指 walk_yz（0.255 m/s 真实地面行走），D 侧同步加重防止
        # "ref 教 yz、style 评跑步机慢步" 的通道分裂；slow 减半（0.1 m/s 极慢步占比原 39%）。
        # 空列表 = 均匀抽样（旧行为）
        demo_seg_weights = [1.0, 0.5, 1.0, 2.0]

    class normalization:
        class obs_scales:
            lin_vel = 2.
            ang_vel = 1.
            dof_pos = 1.
            dof_vel = 0.05
            quat = 1.
            height_measurements = 5.0
        clip_observations = 100.
        clip_actions = 3.  # exp0.3: 100→3 env.step 入口硬界原始 action（des 偏移上限 3×0.3=±0.9 rad）


class X1DHStandCfgPPO(LeggedRobotCfgPPO):
    seed = 5
    runner_class_name = 'DHOnPolicyRunner'   # DWLOnPolicyRunner

    class policy:
        init_noise_std = 1.0
        actor_hidden_dims = [512, 256, 128]
        critic_hidden_dims = [768, 256, 128]
        state_estimator_hidden_dims=[256, 128, 64]
        
        #for long_history cnn only
        kernel_size=[6, 4]
        filter_size=[32, 16]
        stride_size=[3, 2]
        lh_output_dim= 64   #long history output dim
        in_channels = X1DHStandCfg.env.frame_stack

    class algorithm(LeggedRobotCfgPPO.algorithm):
        entropy_coef = 0.001
        learning_rate = 1e-5
        num_learning_epochs = 2
        gamma = 0.994
        lam = 0.9
        num_mini_batches = 4
        if X1DHStandCfg.terrain.measure_heights:
            lin_vel_idx = (X1DHStandCfg.env.single_num_privileged_obs + X1DHStandCfg.terrain.num_height) * (X1DHStandCfg.env.c_frame_stack - 1) + X1DHStandCfg.env.single_linvel_index
        else:
            lin_vel_idx = X1DHStandCfg.env.single_num_privileged_obs * (X1DHStandCfg.env.c_frame_stack - 1) + X1DHStandCfg.env.single_linvel_index

        # ---- exp1: AMP 判别器超参（FLAT 平铺键——class_to_dict 后作为 kwargs 直传 DHPPOAMP，
        # 嵌套 class 会变 dict 导致 **kwargs 展开类型不符）。数值照抄 robolab X1 实测（29DOF 同构）----
        amp_enabled = True              # 与 env cfg amp.enabled 双闸，任一 False 即纯 task
        amp_disc_obs_steps = 3          # 判别器时间窗：183 = 3 × 61（61 = ang3+dof_pos29+dof_vel29）
        amp_disc_hidden_dims = [1024, 512]
        amp_disc_lr = 5e-5              # exp1.1: 1e-4→5e-5——exp1 判别器 86 iter 碾压饱和死锁，降速给 policy 追赶窗口（配合 demo 侧混静立窗）
        amp_grad_penalty_scale = 10.0   # 梯度惩罚只加 demo 侧（AMP 论文标准）
        amp_disc_buffer_size = 100      # 滑窗控制步 > rollout 窗 24，跨迭代混合防 stale
        amp_style_reward_scale = 100   # exp1.2: 1.5→100——量纲修正：dt(0.01)×1.5=0.015 上限 vs task O(6)/步，
                                       # style 梯度弱 60 倍被淹没（exp1/exp1.1 style 无影响力的隐藏根因）。
                                       # 100 → 上限 1.0/步，梯度 0.5·(1-D)·1.0 与 task O(1) 同量级；
                                       # 乘 dt 保留（控制频率解耦）。robolab task O(0.8) 无此问题
                                       # 本地对照（64env×60iter）：ep_len/reward 与 1.5 完全一致（无破坏），style 0.001→0.055
        amp_task_lerp = 0.6             # 融合 = 0.6·task + 0.4·style（站立 env 纯 task 不融合）
        # exp1.5: style 负斜坡下界——rew = max(1-(D-1)²/4, eps·(D+1))。D∈(-1,1) 与旧公式
        # 逐点一致（量纲零扰动）；D<-1 旧 clamp 平顶梯度为 0（D 过冲时 policy 失联），
        # 负斜坡保证任何 D 值梯度不断流且越负越罚。定位：保险丝（exp1.3 死锁值 -0.994
        # 在梯度区，rew≈0.006 是淹没级非零级，主攻是 buffer 门控 + D 重置）
        amp_style_floor_eps = 0.05
        # exp1.5 主攻：agent buffer 三重门控——healthy = 行走(~stand) & 未终止(~done) &
        # episode_length>50(0.5s)。剥掉 D 的平凡可分样本（exp1.3 死锁头号嫌疑：gait 26%
        # 站立段样本 vs 100% 行走 demo，"速度幅度"一维秒分；另防 terminal 摔倒态与
        # 复位静止态送分题）。-1=关闭门控（旧行为）
        amp_buffer_min_episode_len = 50
        amp_disc_trunk_weight_decay = 1e-3
        amp_disc_linear_weight_decay = 1e-1
        amp_disc_max_grad_norm = 1.0

    class runner:
        policy_class_name = 'ActorCriticDH'
        algorithm_class_name = 'DHPPOAMP'  # exp1: DHPPO→DHPPOAMP（runner eval 字符串注入，判别器随算法进训练流）
        num_steps_per_env = 24  # per iteration
        max_iterations = 6000  # number of policy updates

        # logging
        save_interval = 100  # check for potential saves every this many iterations
        experiment_name = 'x1_dh_stand'
        run_name = ''
        # load and resume
        resume = False
        load_run = -1  # -1 = last run
        checkpoint = -1  # -1 = last saved model
        resume_path = None  # updated from load_run and chkpt
