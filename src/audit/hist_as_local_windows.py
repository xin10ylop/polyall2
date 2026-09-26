"""Re-run the audited AS simulator (hist_as_audit.run_one) on the lead's local-time windows (research/09 table) with and
without the print-size cap, so the two tables can be compared directly. h = hours before local midnight of target day D.
Usage: python src/audit/hist_as_local_windows.py"""
import os, sys, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from hist_as_audit import load, run, summary, ROOT
W = [(24, 1e9, "before D-1 00:00"), (12, 24, "D-1 00-12"), (6, 12, "D-1 12-18"), (0, 6, "D-1 18-24"), (-6, 0, "D 00-06"),
     (-10, -6, "D 06-10"), (-14, -10, "D 10-14"), (-30, -14, "D 14-end")]
data = load(f"{ROOT}/data/sample_weather_recent.jsonl")
out = []
for size_cap in [False, True]:
    for d in [0.01, 0.02, 0.03]:
        for hmin, hmax, lab in W:
            R = run(data, d=d, mode="through", clock="hobs", hmin=hmin, hmax=hmax, size_cap=size_cap)
            s = summary(R); s.update(size_cap=size_cap, d=d, win=lab); out.append(s)
            print(f"cap={size_cap!s:5s} d={d:.2f} {lab:18s} mkt_days={s['mkt_days']:6.0f} sh/mkt-day={s['sh_per_mkt_day']:6.1f} "
                  f"PnL/mkt-day=${s['pnl_per_mkt_day']:7.2f} (spread {s['spread_per_mkt_day']:5.2f}, markout {s['markout_per_mkt_day']:7.2f}) "
                  f"PnL/share={s['pnl_per_share'] * 100:+.2f}c", flush=True)
pd.DataFrame(out).to_csv(os.path.join(os.path.dirname(__file__), "hist_as_local_windows.csv"), index=False)
