#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""exp1.13 Step 1 汇总：读 stab_budget.csv → 稳定性预算表（exp1.md §13.4 产出）

采集端 stab_budget.py 跑在 isaacgym 的 py38 环境（无 pandas），本报告脚本用带 pandas 的
解释器运行，例如：
  /home/robot/Anaconda/bin/python humanoid/scripts/stab_budget_report.py \
      --csv czy/data/exp1.13/stab_budget.csv
"""
import argparse
import os

import numpy as np
import pandas as pd

LEGGED_GYM_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CSV = os.path.join(LEGGED_GYM_ROOT_DIR, "czy", "data", "exp1.13", "stab_budget.csv")


def q(s, p):
    return np.nanpercentile(s.dropna().values, p) if len(s.dropna()) else np.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--show", action="store_true", help="打印逐 episode（默认只打汇总）")
    a = ap.parse_args()

    df = pd.read_csv(a.csv)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 60)
    df["terminated"] = df["terminated"].astype(str).str.lower().isin(["true", "1"])
    walk = df[df.n_walk > 0].copy()          # 有行走段的 episode
    term = df[df.terminated].copy()

    print("================ exp1.13 Step1 稳定性预算表 ================")
    print(f"csv={a.csv}")
    print(f"episodes={len(df)}（含行走段 {len(walk)}） 提前终止 {len(term)} 个 "
          f"= {100*len(term)/len(df):.1f}%  最长 episode={int(df.ep_len.max())} 步")

    print("\n-- ① 终止原因分解 --")
    g = df.groupby("reason")
    tb = pd.DataFrame({
        "n": g.size(),
        "占全部%": (100 * g.size() / len(df)).round(1),
        "占提前终止%": (100 * g.size() / max(len(term), 1)).round(1),
        "ep_len 中位": g.ep_len.median().round(0),
        "ep_len 均值": g.ep_len.mean().round(0),
        "ep_len p05": g.ep_len.apply(lambda x: q(x, 5)).round(0),
    }).sort_values("n", ascending=False)
    print(tb.to_string())
    print("\n[按 episode 序号看提前终止率]")
    tb_ep = df.groupby("ep").agg(n=("reason", "size"),
                                提前终止率=("terminated", lambda x: round(100 * x.mean(), 1)))
    print(tb_ep.to_string())

    print("\n-- ② 落地相（行走段，episode 级均值）--")
    cols = ["ds_pct", "ss_pct", "fl_pct", "fl_ev_50ms", "fl_max_ms"]
    tb2 = walk.groupby("reason")[cols].mean().round(2)
    tb2["n"] = walk.groupby("reason").size()
    print(tb2.to_string())
    print(f"\n全局：双支撑 均值 {walk.ds_pct.mean():.2f}% / 中位 {walk.ds_pct.median():.2f}%"
          f"（p05 {q(walk.ds_pct,5):.2f} / p95 {q(walk.ds_pct,95):.2f}）")
    print(f"      单支撑 均值 {walk.ss_pct.mean():.2f}% | 腾空 均值 {walk.fl_pct.mean():.2f}%")
    print(f"      ≥50ms 腾空事件 {int(walk.fl_ev_50ms.sum())} 次，落在 {int((walk.fl_ev_50ms>0).sum())}/{len(walk)} "
          f"episodes（{100*(walk.fl_ev_50ms>0).mean():.1f}%）| 最长腾空 {int(walk.fl_max_ms.max())}ms")
    print(f"      钟上双支撑：k=0.1 → 6.38% | k=0.25 → 16.09%")

    print("\n-- ③ 余量分布（行走段，episode 级）--")
    print(walk[["h_min", "roll_max", "pitch_max", "wz_max"]]
          .describe(percentiles=[0.05, 0.5, 0.95, 0.99]).round(3).to_string())
    print("\n[按原因看余量中位]")
    print(walk.groupby("reason")[["h_min", "roll_max", "pitch_max", "wz_max"]].median().round(3).to_string())

    print("\n-- ④ 终止前 0.5s 窗 vs 全局（因果链检验）--")
    print("注：timeout 的 episode 结尾恒为 stand 段（gait=['stand','walk_omnidirectional','stand']，"
          "命令被重采为 0）\n     → 其末 0.5s 无行走样本，故下表把窗口指标限制在 n_walk_last0p5s>0 的 episode")
    wt = walk[walk.n_walk_last0p5s > 0]
    print(f"有效样本 {len(wt)}/{len(walk)}（timeout 段内掉 {len(walk)-len(wt)} 个）")
    print(f"腾空占比：全局 {wt.fl_pct.mean():.2f}%  →  前0.5s {wt.fl_pct_last0p5s.mean():.2f}%")
    print(f"双支撑占比：全局 {wt.ds_pct.mean():.2f}%  →  前0.5s {wt.ds_pct_last0p5s.mean():.2f}%")
    wtt = wt[wt.terminated]
    if len(wtt):
        print(f"仅提前终止 {len(wtt)} 个：其全局 腾空 {wtt.fl_pct.mean():.2f}% / 双支撑 {wtt.ds_pct.mean():.2f}%"
              f"  →  前0.5s 腾空 {wtt.fl_pct_last0p5s.mean():.2f}% / 双支撑 {wtt.ds_pct_last0p5s.mean():.2f}%")
    print("\n[按原因：窗口 vs 全局]")
    print(wt.groupby("reason")[["fl_pct", "fl_pct_last0p5s", "ds_pct", "ds_pct_last0p5s", "n_walk_last0p5s"]]
          .mean().round(2).to_string())

    print("\n-- ⑤ 条件终止率（曝光量归一：终止次数 / 100 行走秒）--")
    dt = 0.01
    tot_s = df.n_walk.sum() * dt
    base = df.terminated.sum() / tot_s * 100
    print(f"基准：{int(df.terminated.sum())} 次提前终止 / {tot_s:.0f} 行走秒 = {base:.2f} 次/100s")
    print("（✱ 不能用'终止瞬间的指令取值分布'当判据——timeout 恒在结尾 stand 段结束、cmd≡0，"
          "会把任意非零命令都算成 100%）")
    rows = []
    for name, expo, cond in [
        ("|cmd wz| > 0.05", "wz_gt05", df.cmd_wz_end.abs() > 0.05),
        ("|cmd wz| > 0.15", "wz_gt15", df.cmd_wz_end.abs() > 0.15),
        ("|cmd wz| > 0.30", "wz_gt30", df.cmd_wz_end.abs() > 0.30),
        ("|cmd vy| > 0.05", "vy_gt05", df.cmd_y_end.abs() > 0.05),
        ("|cmd vy| > 0.15", "vy_gt15", df.cmd_y_end.abs() > 0.15),
        ("cmd vx > 0.80", "vx_gt08", df.cmd_x_end > 0.80),
    ]:
        expo_s = df[expo].sum() * dt
        n = int((df.terminated & cond).sum())
        rate = n / expo_s * 100 if expo_s > 0 else np.nan
        rows.append(dict(条件=name, 行走曝光s=round(expo_s), 提前终止数=n,
                         终止率每100s=round(rate, 2), 相对基准=round(rate / base, 2) if expo_s else np.nan))
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n[提前终止落在哪个参考段/段序（informational，无分母）]")
    print(pd.crosstab(term.seg_id, term.reason).to_string())
    print("\n[提前终止时刻 |sin(2πφ)| 分布（0=双支撑窗心，1=单支撑窗心）]")
    b = pd.cut(term.sin_end.abs(), [-1e-9, 0.05, 0.1, 0.2, 0.5, 1.001])
    print(term.groupby(b, observed=True).size().to_string())
    print("\n[各原因终止时刻 |sin| 中位]")
    print(term.assign(absin=term.sin_end.abs()).groupby("reason").absin.median().round(3).to_string())

    print("\n-- ⑥ 速度（行走段 episode 均值，仅正向指令 cmd_x_mean>0.1 才算速度比）--")
    sp = walk[walk.cmd_x_mean > 0.1]
    print(f"（{len(sp)}/{len(walk)} 个 episode 满足 cmd_x_mean>0.1）")
    print(sp[["vx_mean", "cmd_x_mean", "speed_ratio", "vy_rms", "yaw_drift"]]
          .describe(percentiles=[0.05, 0.5, 0.95]).round(3).to_string())
    print("\n[按指令档位看速度比——含 vx≈0.77 的 clamp 饱和点检查（候选 E）]")
    sp = sp.copy()
    sp["档"] = pd.cut(sp.cmd_x_mean, [0.1, 0.3, 0.5, 0.7, 0.9, 1.3])
    print(sp.groupby("档", observed=True)[["vx_mean", "cmd_x_mean", "speed_ratio"]].median().round(3).to_string())
    print(f"walk_slow 段（|vx|<0.15）占比按 seg 曝光不可得；参考段 crosstab：")
    print(pd.crosstab(df.seg_id, df.reason).to_string())

    if len(term):
        print("\n-- ⑦ 提前终止瞬间的状态 --")
        print(term[["h_end", "dh_025s", "vz_end", "roll_end", "pitch_end", "vx_end", "vy_end", "wz_end", "sin_end"]]
              .describe(percentiles=[0.05, 0.5, 0.95]).round(3).to_string())
        print("\n[按原因看终止瞬间中位状态——h<0.45 若 dh_025s/vz_end 近 0 说明是'蹲下'而非'塌陷']")
        print(term.groupby("reason")[["h_end", "dh_025s", "vz_end", "roll_end", "pitch_end",
                                      "vx_end", "wz_end", "sin_end", "ep_len"]]
              .median().round(3).to_string())

    # ---- ⑨ 躯干俯仰（exp2.0 修改四新增口径）----
    if "walk_pitch_mean" in df.columns:
        TAG = ["2000ms", "1000ms", "500ms", "100ms"]
        pit_cols = ["walk_pitch_mean", "walk_pitch_start", "walk_pitch_slope", "walk_pitch_span",
                    "pitch_max"]
        print("\n-- ⑨ 躯干俯仰（pitch = 绕 +y 轴转角 → **正=前倾，负=后仰**）--")
        print("注：历轮只有 pitch_max（绝对值），符号与段内漂移全丢；本段为 exp2.0 新增口径，"
              "所有验收判据依赖它")
        print(walk[pit_cols].describe(percentiles=[0.05, 0.5, 0.95]).round(4).to_string())
        print(f"\n段内斜率有效 {int(walk.walk_pitch_slope.notna().sum())}/{len(walk)} episodes"
              f"（每个**完整行走片段**整体最小二乘，跨片段取均值；片段 <0.3s 不计入）")
        print(f"段内跨度（片段末 pitch − 首 pitch，负 = 越走越后仰）："
              f"中位 {walk.walk_pitch_span.median():+.4f} rad"
              f"　|　水平法对照 (walk_pitch_mean − walk_pitch_start)："
              f"中位 {(walk.walk_pitch_mean - walk.walk_pitch_start).median():+.4f} rad")
        print("  注：两者差异大 = 段内轨迹**非单调**（先深后回），此时直线斜率会低估加深总量，"
              "以「跨度」与「水平」为准")
        print(f"后仰(walk_pitch_mean<0) 占 {100*(walk.walk_pitch_mean<0).mean():.1f}% | "
              f"强后仰(<-0.15) 占 {100*(walk.walk_pitch_mean<-0.15).mean():.1f}% | "
              f"段内持续加深(slope<-0.01 rad/s) 占 {100*(walk.walk_pitch_slope<-0.01).mean():.1f}%")
        print("\n[按终止原因（行走段）]")
        print(walk.groupby("reason")[pit_cols].median().round(4).to_string())

        tw = walk[walk.terminated]
        if len(tw):
            both = (tw.pitch_end < -0.3) & (tw.vx_end < 0)
            print("\n[终止时刻俯仰方向 —— 检验'上半身后仰 → 反向迈步/摔倒'签名]")
            tb = pd.DataFrame({
                "n": tw.groupby("reason").size(),
                "pitch_end中位": tw.groupby("reason").pitch_end.median().round(3),
                "后仰<−0.3占%": (100 * tw.assign(f=tw.pitch_end < -0.3).groupby("reason").f.mean()).round(0),
                "vx_end中位": tw.groupby("reason").vx_end.median().round(3),
                "反向<0占%": (100 * tw.assign(f=tw.vx_end < 0).groupby("reason").f.mean()).round(0),
            })
            tb["后仰且反向占%"] = (100 * tw.assign(f=(tw.pitch_end < -0.3) & (tw.vx_end < 0))
                              .groupby("reason").f.mean()).round(0)
            print(tb.to_string())
            print(f"\n行走段提前终止 {len(tw)} 次：后仰(pitch_end<−0.3) {int((tw.pitch_end<-0.3).sum())}"
                  f"（{100*(tw.pitch_end<-0.3).mean():.0f}%）| 反向(vx_end<0) {int((tw.vx_end<0).sum())}"
                  f"（{100*(tw.vx_end<0).mean():.0f}%）| **后仰且反向 {int(both.sum())}"
                  f"（{100*both.mean():.0f}%）** ← exp2.0 主判据之一（基线 exp1.12 = 41%）")
            pc = [f"pitch_signed_{t}" for t in TAG]
            print("\n[各窗口带符号 pitch（窗内行走样本归一；负=后仰）]")
            print("  注：窗口内无行走样本时显示 0.000（非真实读数）——timeout 组结尾恒为 stand 段"                  "故全 0，用 n_{tag} 列识别；该组不作为 pitch 判据组")
            print(walk.groupby("reason")[pc].median().round(3).to_string())

    if a.show:
        print("\n-- 逐 episode --")
        print(walk.to_string(index=False))

    if "fo_n" not in df.columns:
        return
    print("\n\n================ ⑧ 判别 pass：腾空是因还是果？ ================")
    grp = walk.assign(g=np.where(walk.reason == "timeout", "稳定(timeout)",
                                 np.where(walk.reason == "h<0.45", "失败(h<0.45)", "失败(姿态)")))
    TAG = ["2000ms", "1000ms", "500ms", "100ms"]
    cols = ["fl", "ds", "aroll", "adroll", "apitch", "h", "sat", "satleg"]
    print("注：各量在窗内**行走样本**上归一（timeout 结尾为 stand 段，其窗口为空 → 由 n_* 列识别；"
          "下表为组中位，含空窗不影响中位）")

    for tag in TAG:
        tb = grp.groupby("g")[[f"{c}_{tag}" for c in cols]].median().round(3)
        tb.columns = cols
        tb["n_walk"] = grp.groupby("g")[f"n_{tag}"].median().round(0)
        print(f"\n[终止前 {tag}]")
        print(tb.to_string())

    f = grp[grp.g != "稳定(timeout)"]
    print("\n[失败组：越接近终止 vs 2.0s 窗 的比值（>1 = 该量在恶化）]")
    for tag in ("1000ms", "500ms", "100ms"):
        r = {c: f[f"{c}_{tag}"].median() / max(abs(f[f"{c}_2000ms"].median()), 1e-9)
             for c in ("fl", "ds", "aroll", "adroll", "apitch", "sat")}
        print(f"  {tag:>7s}: 腾空 {r['fl']:.2f}x | 双支撑 {r['ds']:.2f}x | |roll| {r['aroll']:.2f}x | "
              f"|roll_rate| {r['adroll']:.2f}x | |pitch| {r['apitch']:.2f}x | τ饱和 {r['sat']:.2f}x")
    dh = (f["h_100ms"].median() - f["h_2000ms"].median()) * 100
    print(f"  高度：2.0s 窗均值 {f['h_2000ms'].median():.3f}m → 0.1s 窗 {f['h_100ms'].median():.3f}m（{dh:+.1f}cm）")

    print("\n[腾空发生时刻的性质（per-episode 聚合，中位）——真 bound vs 塌陷卸载]")
    print(grp.groupby("g")[["fo_n", "fo_h_mean", "fo_h_min", "fo_h_lt052_pct", "fo_roll_mean",
                            "fo_roll_max", "fo_absin_mean", "fo_lost_support_pct", "fo_prev_both_pct",
                            "fo_last_h", "fo_last_roll"]].median().round(3).to_string())
    print("\n[腾空时长分桶]")
    print(grp.groupby("g")[["fl_ev_50ms", "fl_ev_100ms", "fl_ev_150ms", "fl_max_ms"]]
          .agg(["median", "mean"]).round(2).to_string())

    st_ = grp[grp.g == "稳定(timeout)"]
    r1 = {c: f[f"{c}_1000ms"].median() / max(abs(f[f"{c}_2000ms"].median()), 1e-9)
          for c in ("fl", "aroll", "adroll", "sat")}
    print("\n[判读提示（自动）]")
    print(f"  稳定组腾空发生时刻的高度：中位 {st_['fo_h_mean'].median():.3f}m，"
          f"低于 0.52m 的占 {st_['fo_h_lt052_pct'].median():.1f}% → "
          f"{'腾空多发生在正常高度（真 bound）' if st_['fo_h_mean'].median() > 0.55 else '腾空多发生在低位（卸载）'}")
    if r1["aroll"] > 1.15 and r1["fl"] < 1.15:
        print("  1.0s 窗：|roll| 已升而腾空未升 → 倾向 H2（平衡/姿态先恶化，腾空是果）")
    elif r1["fl"] > 1.15 and r1["aroll"] <= 1.15:
        print("  1.0s 窗：腾空已升而 |roll| 未升 → 倾向 H1（腾空先行，是触发器）")
    else:
        print(f"  1.0s 窗：两者同升（腾空 {r1['fl']:.2f}x / |roll| {r1['aroll']:.2f}x）→ 需看 0.1s 与 "
              f"|roll_rate| {r1['adroll']:.2f}x 判断先后")
    if r1["sat"] > 1.5:
        print(f"  1.0s 窗力矩饱和 {r1['sat']:.2f}x → 存在 H3（腿力矩饱和/关节塌陷）成分")
    else:
        print(f"  1.0s 窗力矩饱和仅 {r1['sat']:.2f}x → H3（力矩饱和）证据不足")


if __name__ == "__main__":
    main()
