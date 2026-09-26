"""Paper-simulate a small two-sided liquidity-reward quoting policy on recorded live books + trades.

For each market and each recorded minute:
  * adjusted mid m0 from book levels with cumulative size >= min_size (size-cutoff-adjusted midpoint)
  * our quotes: bid = max(adj_bb, m0 - d), ask = min(adj_ba, m0 + d) on a 0.01 grid (0.001 if price<0.1 or >0.9),
    N shares each side; quote only if both within v cents of the new mid and bid < ask
  * our Q_min = min(Q_one, Q_two) (two-sided)
  * competitors aggregated as ONE maker: Q_comp = rule(min/max of their side totals)  -> upper bound on
    sum of competitors' Q_min, hence our share is a LOWER bound (conservative)
  * reward per sample = share * rate/1440  (epoch normalisation approximated by avg share over the day)
Fills: from recorded taker trades normalised to YES-price. A taker SELL of YES (or BUY of NO) at yes-price p hits our bid
if p <= bid (at-level: pro-rata to our share of the level; through: p < bid fully). Symmetric for asks.
Inventory is tracked; fills are marked at the final outcome if known (outcomes file), else at the last mid.
"""
import os, sys, gzip, json, glob, math, collections
import numpy as np
import datetime as dt
ROOT = os.path.join(os.path.dirname(__file__), "../..")

def adj_levels(levels, min_size, side):
    # levels: list of (price,size) sorted best-first; return price where cumulative size reaches min_size
    cum = 0
    for p, s in levels:
        cum += s
        if cum >= min_size: return p
    return None

def S(v, s): return max(0.0, (v - s) / v) ** 2 if s < v else 0.0

def tick_for(p): return 0.001 if (p < 0.1 or p > 0.9) else 0.01

def load(tag):
    snaps = []
    for fn in sorted(glob.glob(f"{ROOT}/data/live/{tag}/books_*.jsonl.gz")):
        for l in gzip.open(fn, "rt"):
            try: snaps.append(json.loads(l))
            except Exception: pass
    cfg = {}
    for fn in sorted(glob.glob(f"{ROOT}/data/live/{tag}/configs_*.jsonl.gz")):
        for l in gzip.open(fn, "rt"):
            try:
                d = json.loads(l)
                for m in d["markets"]: cfg[m["cid"]] = m
            except Exception: pass
    trades = collections.defaultdict(list)
    for fn in sorted(glob.glob(f"{ROOT}/data/live/{tag}/trades_*.jsonl.gz")):
        for l in gzip.open(fn, "rt"):
            try: t = json.loads(l)
            except Exception: continue
            m = cfg.get(t["cid"])
            if not m: continue
            if t["asset"] == m["yes"]:
                p = t["price"]; hits = "ask" if t["side"] == "BUY" else "bid"
            else:
                p = 1 - t["price"]; hits = "bid" if t["side"] == "BUY" else "ask"
            trades[t["cid"]].append((t["ts"], p, t["size"], hits))
    for k in trades: trades[k].sort()
    return snaps, cfg, trades

def simulate(snaps, cfg, trades, N=None, d=0.015, fill_mode="at", min_rate=0.0, outcomes=None, max_inv=None, hmin=-1e9, hmax=1e9,
             local0=None, lhmin=None, only_temp=False):
    res = collections.defaultdict(lambda: {"reward": 0.0, "samples": 0, "q_samples": 0, "fills": [], "share_sum": 0.0})
    last_ts = {}
    for si, snap in enumerate(snaps):
        ts = snap["ts"]
        for cid, bk in snap["books"].items():
            m = cfg.get(cid)
            if not m or m["rate"] < min_rate or not bk.get("b") and not bk.get("a"): continue
            try:
                _e = dt.datetime.fromisoformat(m["end"].replace(" ", "T").replace("+00", "+00:00")).timestamp()
            except Exception:
                continue
            hte = (_e - ts) / 3600
            if not (hmin <= hte < hmax): continue
            if only_temp and "temperature" not in (m["q"] or "").lower(): continue
            if local0 is not None:
                l0 = local0.get(cid)
                if l0 is None: continue
                if (l0 - ts) / 3600 < lhmin: continue   # hours before station-local midnight of target day
            v = (m["v"] or 4.5) / 100.0; mn = m["min"] or 20
            n = N or mn
            bids = sorted(bk["b"], key=lambda x: -x[0]); asks = sorted(bk["a"], key=lambda x: x[0])
            abb = adj_levels(bids, mn, "b"); aba = adj_levels(asks, mn, "a")
            if abb is None and aba is None: continue
            if abb is None: abb = max(0.0, aba - 2 * v)
            if aba is None: aba = min(1.0, abb + 2 * v)
            m0 = (abb + aba) / 2
            tk = tick_for(m0)
            our_b = max(abb, math.floor((m0 - d) / tk + 1e-9) * tk)
            our_a = min(aba, math.ceil((m0 + d) / tk - 1e-9) * tk)
            our_b = round(max(tk, our_b), 4); our_a = round(min(1 - tk, our_a), 4)
            r = res[cid]; r["samples"] += 1
            if our_b >= our_a: continue
            m1 = (max(abb, our_b) + min(aba, our_a)) / 2
            sb = (m1 - our_b) * 100; sa = (our_a - m1) * 100
            vv = v * 100
            if sb >= vv or sa >= vv: continue
            q_ours = min(S(vv, sb) * n, S(vv, sa) * n)
            q1 = sum(S(vv, (m1 - p) * 100) * s for p, s in bids if (m1 - p) * 100 < vv)
            q2 = sum(S(vv, (p - m1) * 100) * s for p, s in asks if (p - m1) * 100 < vv)
            if 0.10 <= m1 <= 0.90: qc = max(min(q1, q2), max(q1, q2) / 3.0)
            else: qc = min(q1, q2)
            # conservative: count competitor Q as the larger side if two-sided anywhere
            qc_cons = max(q1, q2)
            share = q_ours / (q_ours + qc_cons) if q_ours > 0 else 0
            dt_min = 1.0 if cid not in last_ts else min(5.0, max(0.0, (ts - last_ts[cid]) / 60.0))
            last_ts[cid] = ts
            r["reward"] += share * m["rate"] / 1440.0 * dt_min
            r["q_samples"] += 1; r["share_sum"] += share
            r["cap"] = n * (our_b + (1 - our_a)); r["rate"] = m["rate"]; r.setdefault("mids", []).append(m1)
            # fills in (ts, ts+60]
            for (tt, p, sz, hits) in trades.get(cid, []):
                if tt <= ts or tt > ts + 60: continue
                if hits == "bid" and (p < our_b - 1e-9 or (fill_mode == "at" and abs(p - our_b) < 1e-9)):
                    lvl = sum(s for pp, s in bids if abs(pp - our_b) < 1e-9) + n
                    q = n if p < our_b - 1e-9 else min(n, sz * n / lvl)
                    r["fills"].append((tt, "buy", our_b, q, m1))
                if hits == "ask" and (p > our_a + 1e-9 or (fill_mode == "at" and abs(p - our_a) < 1e-9)):
                    lvl = sum(s for pp, s in asks if abs(pp - our_a) < 1e-9) + n
                    q = n if p > our_a + 1e-9 else min(n, sz * n / lvl)
                    r["fills"].append((tt, "sell", our_a, q, m1))
    return res

if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "weather"
    snaps, cfg, trades = load(tag)
    hours = (snaps[-1]["ts"] - snaps[0]["ts"]) / 3600 if snaps else 0
    print(f"snapshots={len(snaps)} span_h={hours:.2f} markets={len(cfg)} trades={sum(len(v) for v in trades.values())}")
    for d in [0.01, 0.02]:
        res = simulate(snaps, cfg, trades, d=d)
        tot = sum(r["reward"] for r in res.values())
        nq = sum(1 for r in res.values() if r["q_samples"] > 0)
        fills = [f for r in res.values() for f in r["fills"]]
        print(f"d={d}: quoted_markets={nq} reward_in_span=${tot:.2f} -> per_day=${tot / max(hours, 1e-9) * 24:.1f} fills={len(fills)} "
              f"fill_shares={sum(f[3] for f in fills):.0f}")
        top = sorted(res.items(), key=lambda kv: -kv[1]["reward"])[:12]
        for cid, r in top:
            print(f"   {cfg[cid]['q'][:70]:70s} rate={cfg[cid]['rate']:>5} share={r['share_sum'] / max(1, r['q_samples']):.2f} reward=${r['reward']:.3f} fills={len(r['fills'])}")
