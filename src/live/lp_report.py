import sys, os, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
import sim_lp as S
snaps, cfg, trades = S.load(sys.argv[1] if len(sys.argv) > 1 else "weather")
span = (snaps[-1]["ts"] - snaps[0]["ts"]) / 3600
print(f"snapshots={len(snaps)} span_h={span:.2f}")
for d in [0.01, 0.02]:
    for hmin, hmax in [(12, 1e9), (24, 1e9)]:
        res = S.simulate(snaps, cfg, trades, d=d, hmin=hmin, hmax=hmax)
        rows = [(cid, r["reward"] / span * 24, r.get("cap", 0), r["share_sum"] / max(1, r["q_samples"]), r.get("rate", 0))
                for cid, r in res.items() if r["q_samples"] > 0]
        rows.sort(key=lambda x: -x[1])
        tot = sum(x[1] for x in rows); cap = sum(x[2] for x in rows)
        top = rows[:30]
        print(f"d={d} h_to_end>={hmin}: markets={len(rows)} est_reward/day=${tot:.0f} capital=${cap:.0f}  "
              f"top30 reward/day=${sum(x[1] for x in top):.0f} top30 capital=${sum(x[2] for x in top):.0f}  "
              f"median share={np.median([x[3] for x in rows]):.2f}")
