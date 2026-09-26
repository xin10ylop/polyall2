"""Reward per QUOTED market-day for a disciplined small LP (daily temperature buckets, two-sided books, quoting only
until station-local midnight that starts the observation day D), on recorded live books (src/live/recorder.py).

Variants (min-size quote each side):
  LEAD   : sim_lp policy -- quote at max(adj best, mid -/+ d), i.e. improve the book when it is wider than d.
  LEAD+R : same, but whenever we would be the sole scorer a rival farmer matches us (share capped at 0.5).
  JOIN   : never improve the book: rest at the adjusted best bid/ask only if both are within v of the adjusted mid.
Competitor sum of Q_min is bracketed: upper = max(q1,q2) (sim_lp's choice -> our share LOW), lower = max(q1,q2)/3 for mid in
[0.1,0.9] (each maker scores >= its larger side / 3) or min(q1,q2) outside (-> our share HIGH).
Usage: python src/audit/reward_bounds.py [tag] [d=0.01]
"""
import os, sys, math, datetime as dt
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../live")); sys.path.insert(0, os.path.dirname(__file__))
import sim_lp as S
from sim_lp_audit import obs_start_live, DAILY


def run(snaps, cfg, d=0.01, hmin=0.0):
    rows = []; last = {}
    for snap in snaps:
        ts = snap["ts"]
        for cid, bk in snap["books"].items():
            m = cfg.get(cid)
            if not m or not DAILY.search(m["q"] or "") or not bk.get("b") or not bk.get("a"): continue
            try: end = dt.datetime.fromisoformat(m["end"].replace(" ", "T").replace("+00", "+00:00")).timestamp()
            except Exception: continue
            o = obs_start_live(m["q"], end)
            if not np.isfinite(o) or (o - ts) / 3600 < hmin: continue
            v = m["v"] or 4.5; mn = m["min"] or 20; n = mn
            bids = sorted(bk["b"], key=lambda x: -x[0]); asks = sorted(bk["a"], key=lambda x: x[0])
            abb = S.adj_levels(bids, mn, "b"); aba = S.adj_levels(asks, mn, "a")
            if abb is None or aba is None: continue
            gap = min(5.0, (ts - last[cid]) / 60) if cid in last else 1.0; last[cid] = ts
            m0 = (abb + aba) / 2; rec = dict(cid=cid, ts=ts, rate=m["rate"], dt=gap, spread=aba - abb)
            # LEAD (sim_lp policy)
            tk = S.tick_for(m0)
            ob = round(max(tk, max(abb, math.floor((m0 - d) / tk + 1e-9) * tk)), 4); oa = round(min(1 - tk, min(aba, math.ceil((m0 + d) / tk - 1e-9) * tk)), 4)
            for name, (b_, a_, mid) in {"LEAD": (ob, oa, (ob + oa) / 2), "JOIN": (abb, aba, m0)}.items():
                sb, sa = (mid - b_) * 100, (a_ - mid) * 100
                if b_ >= a_ or sb >= v or sa >= v:
                    rec[f"{name}_lo"] = rec[f"{name}_hi"] = 0.0; rec[f"{name}_q"] = False; rec[f"{name}_sole"] = False; continue
                q = n * min(S.S(v, sb), S.S(v, sa))
                q1 = sum(S.S(v, (mid - p) * 100) * s for p, s in bids if (mid - p) * 100 < v)
                q2 = sum(S.S(v, (p - mid) * 100) * s for p, s in asks if (p - mid) * 100 < v)
                if name == "JOIN":  # our order sits in the same levels as competitors: remove nothing, competitors are the book
                    pass
                up = max(q1, q2); lo = max(q1, q2) / 3 if 0.1 <= mid <= 0.9 else min(q1, q2)
                rec[f"{name}_lo"] = q / (q + up) if q > 0 else 0.0
                rec[f"{name}_hi"] = q / (q + lo) if q > 0 else 0.0
                rec[f"{name}_q"] = q > 0; rec[f"{name}_sole"] = up <= 1e-9
                rec[f"{name}_cap"] = n * (b_ + 1 - a_)
            rows.append(rec)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "weather"; d = float(sys.argv[2]) if len(sys.argv) > 2 else 0.01
    snaps, cfg, _ = S.load(tag)
    D = run(snaps, cfg, d=d)
    hrs = sorted(set(pd.to_datetime(D.ts, unit="s").dt.strftime("%H")))
    print(f"snapshots={len(snaps)} UTC hours covered={hrs}; pre-observation daily-temp two-sided market-minutes={len(D)}, markets={D.cid.nunique()}")
    conc = D.groupby("ts").cid.nunique().median(); print(f"concurrently eligible markets (median per snapshot): {conc:.0f}")
    w = D.dt
    for name in ["LEAD", "JOIN"]:
        qd = D[D[f"{name}_q"]]
        frac = (w * D[f"{name}_q"]).sum() / w.sum()
        lo = (qd[f"{name}_lo"] * qd.rate * qd.dt).sum() / qd.dt.sum(); hi = (qd[f"{name}_hi"] * qd.rate * qd.dt).sum() / qd.dt.sum()
        cap = qd.groupby("cid")[f"{name}_cap"].mean().mean()
        print(f"{name:5s}: quotable {frac:.0%} of market-minutes; reward per quoted market-day ${lo:.2f} (share vs max(q1,q2)) .. ${hi:.2f} "
              f"(share vs lower bound); median share {qd[f'{name}_lo'].median():.2f}..{qd[f'{name}_hi'].median():.2f}; quote capital/market ${cap:.1f}")
        if name == "LEAD":
            r = qd.copy()
            for k in ["lo", "hi"]: r.loc[r.LEAD_sole, f"LEAD_{k}"] = np.minimum(r.loc[r.LEAD_sole, f"LEAD_{k}"], 0.5)
            lo = (r.LEAD_lo * r.rate * r.dt).sum() / r.dt.sum(); hi = (r.LEAD_hi * r.rate * r.dt).sum() / r.dt.sum()
            print(f"LEAD+R: reward per quoted market-day ${lo:.2f} .. ${hi:.2f}; sole-scorer minutes {(r.LEAD_sole * r.dt).sum() / r.dt.sum():.0%}")
