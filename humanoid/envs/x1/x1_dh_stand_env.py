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

from humanoid.envs.base.legged_robot_config import LeggedRobotCfg

from isaacgym.torch_utils import *
from isaacgym import gymtorch, gymapi
from humanoid.utils.math import wrap_to_pi


import torch
from humanoid.envs import LeggedRobot

from humanoid.utils.terrain import  Terrain

def copysign_new(a, b):

    a = torch.tensor(a, device=b.device, dtype=torch.float)
    a = a.expand_as(b)
    return torch.abs(a) * torch.sign(b)

def get_euler_rpy(q):
    qx, qy, qz, qw = 0, 1, 2, 3
    # roll (x-axis rotation)
    sinr_cosp = 2.0 * (q[..., qw] * q[..., qx] + q[..., qy] * q[..., qz])
    cosr_cosp = q[..., qw] * q[..., qw] - q[..., qx] * \
        q[..., qx] - q[..., qy] * q[..., qy] + q[..., qz] * q[..., qz]
    roll = torch.atan2(sinr_cosp, cosr_cosp)

    # pitch (y-axis rotation)
    sinp = 2.0 * (q[..., qw] * q[..., qy] - q[..., qz] * q[..., qx])
    pitch = torch.where(torch.abs(sinp) >= 1, copysign_new(
        np.pi / 2.0, sinp), torch.asin(sinp))

    # yaw (z-axis rotation)
    siny_cosp = 2.0 * (q[..., qw] * q[..., qz] + q[..., qx] * q[..., qy])
    cosy_cosp = q[..., qw] * q[..., qw] + q[..., qx] * \
        q[..., qx] - q[..., qy] * q[..., qy] - q[..., qz] * q[..., qz]
    yaw = torch.atan2(siny_cosp, cosy_cosp)

    return roll % (2*np.pi), pitch % (2*np.pi), yaw % (2*np.pi)

def get_euler_xyz_tensor(quat):
    r, p, w = get_euler_rpy(quat)
    # stack r, p, w in dim1
    euler_xyz = torch.stack((r, p, w), dim=-1)
    euler_xyz[euler_xyz > np.pi] -= 2 * np.pi
    return euler_xyz

class X1DHStandEnv(LeggedRobot):
    '''
    X1DHStandEnv is a class that represents a custom environment for a legged robot.

    Args:
        cfg (LeggedRobotCfg): Configuration object for the legged robot.
        sim_params: Parameters for the simulation.
        physics_engine: Physics engine used in the simulation.
        sim_device: Device used for the simulation.
        headless: Flag indicating whether the simulation should be run in headless mode.

    Attributes:
        last_feet_z (float): The z-coordinate of the last feet position.
        feet_height (torch.Tensor): Tensor representing the height of the feet.
        sim (gymtorch.GymSim): The simulation object.
        terrain (Terrain): The terrain object.
        up_axis_idx (int): The index representing the up axis.
        command_input (torch.Tensor): Tensor representing the command input.
        privileged_obs_buf (torch.Tensor): Tensor representing the privileged observations buffer.
        obs_buf (torch.Tensor): Tensor representing the observations buffer.
        obs_history (collections.deque): Deque containing the history of observations.
        critic_history (collections.deque): Deque containing the history of critic observations.

    Methods:
        _push_robots(): Randomly pushes the robots by setting a randomized base velocity.
        _get_phase(): Calculates the phase of the gait cycle.
        _get_stance_mask(): Calculates the gait phase.
        compute_ref_state(): Computes the reference state.
        create_sim(): Creates the simulation, terrain, and environments.
        _get_noise_scale_vec(cfg): Sets a vector used to scale the noise added to the observations.
        step(actions): Performs a simulation step with the given actions.
        compute_observations(): Computes the observations.
        reset_idx(env_ids): Resets the environment for the specified environment IDs.
    '''
    def __init__(self, cfg: LeggedRobotCfg, sim_params, physics_engine, sim_device, headless):
        super().__init__(cfg, sim_params, physics_engine, sim_device, headless)
        self.last_feet_z = self.cfg.rewards.feet_to_ankle_distance
        self.feet_height = torch.zeros((self.num_envs, 2), device=self.device)
        self.ref_dof_pos = torch.zeros((self.num_envs, self.num_actions), device=self.device)      


    def _push_robots(self):
        """ Random pushes the robots. Emulates an impulse by setting a randomized base velocity. 
        """
        max_vel = self.cfg.domain_rand.max_push_vel_xy
        max_push_angular = self.cfg.domain_rand.max_push_ang_vel
        self.rand_push_force[:, :2] = torch_rand_float(
            -max_vel, max_vel, (self.num_envs, 2), device=self.device)  # lin vel x/y
        self.root_states[:, 7:9] = self.rand_push_force[:, :2]

        self.rand_push_torque = torch_rand_float(
            -max_push_angular, max_push_angular, (self.num_envs, 3), device=self.device)  #angular vel xyz

        self.root_states[:, 10:13] = self.rand_push_torque
        self.gym.set_actor_root_state_tensor(
            self.sim, gymtorch.unwrap_tensor(self.root_states))

    def  _get_phase(self):
        cycle_time = self.cfg.rewards.cycle_time
        if self.cfg.commands.sw_switch:
            stand_command = (torch.norm(self.commands[:, :3], dim=1) <= self.cfg.commands.stand_com_threshold)
            self.phase_length_buf[stand_command] = 0 # set this as 0 for which env is standing
            # self.gait_start is rand 0 or 0.5
            # Phase2: 行走 env 的周期逐 env 取所在参考段的 gait_period（mocap 步频），站立/回退用全局 cycle_time
            if getattr(self, "use_mocap_ref", False):
                self.seg_id = self._current_seg_id()   # 每次按当前指令即时算（_get_phase 会先于 compute_ref_state 被调用）
                if getattr(self.cfg.rewards, "gait_speed_adaptive", False):
                    # exp1.7: 相位改为持久积分量（_post_physics_step_callback 推进），周期随指令
                    # 自适应缩放时段切换/缩放变化相位天然连续（只变速不变跳）；本函数纯读，幂等
                    phase = self._gait_phase * (~stand_command)
                    return phase
                cycle_time = torch.full_like(self.phase_length_buf, cycle_time, dtype=torch.float)
                # 相位周期（秒）= 段周期帧数 / 库帧率（如 57帧/50Hz = 1.143s）
                cycle_time[~stand_command] = \
                    self.seg_period_frames[self.seg_id][~stand_command].float() / self.seg_fps[self.seg_id][~stand_command]
            phase = (self.phase_length_buf * self.dt / cycle_time + self.gait_start) * (~stand_command)
        else:
            phase = self.episode_length_buf * self.dt / cycle_time + self.gait_start

        # phase continue increase，if want robot stand, set 0
        return phase

    def _current_seg_id(self):
        """指令 → 参考段索引（向量化）。exp1.7: 多段路由恢复（exp1.6 曾全指 yz）

        路由：|wz|>0.15→walk_turn（优先，转向可伴随前进）；其余按 |vx| 分桶：
        |vx|<0.15→walk_slow，0.15≤|vx|<0.8→walk_yz，|vx|≥0.8→walk_norm。
        exp1.6 教训：全段指 yz 时 0.4/0.6 m/s 指令下固定 4.78s 周期步幅需求
        0.95/1.43 m/步物理不可达 → 策略弃跟拍滑行。exp1.7 配合自适应步频
        （_current_cycle_time）恢复低速段兜底与高速段覆盖。
        """
        wz = self.commands[:, 2]
        vx = self.commands[:, 0]
        turn = self.seg_names.index("walk_turn")
        slow = self.seg_names.index("walk_slow")
        yz = self.seg_names.index("walk_yz")
        norm = self.seg_names.index("walk_norm")
        seg_id = torch.full_like(self.phase_length_buf, yz)
        no_turn = torch.abs(wz) <= 0.15
        seg_id[no_turn & (torch.abs(vx) >= 0.8)] = norm
        seg_id[no_turn & (torch.abs(vx) < 0.15)] = slow
        seg_id[~no_turn] = turn
        return seg_id

    def _current_cycle_time(self):
        """per-env 有效步态周期（秒）。exp1.7: cycle_eff = T_seg × clamp(v_demo/v_cmd, lo, hi)

        机理：保持 demo 步幅几何（查表轨迹不变），仅按指令/参考速度比缩放节奏——
        v_cmd > v_demo → scale<1 步频加快；v_cmd < v_demo → scale>1 慢放。
        turn 段不缩放（原地/绕圈转向 demo 本身按原速播放）。stand env 的返回值
        无意义（相位被 stand_command 掩蔽），v_cmd 下限 1e-3 仅防零除。
        """
        seg_cycle = self.seg_period_frames[self.seg_id].float() / self.seg_fps[self.seg_id]
        if not getattr(self.cfg.rewards, "gait_speed_adaptive", False):
            return seg_cycle
        lo, hi = self.cfg.rewards.gait_scale_clamp
        v_demo = self.seg_demo_speed[self.seg_id]
        v_cmd = torch.clamp(self.commands[:, 0].abs(), min=1e-3)
        scale = torch.clamp(v_demo / v_cmd, lo, hi)
        is_turn = self.seg_id == self.seg_names.index("walk_turn")
        scale = torch.where(is_turn, torch.ones_like(scale), scale)
        return seg_cycle * scale

    def _get_stance_mask(self):
        # return float mask 1 is stance, 0 is swing
        phase = self._get_phase()
        sin_pos = torch.sin(2 * torch.pi * phase)
        
        stance_mask = torch.zeros((self.num_envs, 2), device=self.device)
        # left foot stance
        stance_mask[:, 0] = sin_pos >= 0
        # right foot stance
        stance_mask[:, 1] = sin_pos < 0
        # Add double support phase
        # exp1.13: 窗口半宽改由 cfg.rewards.double_support_k 驱动（旧值硬编码 0.1 = 钟上 DS 仅 6.38%）。
        # 钟上双支撑占比 = 2·asin(k)/π；该值同时决定 feet_contact_number 的 +1 可得时窗、
        # swing_air/feet_clearance 的摆动窗与 base_height 的支撑脚判据。
        stance_mask[torch.abs(sin_pos) < self.cfg.rewards.double_support_k] = 1

        # stand mask == 1 means stand leg 
        return stance_mask

    def generate_gait_time(self,envs):
        if len(envs) == 0:
            return

        # rand sample 
        random_tensor_list = []
        for i in range(len(self.cfg.commands.gait)):
            name = self.cfg.commands.gait[i]
            gait_time_range = self.cfg.commands.gait_time_range[name]
            random_tensor_single = torch_rand_float(gait_time_range[0],
                                            gait_time_range[1],
                                            (len(envs), 1),device=self.device)
            random_tensor_list.append(random_tensor_single)

        random_tensor = torch.cat([random_tensor_list[i] for i in range(len(self.cfg.commands.gait))], dim=1)
        current_sum = torch.sum(random_tensor,dim=1,keepdim=True)
        # scaled_tensor store proportion for each gait type
        scaled_tensor = random_tensor * (self.max_episode_length / current_sum)
        scaled_tensor[:,1:] = scaled_tensor[:,:-1].clone()
        scaled_tensor[:,0] *= 0.0
        # self.gait_time accumulate gait_duration_tick
        # self.gait_time = |__gait1__|__gait2__|__gait3__|
        # self.gait_time triger resample gait command
        self.gait_time[envs] = torch.cumsum(scaled_tensor,dim=1).int()

    def check_termination(self):
        """exp1.12: 收紧 termination——roll/pitch 0.8rad + h<0.45 双条件（§20）。

        base 判据 1.5rad=86° 过松：趴地扑腾段（pitch 30~75°、h~0.1m）大量进入
        训练分布污染 PPO/AMP 样本（exp1.11 修正：训练 episode ~10.9s 即摔终止）。
        提前止损让学习集中在"不摔"分布上；非脚触地力>1N 判据保留（趴地兜底）。
        """
        self.reset_buf = torch.any(
            torch.norm(self.contact_forces[:, self.termination_contact_indices, :], dim=-1) > 1., dim=1)
        self.time_out_buf = self.episode_length_buf > self.max_episode_length
        self.reset_buf |= self.time_out_buf
        self.reset_buf |= torch.abs(self.base_euler_xyz[:, 0]) > self.cfg.termination.roll_pitch_cutoff
        self.reset_buf |= torch.abs(self.base_euler_xyz[:, 1]) > self.cfg.termination.roll_pitch_cutoff
        self.reset_buf |= self.root_states[:, 2] < self.cfg.termination.base_height_cutoff

    def _resample_commands(self):
        """ Randommly select commands of some environments

        Args:
            env_ids (List[int]): Environments ids for which new commands are needed
        """
        for i in range(len(self.cfg.commands.gait)):
            # if env finish current gait type, resample command for next gait
            env_ids = (self.episode_length_buf == self.gait_time[:,i]).nonzero(as_tuple=False).flatten()
            if len(env_ids) > 0:
                # according to gait type create a name
                name = '_resample_' + self.cfg.commands.gait[i] + '_command'
                # get function from self based on name
                resample_command = getattr(self, name)
                # resample_command stands for _resample_stand_command/_resample_walk_sagittal_command/...
                resample_command(env_ids)

    def _resample_stand_command(self, env_ids):
        self.commands[env_ids, 0] = torch.zeros(len(env_ids), device=self.device)
        self.commands[env_ids, 1] = torch.zeros(len(env_ids), device=self.device)
        if self.cfg.commands.heading_command:
            self.commands[env_ids, 3] = torch.zeros(len(env_ids), device=self.device)
        else:
            self.commands[env_ids, 2] = torch.zeros(len(env_ids), device=self.device)
            
    def _resample_walk_sagittal_command(self, env_ids):
        self.commands[env_ids, 0] = torch_rand_float(self.command_ranges["lin_vel_x"][0], self.command_ranges["lin_vel_x"][1], (len(env_ids), 1), device=self.device).squeeze(1)
        self.commands[env_ids, 1] = torch.zeros(len(env_ids), device=self.device)
        if self.cfg.commands.heading_command:
            self.commands[env_ids, 3] = torch.zeros(len(env_ids), device=self.device)
        else:
            self.commands[env_ids, 2] = torch.zeros(len(env_ids), device=self.device)

    def _resample_walk_lateral_command(self, env_ids):
        self.commands[env_ids, 0] = torch.zeros(len(env_ids), device=self.device)
        self.commands[env_ids, 1] = torch_rand_float(self.command_ranges["lin_vel_y"][0], self.command_ranges["lin_vel_y"][1], (len(env_ids), 1), device=self.device).squeeze(1)
        if self.cfg.commands.heading_command:
            self.commands[env_ids, 3] = torch.zeros(len(env_ids), device=self.device)
        else:
            self.commands[env_ids, 2] = torch.zeros(len(env_ids), device=self.device)
    
    def _resample_rotate_command(self, env_ids):
        self.commands[env_ids, 0] = torch.zeros(len(env_ids), device=self.device)
        self.commands[env_ids, 1] = torch.zeros(len(env_ids), device=self.device)
        if self.cfg.commands.heading_command:
            self.commands[env_ids, 3] = torch_rand_float(self.command_ranges["heading"][0], self.command_ranges["heading"][1], (len(env_ids), 1), device=self.device).squeeze(1)
        else:
            self.commands[env_ids, 2] = torch_rand_float(self.command_ranges["ang_vel_yaw"][0], self.command_ranges["ang_vel_yaw"][1], (len(env_ids), 1), device=self.device).squeeze(1)

    def _resample_walk_omnidirectional_command(self,env_ids):
        self.commands[env_ids, 0] = torch_rand_float(self.command_ranges["lin_vel_x"][0], self.command_ranges["lin_vel_x"][1], (len(env_ids), 1), device=self.device).squeeze(1)
        self.commands[env_ids, 1] = torch_rand_float(self.command_ranges["lin_vel_y"][0], self.command_ranges["lin_vel_y"][1], (len(env_ids), 1), device=self.device).squeeze(1)
        if self.cfg.commands.heading_command:
            self.commands[env_ids, 3] = torch_rand_float(self.command_ranges["heading"][0], self.command_ranges["heading"][1], (len(env_ids), 1), device=self.device).squeeze(1)
        else:
            self.commands[env_ids, 2] = torch_rand_float(self.command_ranges["ang_vel_yaw"][0], self.command_ranges["ang_vel_yaw"][1], (len(env_ids), 1), device=self.device).squeeze(1)
        # self.commands[env_ids, :2] *= (torch.norm(self.commands[env_ids, :2], dim=1) > 0.05).unsqueeze(1)
        
    def _post_physics_step_callback(self):
        """ Callback called before computing terminations, rewards, and observations
            Default behaviour: Compute ang vel command based on target and heading, compute measured terrain heights and randomly push robots
        """
        self.phase_length_buf += 1
        # ---- exp1.7: 相位积分推进（自适应步频路径，§17）----
        # _get_phase 每步被多处调用必须幂等，推进只能放这里（每物理步恰一次）。
        # 段切换/指令重采样只改变推进速率 cycle_eff，相位本身连续不跳变。
        if getattr(self, "use_mocap_ref", False) and getattr(self.cfg.rewards, "gait_speed_adaptive", False):
            self.seg_id = self._current_seg_id()
            cycle_eff = self._current_cycle_time()
            stand_command = (torch.norm(self.commands[:, :3], dim=1) <= self.cfg.commands.stand_com_threshold)
            walk = ~stand_command
            resumed = walk & (self._gait_phase == 0)   # 刚从站立恢复（或初始）：从随机半周期起点开始
            self._gait_phase = torch.where(resumed, self.gait_start.float(), self._gait_phase)
            self._gait_phase = torch.where(
                walk, self._gait_phase + self.dt / cycle_eff, torch.zeros_like(self._gait_phase))
        self._resample_commands()
        if self.cfg.commands.heading_command:
            forward = quat_apply(self.base_quat, self.forward_vec)
            heading = torch.atan2(forward[:, 1], forward[:, 0])
            self.commands[:, 2] = torch.clip(0.5*wrap_to_pi(self.commands[:, 3] - heading), -1., 1.)

        if self.cfg.terrain.measure_heights:
            # get all robot surrounding height
            self.measured_heights = self._get_heights()

        if self.cfg.domain_rand.push_robots:
            i = int(self.common_step_counter/self.cfg.domain_rand.update_step)
            if i >= len(self.cfg.domain_rand.push_duration):
                i = len(self.cfg.domain_rand.push_duration) - 1
            duration = self.cfg.domain_rand.push_duration[i]/self.dt
            if self.common_step_counter % self.cfg.domain_rand.push_interval <= duration:
                self._push_robots()
            else:
                self.rand_push_force.zero_()
                self.rand_push_torque.zero_()

    def compute_ref_state(self):
        phase = self._get_phase()
        sin_pos = torch.sin(2 * torch.pi * phase)
        sin_pos_l = sin_pos.clone()
        sin_pos_r = sin_pos.clone()

        self.ref_dof_pos = torch.zeros_like(self.dof_pos)
        # left swing（腿部 dof 索引按名解析；上半身 dof 保持 0，+= default 后即默认位姿）
        sin_pos_l[sin_pos_l > 0] = 0
        self.ref_dof_pos[:, self.leg_dof_indices[:6]] = \
            -sin_pos_l.unsqueeze(1) * self.swing_delta_left
        # right
        sin_pos_r[sin_pos_r < 0] = 0
        self.ref_dof_pos[:, self.leg_dof_indices[6:]] = \
            sin_pos_r.unsqueeze(1) * self.swing_delta_right

        self.ref_dof_pos[torch.abs(sin_pos) < 0.1] = 0.

        # ---- Phase 2a/2b: mocap 查表（行走 env 按相位取所在段帧；站立 env 不覆盖，锁默认）----
        if getattr(self, "use_mocap_ref", False):
            stand_command = (torch.norm(self.commands[:, :3], dim=1) <= self.cfg.commands.stand_com_threshold)
            walk = ~stand_command
            if walk.any():
                self.seg_id = self._current_seg_id()
                # 相位 → 段内帧（锚点对齐 stance 语义；段长取模循环）
                frames = phase[walk] * self.seg_period_frames[self.seg_id[walk]].float() \
                    + self.seg_anchor[self.seg_id[walk]].float()
                frames = torch.remainder(frames.long(), self.seg_len[self.seg_id[walk]])
                q_ref = self.mocap_q[frames, self.seg_id[walk]]        # (N_walk, 29) 绝对角
                if self.mocap_full_body:   # 2b：全身查表
                    self.ref_dof_pos[walk] = q_ref
                else:                      # 2a：只覆盖上半身，腿部保留正弦
                    tmp = self.ref_dof_pos[walk]
                    tmp[:, self.upper_dof_indices] = q_ref[:, self.upper_dof_indices]
                    self.ref_dof_pos[walk] = tmp

        # if use_ref_actions=True, action += ref_action
        # Phase2: ref_dof_pos 含 mocap 绝对角，ref_action 须为相对默认的增量
        self.ref_action = 2 * (self.ref_dof_pos - self.default_dof_pos)

        # self.ref_dof_pos set ref dof pos for swing leg, ref_dof_pos=0 for stance leg
        self.ref_dof_pos += self.default_dof_pos


    def create_sim(self):
        """ Creates simulation, terrain and evironments
        """
        self.up_axis_idx = 2  # 2 for z, 1 for y -> adapt gravity accordingly
        self.sim = self.gym.create_sim(
            self.sim_device_id, self.graphics_device_id, self.physics_engine, self.sim_params)
        mesh_type = self.cfg.terrain.mesh_type
        if mesh_type in ['heightfield', 'trimesh']:
            self.terrain = Terrain(self.cfg.terrain, self.num_envs)

        if mesh_type == 'plane':
            self._create_ground_plane()
        elif mesh_type == 'heightfield':
            self._create_heightfield()
        elif mesh_type == 'trimesh':
            self._create_trimesh()
        elif mesh_type is not None:
            raise ValueError(
                "Terrain mesh type not recognised. Allowed types are [None, plane, heightfield, trimesh]")
        self._create_envs()


    def _get_noise_scale_vec(self, cfg):
        """ Sets a vector used to scale the noise added to the observations.
            [NOTE]: Must be adapted when changing the observations structure

        Args:
            cfg (Dict): Environment config file

        Returns:
            [torch.Tensor]: Vector of scales used to multiply a uniform distribution in [-1, 1]
        """
        noise_vec = torch.zeros(
            self.cfg.env.num_single_obs, device=self.device)
        self.add_noise = self.cfg.noise.add_noise
        noise_scales = self.cfg.noise.noise_scales
        noise_vec[0: self.cfg.env.num_commands] = 0.  # commands
        noise_vec[self.cfg.env.num_commands: self.cfg.env.num_commands+self.num_actions] = noise_scales.dof_pos * self.obs_scales.dof_pos
        noise_vec[self.cfg.env.num_commands+self.num_actions: self.cfg.env.num_commands+2*self.num_actions] = noise_scales.dof_vel * self.obs_scales.dof_vel
        noise_vec[self.cfg.env.num_commands+2*self.num_actions: self.cfg.env.num_commands+3*self.num_actions] = 0.  # previous actions
        noise_vec[self.cfg.env.num_commands+3*self.num_actions: self.cfg.env.num_commands+3*self.num_actions + 3] = noise_scales.ang_vel * self.obs_scales.ang_vel   # ang vel
        noise_vec[self.cfg.env.num_commands+3*self.num_actions + 3: self.cfg.env.num_commands+3*self.num_actions + 6] = noise_scales.quat * self.obs_scales.quat         # euler x,y
        return noise_vec



    def step(self, actions):
        if self.cfg.env.use_ref_actions:
            actions += self.ref_action
        # exp1.4: 手臂/腰部 EMA 低通滤波——物理消除高频抖动，真实移动 agent 分布
        # （治本路线：改变生成侧，而非缩 D 容量让 D 变笨）。EMA 凸组合输出不越
        # [-clip,clip]，滤波后值经 super().step() 的 clip 进 self.actions，obs 的
        # last_action 与实际执行一致。alpha=1.0 时退化为直通。
        alpha = self.cfg.control.arm_action_ema_alpha
        if alpha < 1.0:
            filt = self._arm_action_filt * alpha + actions[:, self.arm_dof_indices] * (1 - alpha)
            actions[:, self.arm_dof_indices] = filt
            self._arm_action_filt = filt.clone()
        return super().step(actions)

    def compute_observations(self):

        phase = self._get_phase()
        self.compute_ref_state()

        sin_pos = torch.sin(2 * torch.pi * phase).unsqueeze(1)
        cos_pos = torch.cos(2 * torch.pi * phase).unsqueeze(1)

        stance_mask = self._get_stance_mask()
        contact_mask = self.contact_forces[:, self.feet_indices, 2] > 5.

        self.command_input = torch.cat(
            (sin_pos, cos_pos, self.commands[:, :3] * self.commands_scale), dim=1)
        
        # critic no lag
        diff = self.dof_pos - self.ref_dof_pos
        # 73
        privileged_obs_buf = torch.cat((
            self.command_input,  # 2 + 3
            (self.dof_pos - self.default_joint_pd_target) * self.obs_scales.dof_pos,  # 12
            self.dof_vel * self.obs_scales.dof_vel,  # 12
            self.actions,  # 12
            diff,  # 12
            self.base_lin_vel * self.obs_scales.lin_vel,  # 3
            self.base_ang_vel * self.obs_scales.ang_vel,  # 3
            self.base_euler_xyz * self.obs_scales.quat,  # 3
            self.rand_push_force[:, :2],  # 2
            self.rand_push_torque,  # 3
            self.env_frictions,  # 1
            self.body_mass / 10.,  # 1 # sum of all fix link mass
            stance_mask,  # 2
            contact_mask,  # 2
        ), dim=-1)
        
        # random add dof_pos and dof_vel same lag
        if self.cfg.domain_rand.add_dof_lag:
            if self.cfg.domain_rand.randomize_dof_lag_timesteps_perstep:
                self.dof_lag_timestep = torch.randint(self.cfg.domain_rand.dof_lag_timesteps_range[0], 
                                                  self.cfg.domain_rand.dof_lag_timesteps_range[1]+1,(self.num_envs,),device=self.device)
                cond = self.dof_lag_timestep > self.last_dof_lag_timestep + 1
                self.dof_lag_timestep[cond] = self.last_dof_lag_timestep[cond] + 1
                self.last_dof_lag_timestep = self.dof_lag_timestep.clone()
            self.lagged_dof_pos = self.dof_lag_buffer[torch.arange(self.num_envs), :self.num_actions, self.dof_lag_timestep.long()]
            self.lagged_dof_vel = self.dof_lag_buffer[torch.arange(self.num_envs), -self.num_actions:, self.dof_lag_timestep.long()]  
        # random add dof_pos and dof_vel different lag
        elif self.cfg.domain_rand.add_dof_pos_vel_lag:
            if self.cfg.domain_rand.randomize_dof_pos_lag_timesteps_perstep:
                self.dof_pos_lag_timestep = torch.randint(self.cfg.domain_rand.dof_pos_lag_timesteps_range[0], 
                                                  self.cfg.domain_rand.dof_pos_lag_timesteps_range[1]+1,(self.num_envs,),device=self.device)
                cond = self.dof_pos_lag_timestep > self.last_dof_pos_lag_timestep + 1
                self.dof_pos_lag_timestep[cond] = self.last_dof_pos_lag_timestep[cond] + 1
                self.last_dof_pos_lag_timestep = self.dof_pos_lag_timestep.clone()
            self.lagged_dof_pos = self.dof_pos_lag_buffer[torch.arange(self.num_envs), :, self.dof_pos_lag_timestep.long()]
                
            if self.cfg.domain_rand.randomize_dof_vel_lag_timesteps_perstep:
                self.dof_vel_lag_timestep = torch.randint(self.cfg.domain_rand.dof_vel_lag_timesteps_range[0], 
                                                  self.cfg.domain_rand.dof_vel_lag_timesteps_range[1]+1,(self.num_envs,),device=self.device)
                cond = self.dof_vel_lag_timestep > self.last_dof_vel_lag_timestep + 1
                self.dof_vel_lag_timestep[cond] = self.last_dof_vel_lag_timestep[cond] + 1
                self.last_dof_vel_lag_timestep = self.dof_vel_lag_timestep.clone()
            self.lagged_dof_vel = self.dof_vel_lag_buffer[torch.arange(self.num_envs), :, self.dof_vel_lag_timestep.long()]
        # dof_pos and dof_vel has no lag
        else:
            self.lagged_dof_pos = self.dof_pos
            self.lagged_dof_vel = self.dof_vel

        # imu lag, including rpy and omega
        if self.cfg.domain_rand.add_imu_lag:    
            if self.cfg.domain_rand.randomize_imu_lag_timesteps_perstep:
                self.imu_lag_timestep = torch.randint(self.cfg.domain_rand.imu_lag_timesteps_range[0], 
                                                  self.cfg.domain_rand.imu_lag_timesteps_range[1]+1,(self.num_envs,),device=self.device)
                cond = self.imu_lag_timestep > self.last_imu_lag_timestep + 1
                self.imu_lag_timestep[cond] = self.last_imu_lag_timestep[cond] + 1
                self.last_imu_lag_timestep = self.imu_lag_timestep.clone()
            self.lagged_imu = self.imu_lag_buffer[torch.arange(self.num_envs), :, self.imu_lag_timestep.int()]
            self.lagged_base_ang_vel = self.lagged_imu[:,:3].clone()
            self.lagged_base_euler_xyz = self.lagged_imu[:,-3:].clone()
        # no imu lag
        else:              
            self.lagged_base_ang_vel = self.base_ang_vel[:,:3]
            self.lagged_base_euler_xyz = self.base_euler_xyz[:,-3:]
        
        # obs q and dq
        q = (self.lagged_dof_pos - self.default_dof_pos) * self.obs_scales.dof_pos
        dq = self.lagged_dof_vel * self.obs_scales.dof_vel  

        # 47
        obs_buf = torch.cat((
            self.command_input,  # 5 = 2D(sin cos) + 3D(vel_x, vel_y, aug_vel_yaw)
            q,    # 12
            dq,  # 12
            self.actions,   # 12
            self.lagged_base_ang_vel * self.obs_scales.ang_vel,  # 3
            self.lagged_base_euler_xyz * self.obs_scales.quat,  # 3
        ), dim=-1)

        if self.cfg.env.num_single_obs == 48:
            stand_command = (torch.norm(self.commands[:, :3], dim=1, keepdim=True) <= self.cfg.commands.stand_com_threshold)
            obs_buf = torch.cat((obs_buf, stand_command),dim=1)
            
        if self.cfg.terrain.measure_heights:
            heights = torch.clip(self.root_states[:, 2].unsqueeze(1) - 0.5 - self.measured_heights, -1, 1.) * self.obs_scales.height_measurements
            privileged_obs_buf = torch.cat((privileged_obs_buf.clone(), heights), dim=-1)
        
        if self.add_noise:  
            # add obs noise
            obs_now = obs_buf.clone() + (2 * torch.rand_like(obs_buf) -1) * self.noise_scale_vec * self.cfg.noise.noise_level
        else:
            obs_now = obs_buf.clone()

        self.obs_history.append(obs_now)
        self.critic_history.append(privileged_obs_buf)

        obs_buf_all = torch.stack([self.obs_history[i]
                                   for i in range(self.obs_history.maxlen)], dim=1)  # N,T,K

        self.obs_buf = obs_buf_all.reshape(self.num_envs, -1)  # N, T*K
        self.privileged_obs_buf = torch.cat([self.critic_history[i] for i in range(self.cfg.env.c_frame_stack)], dim=1)

    def reset_idx(self, env_ids):
        """ Reset some environments.
            Calls self._reset_dofs(env_ids), self._reset_root_states(env_ids), and self._resample_commands(env_ids)
            [Optional] calls self._update_terrain_curriculum(env_ids), self.update_command_curriculum(env_ids) and
            Logs episode info
            Resets some buffers

        Args:
            env_ids (list[int]): List of environment ids which must be reset
        """
        if len(env_ids) == 0:
            return
        # update curriculum
        if self.cfg.terrain.curriculum:
            self._update_terrain_curriculum(env_ids)
        # avoid updating command curriculum at each step since the maximum command is common to all envs
        if self.cfg.commands.curriculum and (self.common_step_counter % self.max_episode_length==0):
            self.update_command_curriculum(env_ids)
        
        # reset rand dof_pos and dof_vel=0
        self._reset_dofs(env_ids)

        # reset base position
        self._reset_root_states(env_ids)
        
        # Randomize joint parameters, like torque gain friction ...
        self.randomize_dof_props(env_ids)
        self._refresh_actor_dof_props(env_ids)
        self.randomize_lag_props(env_ids)
        
        # reset buffers
        self.last_last_actions[env_ids] = 0.
        self.actions[env_ids] = 0.
        self.last_actions[env_ids] = 0.
        self.last_rigid_state[env_ids] = 0.
        self.last_dof_vel[env_ids] = 0.
        self.last_root_vel[env_ids] = 0.
        self.feet_air_time[env_ids] = 0.
        self.episode_length_buf[env_ids] = 0
        self.phase_length_buf[env_ids] = 0
        self._gait_phase[env_ids] = 0.   # exp1.7: 相位积分复位（恢复行走时由 resumed 逻辑取 gait_start）
        self.reset_buf[env_ids] = 1
        # exp1.4: 手臂 EMA 滤波状态复位（默认位=0，与 actions[env_ids]=0 对齐）
        self._arm_action_filt[env_ids] = 0.
        # rand 0 or 0.5
        self.gait_start[env_ids] = torch.randint(0, 2, (len(env_ids),)).to(self.device)*0.5
        
        #resample command
        self.generate_gait_time(env_ids)
        self._resample_commands()
        
        # fill extras
        self.extras["episode"] = {}
        for key in self.episode_sums.keys():
            self.extras["episode"]['rew_' + key] = torch.mean(self.episode_sums[key][env_ids]) / self.max_episode_length_s
            self.episode_sums[key][env_ids] = 0.
        # log additional curriculum info
        if self.cfg.terrain.mesh_type == "trimesh":
            self.extras["episode"]["terrain_level"] = torch.mean(self.terrain_levels.float())
        if self.cfg.commands.curriculum:
            self.extras["episode"]["max_command_x"] = self.command_ranges["lin_vel_x"][1]
        # send timeout info to the algorithm
        if self.cfg.env.send_timeouts:
            self.extras["time_outs"] = self.time_out_buf
            
        # fix reset gravity bug
        self.gym.refresh_actor_root_state_tensor(self.sim)
        self.gym.refresh_net_contact_force_tensor(self.sim)
        self.gym.refresh_rigid_body_state_tensor(self.sim)
        
        self.base_quat[env_ids] = self.root_states[env_ids, 3:7]
        self.base_euler_xyz = get_euler_xyz_tensor(self.base_quat)
        self.projected_gravity[env_ids] = quat_rotate_inverse(self.base_quat[env_ids], self.gravity_vec[env_ids])
        self.base_lin_vel[env_ids] = quat_rotate_inverse(self.base_quat[env_ids], self.root_states[env_ids, 7:10])
        self.base_ang_vel[env_ids] = quat_rotate_inverse(self.base_quat[env_ids], self.root_states[env_ids, 10:13])
        self.feet_quat = self.rigid_state[:, self.feet_indices, 3:7]
        self.feet_euler_xyz = get_euler_xyz_tensor(self.feet_quat)
        
        # clear obs history buffer and privileged obs buffer
        for i in range(self.obs_history.maxlen):
            self.obs_history[i][env_ids] *= 0
        for i in range(self.critic_history.maxlen):
            self.critic_history[i][env_ids] *= 0

        # exp1: AMP 历史整窗待填充（下一步 _sample_amp 用复位后状态覆盖，防旧 episode 样本污染）
        if getattr(self, "amp_enabled", False):
            self._amp_hist_fill[env_ids] = True

        # exp2.0: 躯干俯仰 EMA 复位为**复位后的当前姿态**（勿置 0——否则上一 episode 的后仰
        # 会在新 episode 开头被"记着"，产生跨 episode 泄漏）；base_euler_xyz 已在上方刷新
        self._pitch_lpf[env_ids] = self.base_euler_xyz[env_ids, 1]
        
    
    def _init_buffers(self):
        """ Initialize torch tensors which will contain simulation states and processed quantities
        """
        super()._init_buffers()
        self.gait_time = torch.zeros(self.num_envs, len(self.cfg.commands.gait) ,dtype=torch.int, device=self.device, requires_grad=False)
        self.phase_length_buf = torch.zeros(
            self.num_envs, device=self.device, dtype=torch.long)
        self.gait_start = torch.randint(0, 2, (self.num_envs,)).to(self.device)*0.5
        self._gait_phase = torch.zeros(self.num_envs, device=self.device)  # exp1.7: 相位积分（自适应步频路径）
        # exp2.0: "持续后仰"约束的 EMA 状态（低通后的躯干俯仰，见 _reward_torso_pitch_lpf）
        self._pitch_lpf = torch.zeros(self.num_envs, device=self.device)

        # 29DOF 支持：腿部 dof 索引按关节名解析，不依赖 URDF 关节顺序
        # （12DOF URDF 下解析结果即 0-11，行为与旧硬编码完全等价）
        self.leg_dof_names = [
            'left_hip_pitch_joint', 'left_hip_roll_joint', 'left_hip_yaw_joint',
            'left_knee_pitch_joint', 'left_ankle_pitch_joint', 'left_ankle_roll_joint',
            'right_hip_pitch_joint', 'right_hip_roll_joint', 'right_hip_yaw_joint',
            'right_knee_pitch_joint', 'right_ankle_pitch_joint', 'right_ankle_roll_joint',
        ]
        missing = [n for n in self.leg_dof_names if n not in self.dof_names]
        assert not missing, "URDF 缺少腿部关节: {}".format(missing)
        self.leg_dof_indices = torch.tensor(
            [self.dof_names.index(n) for n in self.leg_dof_names],
            dtype=torch.long, device=self.device)
        # final_swing_joint_delta_pos 按 leg_dof_names 顺序解释（前 6 左腿，后 6 右腿）
        swing = torch.tensor(self.cfg.rewards.final_swing_joint_delta_pos,
                             dtype=torch.float, device=self.device)
        assert swing.numel() == 12, "final_swing_joint_delta_pos 须为 12 元素（按腿部顺序）"
        self.swing_delta_left = swing[:6]
        self.swing_delta_right = swing[6:]
        # 打印 dof 索引表，供 config 逐关节参数（armature 等）人工核对
        print("[DOF] " + ", ".join("{}:{}".format(i, n) for i, n in enumerate(self.dof_names)))

        # ---- exp1.4: 手臂/腰部 action EMA 低通滤波 ----
        # ref_joint_pos 降为半值(0.5)后手臂缺任务老师，成噪声海绵：PPO noise_std 全关节共享
        # + 腿部梯度耦合 → 高频抖动（dof_vel std 达 mocap 3.2~10.1 倍），D 分离面主成分。
        # 索引按关节名解析（lumbar×3 + shoulder/elbow/wrist×14 = 17），硬断言拦截 URDF 变更
        self.arm_dof_indices = torch.tensor(
            [i for i, n in enumerate(self.dof_names)
             if any(k in n for k in ('lumbar', 'shoulder', 'elbow', 'wrist'))],
            dtype=torch.long, device=self.device)
        assert len(self.arm_dof_indices) == 17, \
            "arm dof 解析出 {} 个（期望 17）: {}".format(
                len(self.arm_dof_indices),
                [self.dof_names[i] for i in self.arm_dof_indices.tolist()])
        self._arm_action_filt = torch.zeros(
            self.num_envs, len(self.arm_dof_indices), device=self.device)
        if self.cfg.control.arm_action_ema_alpha < 1.0:
            print("[EMA] arm/lumbar EMA alpha={}, fc≈{:.1f}Hz, dofs={}".format(
                self.cfg.control.arm_action_ema_alpha,
                (1 - self.cfg.control.arm_action_ema_alpha) /
                (2 * torch.pi * self.cfg.control.arm_action_ema_alpha * self.dt),
                self.arm_dof_indices.tolist()))
        else:
            print("[EMA] DISABLED (alpha=1.0, exp1.6 撤除——env 侧滤波 resume 冲击+PPO 一致性破坏)")

        # ---- Phase 2: mocap 参考轨迹库（2a：上半身查表）----
        self.use_mocap_ref = getattr(self.cfg.rewards, "use_mocap_ref", False)
        self.mocap_full_body = getattr(self.cfg.rewards, "mocap_full_body", False)
        if self.use_mocap_ref:
            self._init_mocap_lib()

        # ---- exp1: AMP 判别器特征管线（demo 预计算 + 每步采样，独立于 use_mocap_ref）----
        amp_cfg = getattr(self.cfg, "amp", None)
        self.amp_enabled = bool(getattr(amp_cfg, "enabled", False))
        if self.amp_enabled:
            self._init_amp(amp_cfg)

    def _init_mocap_lib(self):
        """加载 ref_lib.pt（prep_mocap_ref.py 产物），按段建查表结构"""
        import os
        path = self.cfg.rewards.mocap_ref_file.format(LEGGED_GYM_ROOT_DIR=self.cfg.commands.__class__.__module__ and os.environ.get("LEGGED_GYM_ROOT_DIR", ""))
        # 兜底：config 路径里的占位符按仓库根展开
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
        if "{LEGGED_GYM_ROOT_DIR}" in path or not os.path.isfile(path):
            path = os.path.join(root, "resources/motions/processed/ref_lib.pt")
        lib = torch.load(path, map_location=self.device)
        assert list(lib["walk_norm"]["dof_names"]) == list(self.dof_names), \
            "ref_lib dof_names 与 env 不一致，请重跑 prep_mocap_ref.py"

        self.seg_names = sorted(lib.keys())
        self.upper_dof_indices = torch.tensor(
            [i for i, n in enumerate(self.dof_names)
             if "hip" not in n and "knee" not in n and "ankle" not in n],
            dtype=torch.long, device=self.device)
        # 统一张量：q(T_max, num_seg, 29) 便于按段 gather；period_frames/anchor/len 每段一个值
        T_max = max(lib[s]["dof_pos"].shape[0] for s in self.seg_names)
        num_seg = len(self.seg_names)
        q_all = torch.zeros(T_max, num_seg, len(self.dof_names), device=self.device)
        # 周期帧数按【库帧率 fps】换算（与 anchor/查表索引同单位），
        # 不能用 policy dt：mocap_q 是 50Hz 帧，用 0.01s 换算会 2 倍速播放
        self.seg_period_frames = torch.zeros(num_seg, dtype=torch.long, device=self.device)
        self.seg_fps = torch.zeros(num_seg, dtype=torch.float, device=self.device)
        self.seg_anchor = torch.zeros(num_seg, dtype=torch.long, device=self.device)
        self.seg_len = torch.zeros(num_seg, dtype=torch.long, device=self.device)
        for k, s in enumerate(self.seg_names):
            q = lib[s]["dof_pos"]                       # (T,29) float32 gym 序
            self.seg_len[k] = q.shape[0]
            self.seg_fps[k] = float(lib[s].get("fps", 50))
            self.seg_period_frames[k] = int(round(lib[s]["gait_period"] * float(lib[s].get("fps", 50))))
            self.seg_anchor[k] = int(lib[s]["phase_anchor_frame"])
            q_all[:q.shape[0], k] = q
        self.mocap_q = q_all
        print("[MOCP] 段: " + ", ".join(
            "{}(T={},P={},A={})".format(s, int(self.seg_len[k]), int(self.seg_period_frames[k]),
                                        int(self.seg_anchor[k]))
            for k, s in enumerate(self.seg_names)))

        # ---- exp1.7: 段参考速度（§17 自适应步频）----
        # 真实地面段（yz/turn）按 root 水平轨迹路径长实测；跑步机段（norm/slow）root 静止
        # （皮带抵消位移，实测≈0），用 config 体检表值兜底。
        self.seg_demo_speed = torch.zeros(num_seg, dtype=torch.float, device=self.device)
        speed_table = getattr(self.cfg.rewards, "seg_demo_speed_table", {}) or {}
        for k, s in enumerate(self.seg_names):
            root_xy = lib[s]["root_pos"][:, :2]              # (T,2) 水平轨迹
            Tk = int(self.seg_len[k])
            path_len = torch.norm(root_xy[1:] - root_xy[:-1], dim=1).sum() if Tk > 1 else 0.
            v_meas = float(path_len) * float(self.seg_fps[k]) / max(Tk, 1)  # 路径长×fps/帧数 = m/s
            v_cfg = float(speed_table.get(s, 0.))
            # 表值>0 且实测远小于表值（<50%）→ 判定跑步机静止，用表值；否则实测优先
            self.seg_demo_speed[k] = v_meas if (v_cfg <= 0 or v_meas > 0.5 * v_cfg) else v_cfg
        if getattr(self.cfg.rewards, "gait_speed_adaptive", False):
            print("[GAIT] 自适应步频 ON, clamp={}, 段参考速度: {}".format(
                tuple(self.cfg.rewards.gait_scale_clamp),
                {s: round(float(self.seg_demo_speed[k]), 3) for k, s in enumerate(self.seg_names)}))
        else:
            print("[GAIT] 自适应步频 OFF（固定段周期）")

    # ================= exp1: AMP 判别器特征管线 =================
    def _init_amp(self, amp_cfg):
        """加载 ref_lib.pt 预计算 demo 特征 (T_max, num_seg, 61)：
        61 = root_ang_vel(3, 体轴) + dof_pos(29, 绝对角) + dof_vel(29)
        速度不存盘加载现算（robolab 惯例）：dof_vel 前向差分、root_ang_vel 四元数差分精确 log 映射
        """
        import os
        path = getattr(amp_cfg, "demo_file", "")
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
        if (not path) or "{LEGGED_GYM_ROOT_DIR}" in path or not os.path.isfile(path):
            path = os.path.join(root, "resources/motions/processed/ref_lib.pt")
        lib = torch.load(path, map_location=self.device)

        self.amp_disc_steps = int(getattr(amp_cfg, "disc_obs_steps", 3))
        feat_dim = 3 + 2 * self.num_dof
        self.amp_feat_dim = feat_dim

        seg_names = sorted(lib.keys())
        # 启动硬断言：demo dof 顺序与 env 一致（notes §4-4，拦截两侧特征错位）
        for s in seg_names:
            assert list(lib[s]["dof_names"]) == list(self.dof_names), \
                "AMP ref_lib 段 {} dof_names 与 env 不一致，请重跑 prep_mocap_ref.py".format(s)

        num_seg = len(seg_names)
        T_max = max(lib[s]["dof_pos"].shape[0] for s in seg_names)
        demo_feat = torch.zeros(T_max, num_seg, feat_dim, device=self.device)
        seg_len = torch.zeros(num_seg, dtype=torch.long, device=self.device)
        seg_stride = torch.zeros(num_seg, dtype=torch.long, device=self.device)

        # exp1.6: demo 段抽样权重（multinomial；空 = 均匀旧行为）。顺序 = sorted 段名
        w = list(getattr(amp_cfg, "demo_seg_weights", []) or [])
        if w:
            assert len(w) == num_seg, \
                "amp.demo_seg_weights 长度 {} != 段数 {}（段序: {}）".format(len(w), num_seg, seg_names)
            self._amp_seg_weights = torch.tensor(w, dtype=torch.float, device=self.device)
        else:
            self._amp_seg_weights = torch.ones(num_seg, dtype=torch.float, device=self.device)
        print("[AMP] demo 段权重: {}（段序 {}）".format(w if w else "均匀", seg_names))

        for k, s in enumerate(seg_names):
            q = lib[s]["dof_pos"].float().to(self.device)   # (T,29) 绝对角
            fps = float(lib[s].get("fps", 50))
            T = q.shape[0]
            seg_len[k] = T
            # demo 窗口步进（库帧）：控制 dt × 库帧率；不足 1 帧时取 1（agent 侧隔步采样补偿时间尺度）
            seg_stride[k] = max(1, round(self.dt * fps))

            # dof_vel 前向差分，末帧沿用
            dq = torch.zeros_like(q)
            dq[:-1] = (q[1:] - q[:-1]) * fps
            dq[-1] = dq[-2]

            # root_ang_vel（体轴）：q_rel = q_t^{-1} ⊗ q_{t+1}，精确 log 映射 ×fps，末帧沿用
            rot = lib[s]["root_rot_wxyz"].float().to(self.device)  # (T,4) wxyz
            quat = rot[:, [1, 2, 3, 0]]                             # → xyzw
            quat = quat / quat.norm(dim=-1, keepdim=True).clamp(min=1e-8)
            conj = torch.cat([-quat[:-1, :3], quat[:-1, 3:4]], dim=-1)
            ax, ay, az, aw = conj[:, 0], conj[:, 1], conj[:, 2], conj[:, 3]
            bx, by, bz, bw = quat[1:, 0], quat[1:, 1], quat[1:, 2], quat[1:, 3]
            q_rel = torch.stack([
                aw * bx + ax * bw + ay * bz - az * by,
                aw * by - ax * bz + ay * bw + az * bx,
                aw * bz + ax * by - ay * bx + az * bw,
                aw * bw - ax * bx - ay * by - az * bz,
            ], dim=-1)                                              # (T-1,4) 体轴相对旋转
            vec = q_rel[:, :3]
            n = vec.norm(dim=-1).clamp(min=1e-8)
            angle = 2.0 * torch.atan2(n, q_rel[:, 3])
            ang = torch.zeros(T, 3, device=self.device)
            ang[:-1] = vec / n.unsqueeze(-1) * (angle * fps).unsqueeze(-1)
            ang[-1] = ang[-2]

            demo_feat[:T, k, 0:3] = ang
            demo_feat[:T, k, 3:3 + self.num_dof] = q
            demo_feat[:T, k, 3 + self.num_dof:] = dq

        self._amp_demo_feat = demo_feat
        self._amp_seg_len = seg_len
        self._amp_seg_stride = seg_stride
        self._amp_num_seg = num_seg

        # agent 侧隔步采样：控制 dt × 库帧率 < 1 时，agent 窗口每 agent_stride 步滚动一次，
        # 使两侧窗口真实时间跨度对齐（如 dt=0.01/fps=50：demo 3 帧=0.04s，agent 每 2 步取点=0.04s）
        ref_fps = float(lib[seg_names[0]].get("fps", 50))
        frames_per_step = self.dt * ref_fps
        self._amp_agent_stride = max(1, round(1.0 / frames_per_step)) if frames_per_step > 0 else 1
        self._amp_step_ctr = 0

        # agent 侧 3 步环形历史；出生/复位后整窗填当前态（防 reset 前样本污染，notes §4-7）
        self._amp_hist = torch.zeros(self.num_envs, self.amp_disc_steps, feat_dim, device=self.device)
        self._amp_hist_fill = torch.ones(self.num_envs, dtype=torch.bool, device=self.device)
        print("[AMP] demo 库 {} 段，特征 {} 维 × {} 步窗，dt {:.4f}，demo_stride {}，"
              "agent_stride {}（窗口跨度 {:.3f}s vs demo {:.3f}s）".format(
                  num_seg, feat_dim, self.amp_disc_steps, self.dt,
                  seg_stride.tolist(), self._amp_agent_stride,
                  (self.amp_disc_steps - 1) * self._amp_agent_stride * self.dt,
                  (self.amp_disc_steps - 1) * seg_stride[0].item() / ref_fps))

    def post_physics_step(self):
        """exp1: AMP 特征在 super 之前采样（即 reset_idx 之前）——
        本步特征属于刚执行完的动作（commands 尚未被 callback 重采，站立判定准确）；
        死亡 env 的 terminal 状态也是合法 agent 样本；复位历史整窗填充见 _amp_hist_fill
        """
        if getattr(self, "amp_enabled", False):
            self._sample_amp()
        super().post_physics_step()

    def _sample_amp(self):
        self.gym.refresh_actor_root_state_tensor(self.sim)
        base_quat = self.root_states[:, 3:7]
        ang = quat_rotate_inverse(base_quat, self.root_states[:, 10:13])
        feat = torch.cat([ang, self.dof_pos, self.dof_vel], dim=1)   # (N,61)

        # 隔步滚动历史（与 demo 帧距时间尺度对齐，见 _init_amp；滚动步 clone 防重叠切片自赋值）
        self._amp_step_ctr += 1
        if self._amp_step_ctr % self._amp_agent_stride == 0:
            self._amp_hist[:, :-1] = self._amp_hist[:, 1:].clone()
            self._amp_hist[:, -1] = feat
        fill = self._amp_hist_fill
        if fill.any():
            self._amp_hist[fill] = feat[fill].unsqueeze(1).expand(-1, self.amp_disc_steps, -1)
            self._amp_hist_fill[fill] = False

        stand = torch.norm(self.commands[:, :3], dim=1) <= self.cfg.commands.stand_com_threshold
        # exp1.3: stand_ratio 固定 0——exp1.1/1.2 的静立窗混合被 D 学成"静立= demo"，
        # 行走 env 站立也能吃 style 工资，是 exp1.2 行走能力被拆的根因之一（exp1.md §13）。
        # 站立技能由 task 侧负责（stand_still + 站立指令满额 tracking，style 被 stand_mask 屏蔽）
        demo = self._sample_amp_demo(stand_ratio=0.0)
        self.extras["amp"] = {
            "disc_obs": self._amp_hist,        # (N,S,61) 原始特征
            "disc_demo_obs": demo,             # (N,S,61)
            "stand_mask": stand,               # (N,) bool
            # exp1.5: buffer 门控第三条件——复位初期（episode_length 小）样本不入 D
            "episode_length": self.episode_length_buf,  # (N,)
        }

    def _sample_amp_demo(self, stand_ratio=0.0):
        """每步每 env 随机抽（段, 起始帧）取 S 步窗——与相位解耦的纯风格匹配（random_fetch 风格）

        exp1.1: 以当前 agent 站立占比 stand_ratio 混入静立窗（随机帧 q_t 重复 S 次，ang/dq=0）——
        两侧静立分布逐批对齐，堵判别器"运动幅度"平凡特征（exp1 死锁根因，见 exp1.md §8）。
        融合不受影响：站立 env 的 style 仍被 stand_mask 屏蔽，风格信号只作用于行走 env。
        """
        N = self.num_envs
        # exp1.6: 按段权重抽样（multinomial 自动归一；空权重时为均匀，与旧 randint 等价）
        seg = torch.multinomial(self._amp_seg_weights, N, replacement=True)
        stride = self._amp_seg_stride[seg]
        max_start = (self._amp_seg_len[seg] - (self.amp_disc_steps - 1) * stride - 1).clamp(min=0)
        start = (torch.rand(N, device=self.device) * (max_start + 1).float()).long()
        frames = torch.stack(
            [start + j * stride for j in range(self.amp_disc_steps)], dim=1)   # (N,S)
        seg_idx = seg.unsqueeze(1).expand(-1, self.amp_disc_steps)
        demo = self._amp_demo_feat[frames, seg_idx]                            # (N,S,61)

        if stand_ratio > 0.0:
            # 静立窗：default_dof_pos 位形重复 S 次，速度/角速度置 0
            # exp1.1 曾用 mocap 随机帧 q_t——与 agent 站立位形不同，D 照样一票分类（exp1.md §10 归因）
            still = torch.zeros_like(demo)
            still[:, :, 3:3 + self.num_dof] = self.default_dof_pos.view(1, 1, -1)
            mix = torch.rand(N, device=self.device) < stand_ratio
            demo = torch.where(mix.unsqueeze(1).unsqueeze(2), still, demo)
        return demo

# ================================================ Rewards ================================================== #
    def _reward_ref_joint_pos(self):
        """
        Calculates the reward based on the difference between the current joint positions and the target joint positions.
        """
        joint_pos = self.dof_pos.clone()
        pos_target = self.ref_dof_pos.clone()
        stand_command = (torch.norm(self.commands[:, :3], dim=1) <= self.cfg.commands.stand_com_threshold)
        pos_target[stand_command] = self.default_dof_pos.clone()
        diff = joint_pos - pos_target
        r = torch.exp(-2 * torch.norm(diff, dim=1)) - 0.2 * torch.norm(diff, dim=1).clamp(0, 0.5)
        r[stand_command] = 1.0
        return r
    
    def _reward_feet_distance(self):
        """
        Calculates the reward based on the distance between the feet. Penilize feet get close to each other or too far away.
        """
        foot_pos = self.rigid_state[:, self.feet_indices, :2]
        foot_dist = torch.norm(foot_pos[:, 0, :] - foot_pos[:, 1, :], dim=1)
        fd = self.cfg.rewards.foot_min_dist
        max_df = self.cfg.rewards.foot_max_dist
        d_min = torch.clamp(foot_dist - fd, -0.5, 0.)
        d_max = torch.clamp(foot_dist - max_df, 0, 0.5)
        return (torch.exp(-torch.abs(d_min) * 100) + torch.exp(-torch.abs(d_max) * 100)) / 2

    def _reward_knee_distance(self):
        """
        Calculates the reward based on the distance between the knee of the humanoid.
        """
        foot_pos = self.rigid_state[:, self.knee_indices, :2]
        foot_dist = torch.norm(foot_pos[:, 0, :] - foot_pos[:, 1, :], dim=1)
        fd = self.cfg.rewards.foot_min_dist
        max_df = self.cfg.rewards.foot_max_dist / 2
        d_min = torch.clamp(foot_dist - fd, -0.5, 0.)
        d_max = torch.clamp(foot_dist - max_df, 0, 0.5)
        return (torch.exp(-torch.abs(d_min) * 100) + torch.exp(-torch.abs(d_max) * 100)) / 2

    def _reward_foot_slip(self):
        """
        Calculates the reward for minimizing foot slip. The reward is based on the contact forces 
        and the speed of the feet. A contact threshold is used to determine if the foot is in contact 
        with the ground. The speed of the foot is calculated and scaled by the contact conditions.
        """
        contact = self.contact_forces[:, self.feet_indices, 2] > 5.
        foot_speed_norm = torch.norm(self.rigid_state[:, self.feet_indices, 10:12], dim=2)
        rew = torch.sqrt(foot_speed_norm)
        rew *= contact
        return torch.sum(rew, dim=1)

    def _reward_feet_air_time(self):
        """
        Calculates the reward for feet air time, promoting longer steps. This is achieved by
        checking the first contact with the ground after being in the air. The air time is
        limited to a maximum value for reward calculation.
        """
        contact = self.contact_forces[:, self.feet_indices, 2] > 5.
        # exp1.8: contact_filt 剥离 stance_mask——相位期望不应伪造"触地"事实：
        # 不跟拍的策略真实抬脚时（相位却说该支撑）air_time 被强制清零 → 永不触发落地
        # 奖励 → 抬脚零梯度死区（exp1.7 全程 0.0019）。相位对齐职责移交 swing_air/
        # feet_contact_number（那里有一对一耦合）。站立时 phase=0 双支撑、脚贴地，
        # air_time 天然不累积，无需 stand 分支。
        self.contact_filt = torch.logical_or(contact, self.last_contacts)
        self.last_contacts = contact
        first_contact = (self.feet_air_time > 0.) * self.contact_filt
        self.feet_air_time += self.dt
        air_time = self.feet_air_time.clamp(0, 0.5) * first_contact
        self.feet_air_time *= ~self.contact_filt
        return air_time.sum(dim=1)

    def _reward_swing_air(self):
        """exp1.8: 摆动相离地奖励——相位说该摆动的脚，真实离地即得分（每步连续）。

        机理：直接教"相位-抬脚"一对一耦合（左摆动相抬左脚、右摆动相抬右脚，
        半周期一交换）——交替步态的最小可学单元。无落地事件依赖（air_time 的
        结构性死区来源），无 stance_mask 清零路径。
        副作用防护：一直抬腿→单支撑必倒（物理）；双支撑期（|sin|<0.1）双方
        stance_mask=1 不得分；feet_contact_number（错配 -1.0）反向钳制。
        站立 env：phase 恒 0 → sin=0 → 双支撑 → 天然 0 分。
        """
        contact = self.contact_forces[:, self.feet_indices, 2] > 5.
        swing = 1. - self._get_stance_mask()          # (N,2) 1=期望摆动
        return (swing * (~contact).float()).sum(dim=1)

    def _reward_feet_contact_number(self):
        """
        Calculates a reward based on the number of feet contacts aligning with the gait phase. 
        Rewards or penalizes depending on whether the foot contact matches the expected gait phase.
        """
        contact = self.contact_forces[:, self.feet_indices, 2] > 5.
        stance_mask = self._get_stance_mask().clone()
        stance_mask[torch.norm(self.commands[:, :3], dim=1) <= self.cfg.commands.stand_com_threshold] = 1
        # exp1.8: 错配罚分 -0.3→-1.0——旧值下贴地策略单支撑期错配一只仍净赚
        # （(1-0.3)/2=+0.35/步，exp1.7 实测 1.23/ep 为零对齐基线 3.5 倍），激励反转：
        # 贴地净收益归零，真实交替全匹配 2/步
        reward = torch.where(contact == stance_mask, 1, -1.0)
        return torch.mean(reward, dim=1)

    def _reward_hip_ref(self):
        """exp1.8: 左右髋 pitch 对查表 ref 的专项跟踪——交替波形 2 维直锚。

        机理：ref 查表轨迹（yz demo）本身含大幅交替摆髋，单锚这两维等于直接
        注入交替波形；ref_joint_pos 是 29 维全身范数，交替模式（2 维）被稀释
        （exp1.7 全身跟踪仅 0.18~0.20）。公式沿用 ref_joint_pos 形态
        （exp(-2d) + 远场线性项）。站立锁 1.0 与其一致。
        """
        idx = self.leg_dof_indices[[0, 6]]            # 左/右 hip_pitch
        diff = self.dof_pos[:, idx] - self.ref_dof_pos[:, idx]
        d = torch.norm(diff, dim=1)
        r = torch.exp(-2 * d) - 0.2 * d.clamp(0, 0.5)
        stand_command = (torch.norm(self.commands[:, :3], dim=1) <= self.cfg.commands.stand_com_threshold)
        r[stand_command] = 1.0
        return r

    def _reward_foot_height(self):
        """exp1.9: 摆动相足高对相位钟形目标的连续跟踪——攻 tap 试探（§19）。

        机理：swing_air（二值"离地即赚"）下策略学到 1~2cm 点地试探（exp1.8 终值
        0.219/2.0≈11%）。本项用相位生成钟形目标 h_target = A·|sin(2πφ)|（左脚在
        sin<0 半周期摆动 → relu(-sin)，右对称），逼"完整摆动"（0→A→0）。
        - 直接世界坐标计算（rigid_state z − ankle 距离），无 feet_height 状态依赖
          （旧 feet_clearance 的累计量只在被调用时更新，跨界引用有时序陷阱）
        - 双支撑窗 |sin|<0.1 目标≈0，触地即满足；站立锁 1.0 与 hip_ref 一致
        - 峰值 A=cfg.rewards.foot_height_target（0.08）；容差 0.04（A/2）
        """
        sin_pos = torch.sin(2 * torch.pi * self._get_phase())              # (N,)
        h = self.rigid_state[:, self.feet_indices, 2] \
            - self.cfg.rewards.feet_to_ankle_distance                       # 离地高度 (N,2)
        A = self.cfg.rewards.foot_height_target
        tgt = torch.stack([torch.relu(-sin_pos), torch.relu(sin_pos)], dim=1) * A
        r = torch.exp(-torch.abs(h - tgt) / (0.5 * A))
        stand_command = (torch.norm(self.commands[:, :3], dim=1) <= self.cfg.commands.stand_com_threshold)
        r[stand_command] = 1.0
        return r.sum(dim=1)

    def _reward_foot_place(self):
        """exp1.12: 摆动腿落点锚——步幅按 v_cmd×T/2 缩放（§20）。

        机理：cycle_eff 只缩节奏（T），参考几何步幅 0.62m 固定 → 稳态速度饱和
        ~0.5（exp1.11 速度扫描：0.3~0.8 档全聚 0.46~0.55）。本项补第二自由度：
        每步目标位移 step_len = v_cmd·T/2，摆动相内前脚 x（根系投影）连续跟踪
        root_x + 0.75·step_len——几何自洽（v = 2·step_len/T 恰为指令速度），
        且落点进支撑多边形兼是防摔稳定器（第一瓶颈 8~10s/摔）。
        - 根系投影：世界系 (foot-root) 经 quat_rotate_inverse 取 x，免疫 yaw
          漂移（±17°/s）对步幅语义的污染
        - 0.75 = 触地几何 0.5 + 支撑相余量 0.25（快测校准常数）
        - 方向约定同 foot_height：sin<0 左摆、sin>0 右摆；双支撑 |sin|<0.1
          不激活；站立锁 1.0
        """
        sin_pos = torch.sin(2 * torch.pi * self._get_phase())              # (N,)
        v_cmd = self.commands[:, 0].clamp(min=0.)                           # (N,)
        T = self._current_cycle_time()                                     # (N,) exp1.7 自适应
        step_len = v_cmd * T / 2
        foot = self.rigid_state[:, self.feet_indices, 0:3]                 # (N,2,3) 世界系
        root_p = self.root_states[:, 0:3]                                  # (N,3)
        # 左右脚分别转根系（(N,4)×(N,3) 标准用法——TorchScript 不接受 (N,2,4)×(N,2,3)）
        fwd = torch.stack([
            quat_rotate_inverse(self.base_quat, foot[:, 0, :] - root_p)[:, 0],
            quat_rotate_inverse(self.base_quat, foot[:, 1, :] - root_p)[:, 0],
        ], dim=1)                                                          # (N,2) 根系前向偏移
        tgt = 0.75 * step_len.unsqueeze(1)                                  # (N,1) 相对根
        r = torch.exp(-torch.abs(fwd - tgt) / self.cfg.rewards.foot_place_sigma)
        swing = torch.stack([sin_pos < -0.1, sin_pos > 0.1], dim=1)         # 左摆/右摆
        r = torch.where(swing, r, torch.ones_like(r))                       # 非摆动相不罚
        stand_command = (torch.norm(self.commands[:, :3], dim=1) <= self.cfg.commands.stand_com_threshold)
        r[stand_command] = 1.0
        return r.sum(dim=1)

    def _reward_orientation(self):
        """
        Calculates the reward for maintaining a flat base orientation. It penalizes deviation 
        from the desired base orientation using the base euler angles and the projected gravity vector.
        """
        quat_mismatch = torch.exp(-torch.sum(torch.abs(self.base_euler_xyz[:, :2]), dim=1) * 10)
        orientation = torch.exp(-torch.norm(self.projected_gravity[:, :2], dim=1) * 20)
        return (quat_mismatch + orientation) / 2.

    def _reward_torso_pitch_lpf(self):
        """
        exp2.0：抑制"持续后仰"——对 EMA 低通后的躯干俯仰与目标（直立）之差给奖。

        · 为什么用低通量而非瞬时量：正常步态每步有 ≈0.05 rad 俯仰摆动，瞬时惩罚会误伤步态
          节律；低通后只保留"持续后仰"这一实测签名（多环境预算表：行走段 pitch 均值 −0.177、
          99.9% 的行走 episode 为后仰，且段内再累积 ≈0.20 rad）。pitch 的瞬时分量已由
          `orientation` 覆盖（本项与其互补，不是重复）。
        · 为什么必须带线性底：纯指数核在远端会饱和。以 σ=20 为例，基线后仰 d≈0.15 处
          exp(−3)=0.050、梯度仅 20×0.050=1.0 /rad，d≈0.25 处只剩 0.13 /rad → 恰好**在唯一
          需要的区间**失去梯度（这也是 σ 最终取 8 的原因：|d| 核在 0.15/0.25 处仍保留
          1.94/1.08 /rad）。线性底再给出与偏移量**无关**的恒定梯度，负责 d>0.3 的远端；
          "exp + 线性底"的写法与本仓 `_reward_ref_joint_pos` / `_reward_hip_ref` 一致。
        · 符号：pitch = asin(2(qw·qy − qz·qx))，绕 +y 轴 → **正=前倾、负=后仰**。
        """
        alpha = self.cfg.rewards.pitch_lpf_alpha
        self._pitch_lpf = alpha * self._pitch_lpf + (1.0 - alpha) * self.base_euler_xyz[:, 1]
        d = torch.abs(self._pitch_lpf - self.cfg.rewards.pitch_target)
        return (torch.exp(-self.cfg.rewards.pitch_sigma * d)
                - self.cfg.rewards.pitch_lin_coef * d.clamp(0.0, self.cfg.rewards.pitch_lin_cap))

    def _reward_feet_contact_forces(self):
        """
        Calculates the reward for keeping contact forces within a specified range. Penalizes
        high contact forces on the feet.
        """
        return torch.sum((torch.norm(self.contact_forces[:, self.feet_indices, :], dim=-1) - self.cfg.rewards.max_contact_force).clip(0, 400), dim=1)

    def _reward_default_joint_pos(self):
        """
        Calculates the reward for keeping joint positions close to default positions, with a focus 
        on penalizing deviation in yaw and roll directions. Excludes yaw and roll from the main penalty.
        """
        joint_diff = self.dof_pos - self.default_joint_pd_target
        left_yaw_roll = joint_diff[:, self.leg_dof_indices[[1,2,5]]]
        right_yaw_roll = joint_diff[:, self.leg_dof_indices[[7,8,11]]]
        yaw_roll = torch.norm(left_yaw_roll, dim=1) + torch.norm(right_yaw_roll, dim=1)
        yaw_roll = torch.clamp(yaw_roll - 0.1, 0, 50)
        return torch.exp(-yaw_roll * 100) - 0.01 * torch.norm(joint_diff, dim=1)

    def _reward_base_height(self):
        """
        Calculates the reward based on the robot's base height. Penalizes deviation from a target base height.
        The reward is computed based on the height difference between the robot's base and the average height 
        of its feet when they are in contact with the ground.
        """
        stance_mask = self._get_stance_mask()
        measured_heights = torch.sum(
            self.rigid_state[:, self.feet_indices, 2] * stance_mask, dim=1) / torch.sum(stance_mask, dim=1)
        base_height = self.root_states[:, 2] - (measured_heights - self.cfg.rewards.feet_to_ankle_distance)
        return torch.exp(-torch.abs(base_height - self.cfg.rewards.base_height_target) * 100)

    def _reward_base_acc(self):
        """
        Computes the reward based on the base's acceleration. Penalizes high accelerations of the robot's base,
        encouraging smoother motion.
        """
        root_acc = self.last_root_vel - self.root_states[:, 7:13]
        rew = torch.exp(-torch.norm(root_acc, dim=1) * 3)
        return rew


    def _reward_vel_mismatch_exp(self):
        """
        Computes a reward based on the mismatch in the robot's linear and angular velocities.
        Encourages the robot to maintain a stable velocity by penalizing large deviations.
        """
        lin_mismatch = torch.exp(-torch.square(self.base_lin_vel[:, 2]) * 10)
        ang_mismatch = torch.exp(-torch.norm(self.base_ang_vel[:, :2], dim=1) * 5.)

        c_update = (lin_mismatch + ang_mismatch) / 2.

        return c_update

    def _reward_lat_vel(self):
        # exp0.2: 仅在无侧向指令时线性惩罚侧向速度（消除净漂移），
        # 侧向指令段豁免以避免与 tracking_lin_vel 的 vy 跟踪冲突
        no_lat_cmd = (torch.abs(self.commands[:, 1]) <= 0.05).float()
        return torch.abs(self.base_lin_vel[:, 1]) * no_lat_cmd

    def _reward_yaw_drift(self):
        # exp1.3: 仅在无转向指令时线性惩罚偏航角速度（抑制左右步不对称的慢累积漂移），
        # 转向指令段豁免以避免与 tracking_ang_vel 冲突
        no_yaw_cmd = (torch.abs(self.commands[:, 2]) <= 0.05).float()
        return torch.abs(self.base_ang_vel[:, 2]) * no_yaw_cmd

    def _reward_track_vel_hard(self):
        """
        Calculates a reward for accurately tracking both linear and angular velocity commands.
        Penalizes deviations from specified linear and angular velocity targets.
        """
        # Tracking of linear velocity commands (xy axes)
        lin_vel_error = torch.norm(
            self.commands[:, :2] - self.base_lin_vel[:, :2], dim=1)
        lin_vel_error_exp = torch.exp(-lin_vel_error * 10)

        # Tracking of angular velocity commands (yaw)
        ang_vel_error = torch.abs(
            self.commands[:, 2] - self.base_ang_vel[:, 2])
        ang_vel_error_exp = torch.exp(-ang_vel_error * 10)

        linear_error = 0.2 * (lin_vel_error + ang_vel_error)
        r = (lin_vel_error_exp + ang_vel_error_exp) / 2. - linear_error
        return r
    
    def _reward_tracking_lin_vel(self):
        """
        Tracks linear velocity commands along the xy axes. 
        Calculates a reward based on how closely the robot's linear velocity matches the commanded values.
        """
        stand_command = (torch.norm(self.commands[:, :3], dim=1) <= self.cfg.commands.stand_com_threshold)
        lin_vel_error_square = torch.sum(torch.square(
            self.commands[:, :2] - self.base_lin_vel[:, :2]), dim=1)
        lin_vel_error_abs = torch.sum(torch.abs(
            self.commands[:, :2] - self.base_lin_vel[:, :2]), dim=1)
        r_square = torch.exp(-lin_vel_error_square * self.cfg.rewards.tracking_sigma)
        r_abs = torch.exp(-lin_vel_error_abs * self.cfg.rewards.tracking_sigma * 2)
        r = torch.where(stand_command, r_abs, r_square)

        return r

    def _reward_tracking_ang_vel(self):
        """
        Tracks angular velocity commands for yaw rotation.
        Computes a reward based on how closely the robot's angular velocity matches the commanded yaw values.
        """   
        stand_command = (torch.norm(self.commands[:, :3], dim=1) <= self.cfg.commands.stand_com_threshold)
        ang_vel_error_square = torch.square(
            self.commands[:, 2] - self.base_ang_vel[:, 2])
        ang_vel_error_abs = torch.abs(
            self.commands[:, 2] - self.base_ang_vel[:, 2])
        r_square = torch.exp(-ang_vel_error_square * self.cfg.rewards.tracking_sigma)
        r_abs = torch.exp(-ang_vel_error_abs * self.cfg.rewards.tracking_sigma * 2)
        r = torch.where(stand_command, r_abs, r_square)

        return r 
    
    def _reward_feet_clearance(self):
        """
        Calculates reward based on the clearance of the swing leg from the ground during movement.
        Encourages appropriate lift of the feet during the swing phase of the gait.
        """
        # Compute feet contact mask
        contact = self.contact_forces[:, self.feet_indices, 2] > 5.

        # Get the z-position of the feet and compute the change in z-position
        feet_z = self.rigid_state[:, self.feet_indices, 2] - self.cfg.rewards.feet_to_ankle_distance
        delta_z = feet_z - self.last_feet_z
        self.feet_height += delta_z
        self.last_feet_z = feet_z

        # Compute swing mask
        swing_mask = 1 - self._get_stance_mask()

        # feet height should larger than target feet height at the peak
        rew_pos = (self.feet_height > self.cfg.rewards.target_feet_height) * (self.feet_height < self.cfg.rewards.target_feet_height_max)
        rew_pos = torch.sum(rew_pos * swing_mask, dim=1)
        self.feet_height *= ~contact
        return rew_pos

    def _reward_low_speed(self):
        """
        Rewards or penalizes the robot based on its speed relative to the commanded speed. 
        This function checks if the robot is moving too slow, too fast, or at the desired speed, 
        and if the movement direction matches the command.
        """
        # Calculate the absolute value of speed and command for comparison
        absolute_speed = torch.abs(self.base_lin_vel[:, 0])
        absolute_command = torch.abs(self.commands[:, 0])

        # Define speed criteria for desired range
        speed_too_low = absolute_speed < 0.5 * absolute_command
        speed_too_high = absolute_speed > 1.2 * absolute_command
        speed_desired = ~(speed_too_low | speed_too_high)

        # Check if the speed and command directions are mismatched
        sign_mismatch = torch.sign(
            self.base_lin_vel[:, 0]) != torch.sign(self.commands[:, 0])

        # Initialize reward tensor
        reward = torch.zeros_like(self.base_lin_vel[:, 0])

        # Assign rewards based on conditions
        # Speed too low（exp1: -1.0→-2.0 治 exp0.3 原地踏步局部最优——步态形奖励白拿但 tracking σ=5 太平，
        # 踏步净收益为正；配合 σ 5→20 与 low_speed scale 0.2→1.0 让踏步净收益转负）
        reward[speed_too_low] = -2.0
        # Speed too high（exp0.3: 0→-1.0 对称罚，堵超速白赚漏洞）
        reward[speed_too_high] = -1.0
        # Speed within desired range
        reward[speed_desired] = 1.2
        # Sign mismatch has the highest priority
        reward[sign_mismatch] = -2.0
        return reward * (self.commands[:, 0].abs() > 0.05)
    
    def _reward_torques(self):
        """
        Penalizes the use of high torques in the robot's joints. Encourages efficient movement by minimizing
        the necessary force exerted by the motors.
        """
        return torch.sum(torch.square(self.torques), dim=1)
    
    def _reward_ankle_torques(self):
        """
        Penalizes the use of high torques in the robot's joints. Encourages efficient movement by minimizing
        the necessary force exerted by the motors.
        """
        ankle_idx = self.leg_dof_indices[[4, 5, 10, 11]]
        return torch.sum(torch.square(self.torques[:,ankle_idx]), dim=1)
    
    def _reward_feet_rotation(self):
        feet_euler_xyz = self.feet_euler_xyz
        rotation = torch.sum(torch.square(feet_euler_xyz[:,:,:2]),dim=[1,2])
        # rotation = torch.sum(torch.square(feet_euler_xyz[:,:,1]),dim=1)
        r = torch.exp(-rotation*15)
        return r

    def _reward_dof_vel(self):
        """
        Penalizes high velocities at the degrees of freedom (DOF) of the robot. This encourages smoother and 
        more controlled movements.
        """
        return torch.sum(torch.square(self.dof_vel), dim=1)
    
    def _reward_dof_acc(self):
        """
        Penalizes high accelerations at the robot's degrees of freedom (DOF). This is important for ensuring
        smooth and stable motion, reducing wear on the robot's mechanical parts.
        """
        return torch.sum(torch.square((self.last_dof_vel - self.dof_vel) / self.dt), dim=1)
    
    def _reward_collision(self):
        """
        Penalizes collisions of the robot with the environment, specifically focusing on selected body parts.
        This encourages the robot to avoid undesired contact with objects or surfaces.
        """
        return torch.sum(1.*(torch.norm(self.contact_forces[:, self.penalised_contact_indices, :], dim=-1) > 0.1), dim=1)
    
    def _reward_action_smoothness(self):
        """
        Encourages smoothness in the robot's actions by penalizing large differences between consecutive actions.
        This is important for achieving fluid motion and reducing mechanical stress.
        """
        term_1 = torch.sum(torch.square(
            self.last_actions - self.actions), dim=1)
        term_2 = torch.sum(torch.square(
            self.actions + self.last_last_actions - 2 * self.last_actions), dim=1)
        term_3 = 0.05 * torch.sum(torch.abs(self.actions), dim=1)
        return term_1 + term_2 + term_3
    
    def _reward_termination(self):
        # Terminal reward / penalty
        return self.reset_buf * ~self.time_out_buf
    
    def _reward_stand_still(self):
        # penalize motion at zero commands
        stand_command = (torch.norm(self.commands[:, :3], dim=1) <= self.cfg.commands.stand_com_threshold)
        r = torch.exp(-torch.sum(torch.square(self.dof_pos - self.default_dof_pos), dim=1))
        r = torch.where(stand_command, r.clone(),
                        torch.zeros_like(r))
        return r
    
    def _reward_feet_stumble(self):
        # Penalize feet hitting vertical surfaces
        return torch.any(torch.norm(self.contact_forces[:, self.feet_indices, :2], dim=2) >\
             5 *torch.abs(self.contact_forces[:, self.feet_indices, 2]), dim=1)

    def _reward_dof_pos_limits(self):
        # Penalize dof positions too close to the limit
        out_of_limits = -(self.dof_pos - self.dof_pos_limits[:, 0]).clip(max=0.) # lower limit
        out_of_limits += (self.dof_pos - self.dof_pos_limits[:, 1]).clip(min=0.)
        return torch.sum(out_of_limits, dim=1)

    def _reward_dof_vel_limits(self):
        # Penalize dof velocities too close to the limit
        # clip to max error = 1 rad/s per joint to avoid huge penalties
        return torch.sum((torch.abs(self.dof_vel) - self.dof_vel_limits*self.cfg.rewards.soft_dof_vel_limit).clip(min=0., max=1.), dim=1)

    def _reward_dof_torque_limits(self):
        # penalize torques too close to the limit
        return torch.sum((torch.abs(self.torques) - self.torque_limits*self.cfg.rewards.soft_torque_limit).clip(min=0.), dim=1)