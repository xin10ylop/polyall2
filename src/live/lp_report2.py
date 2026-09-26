import sys, os, numpy as np, collections
sys.path.insert(0, os.path.dirname(__file__))
import sim_lp as S
snaps, cfg, trades = S.load(sys.argv[1] if len(sys.argv) > 1 else "weather")
span = (snaps[-1]["ts"] - snaps[0]["ts"]) / 3600
print(f"snapshots={len(snaps)} span_h={span:.2f}")
for d in [0.01, 0.02]:
    res = S.simulate(snaps, cfg, trades, d=d, hmin=12, hmax=1e9)
    b = collections.defaultdict(lambda: [0, 0.0, 0.0, []])
    for cid, r in res.items():
        if r["q_samples"] == 0: continue
        pm = np.median(r["mids"]); k = next(x for x in [0.03, 0.1, 0.3, 0.6, 0.9, 1.01] if pm < x)
        b[k][0] += 1; b[k][1] += r["reward"] / span * 24; b[k][2] += r["cap"]; b[k][3].append(r["share_sum"] / r["q_samples"])
    for k in sorted(b):
        n, rew, cap, sh = b[k]
        print(f"d={d} mid<{k}: markets={n} reward/day=${rew:.0f} per_mkt=${rew / n:.2f} capital=${cap:.0f} reward/$cap/day={rew / cap:.3f} median_share={np.median(sh):.2f}")
