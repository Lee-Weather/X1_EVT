# Copyright (c) 2024, AgiBot Inc. All rights reserved.
# exp1 AMP 环形缓冲：robolab storage/circular_buffer.py 精简版
#
# - 构造期预分配（max_len, batch_size, *obs_shape），append 仅写行——
#   保证在 runner 的 inference_mode rollout 中写入不产生推理张量（推理张量不能进 backward）
# - 容量 max_len 控制步 > rollout 窗（24），FIFO 滑窗跨迭代混合新旧策略样本防 stale，
#   训练期不清空（storage.clear() 只清 RolloutStorage）
# - mini_batch_generator 从 (有效步 × batch) 组合空间随机抽样，与 PPO 同频同批训练判别器

import torch


class CircularBuffer:

    def __init__(self, max_len, batch_size, obs_shape, device):
        if max_len < 1:
            raise ValueError("buffer max_len 须 >= 1, 实际 {}".format(max_len))
        self.max_len = int(max_len)
        self.batch_size = int(batch_size)
        self.device = device
        self._buffer = torch.zeros(self.max_len, self.batch_size, *obs_shape, device=device)
        self._pointer = -1
        self._num_pushes = 0

    @property
    def filled_steps(self):
        return min(self._num_pushes, self.max_len)

    def append(self, data):
        """data: (batch_size, *obs_shape)，整批写一行"""
        if data.shape[0] != self.batch_size:
            raise ValueError("append batch {} != buffer batch {}".format(
                data.shape[0], self.batch_size))
        self._pointer = (self._pointer + 1) % self.max_len
        self._buffer[self._pointer] = data.to(self.device)
        self._num_pushes += 1

    def append_masked(self, data, mask):
        """exp1.5: 门控写入——mask 为 False 的 env 保留上一行旧样本（本步不更新）。

        agent buffer 三重门控用（~stand & ~done & episode_len>阈值）：站立/终止/
        复位初期样本不进 D 的训练集，剥掉"速度幅度"等平凡可分特征（exp1.3 死锁
        头号嫌疑：gait 26% 站立段样本 vs 100% 行走 demo，与 exp1 的 demo 静立窗
        问题互为镜像）。首行（无旧样本可保留）时 False 槽位写当前值，随滑窗自然
        更新淘汰。demo buffer 不门控（本来就干净）。

        Args:
            data: (batch_size, *obs_shape)
            mask: (batch_size,) bool
        """
        if data.shape[0] != self.batch_size:
            raise ValueError("append batch {} != buffer batch {}".format(
                data.shape[0], self.batch_size))
        if mask.shape[0] != self.batch_size:
            raise ValueError("mask batch {} != buffer batch {}".format(
                mask.shape[0], self.batch_size))
        prev_ptr = (self._pointer - 1) % self.max_len if self._num_pushes > 0 else None
        self._pointer = (self._pointer + 1) % self.max_len
        row = self._buffer[self._pointer]
        row.copy_(data.to(self.device))
        if prev_ptr is not None and not bool(mask.all()):
            # 不健康 env 槽位回退为上一行同 env 旧样本（等效该 env 本步不更新）
            row[~mask] = self._buffer[prev_ptr][~mask]
        self._num_pushes += 1

    def mini_batch_generator(self, fetch_length, num_mini_batches, num_epochs):
        """与 RolloutStorage.mini_batch_generator 同频：每 epoch 抽
        batch_size × fetch_length 个样本，切 num_mini_batches 份"""
        valid_len = self.filled_steps
        if fetch_length > valid_len:
            raise ValueError("fetch_length {} 超过缓冲有效步数 {}".format(
                fetch_length, valid_len))
        epoch_batch_size = self.batch_size * fetch_length
        if epoch_batch_size % num_mini_batches != 0:
            raise ValueError("epoch batch {} 不能被 {} 整除".format(
                epoch_batch_size, num_mini_batches))
        mini_batch_size = epoch_batch_size // num_mini_batches

        # (step, env) 组合空间均匀随机抽 epoch_batch_size 对（跨步跨 env 打散）
        linear = torch.randperm(valid_len * self.batch_size, device=self.device)[:epoch_batch_size]
        idx_step = torch.div(linear, self.batch_size, rounding_mode="floor")
        idx_env = linear % self.batch_size
        for _ in range(num_epochs):
            order = torch.randperm(epoch_batch_size, device=self.device)
            for i in range(num_mini_batches):
                sel = order[i * mini_batch_size:(i + 1) * mini_batch_size]
                yield self._buffer[idx_step[sel], idx_env[sel]]
