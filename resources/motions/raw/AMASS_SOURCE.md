# AMASS_minimal 归档说明（mocap 再生源 · 外部归档随行文件）

> 本目录 `resources/motions/raw/` 存放 ref_lib.pt 再生链的小文件正本。
> AMASS 源数据本体（573M，22 个文件）**不入库**，归档于外部存储（网盘/移动硬盘）；
> 本文件 + `AMASS_manifest.md5` 足以在任何机器上校验和恢复它。

## 1. 这是什么

`AMASS_minimal` 是 2026-09-03 GMR 重定向时从 AMASS 官方数据中抽取的**最小集**，
即"resources/x1_gmr + x1_lab 14 段重定向动作"的原始源头：

| 子目录 | 体积 | 内容 | 对应重定向产物 |
| --- | --- | --- | --- |
| `BMLrub_stageii/` | 30M | 8 个 npz（StageII，跑步机/行走/慢跑/走圈） | `0000_treadmill_norm` `0002_treadmill_slow` `0003_treadmill_jog` `0005_normal_walk1` `0007_normal_walk3` `0008_normal_walk4` `0009_normal_jog1` `0026_circle_walk` |
| `CMU/` | 24M | 6 个 npz（CMU 号段 36/114/127） | `36_01` `36_11` `114_08` `114_09` `127_04` `127_06` |
| `smplx_parts/` | 519M | `SMPLX_NEUTRAL.pkl` 分片（partaa–partaf，6 片，`cat` 合并还原） | 重定向时的 SMPLX 身体模型 |

## 2. 校验

归档后用清单校验（清单内路径相对于 `AMASS_minimal/` 根）：

```bash
cd <归档目录>/AMASS_minimal
md5sum -c /path/to/AMASS_manifest.md5
```

## 3. 再生链路（丢了 resources 成品时按此重建）

```
AMASS_minimal (外部归档)
  └─(czy/diff/roboparty_train: run_gmr_retarget.py + robolab/scripts/tools/retarget/)
       → resources/x1_gmr/*.npz+pkl、resources/x1_lab/*.npz+pkl   (14 段)
           └─(scripts/tools/prep_mocap_ref.py)                     → ref_lib.pt 前 3 段
resources/motions/raw/yz_walk.csv  (本目录，真机直线行走 30Hz CSV)
  └─(scripts/tools/prep_yz_ref.py)                                 → ref_lib.pt 第 4 段 walk_yz
```

注意：
- 重定向工具链**自包含在 `czy/diff/roboparty_train/`**（含自带 meshes/urdf），整包随归档走，勿拆散
- 重定向的模型配置正本（x1.xml + x1_tpose.json）在本仓库 `resources/retarget/gmr_x1_assets/`（2026-09-21 起，run_gmr_retarget.py 自动向上搜索定位）
- `smplx_parts/` 还原身体模型：`cat SMPLX_NEUTRAL.pkl.parta* > SMPLX_NEUTRAL.pkl`

## 4. 归档清单速览

- 生成时间：2026-09-21（md5 清单 `AMASS_manifest.md5`，22 条）
- 总体积：573M（BMLrub 30M + CMU 24M + smplx_parts 519M）
