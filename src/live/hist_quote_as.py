"""Historical adverse-selection cost of two-sided quoting around the 1-min price in weather temperature markets.
For each market & minute t: quotes bid = round_down(p_t - d), ask = round_up(p_t + d) (tick 0.01, 0.001 if p<0.1/p>0.9),
size N shares each; fills from real taker prints in (t, t+60]:
   mode 'through': fill only if print strictly beyond our price (guaranteed by price priority)
   mode 'at': also fill at-level (assume we are at front of queue: optimistic on fills)
Net-inventory cap per market; hold to resolution. Output: PnL per market-day by hours-to-endDate bucket.
"""
import os, sys, json, glob, gzip, math
import numpy as np, pandas as pd, datetime as dt
ROOT = os.path.join(os.path.dirname(__file__), "../..")
def ts(s):
    s = (s or "").replace(" ", "T")
    if s.endswith("+00"): s += ":00"
    try: return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception: return np.nan

def load(sample):
    cids = set(json.loads(l)["conditionId"] for l in open(sample))
    meta = {}
    for fn in glob.glob(f"{ROOT}/data/raw/markets/2026-0[789]-*.jsonl"):
        for l in open(fn):
            m = json.loads(l)
            if m["conditionId"] in cids: meta[m["conditionId"]] = m
    out = []
    for cid, m in meta.items():
        pf = f"{ROOT}/data/raw/ph10/{cid}.json"; tf = f"{ROOT}/data/raw/trades/{cid}.csv.gz"
        if not (os.path.exists(pf) and os.path.exists(tf)): continue
        ph = json.load(open(pf))
        if len(ph["t"]) < 30: continue
        try: tr = pd.read_csv(tf)
        except Exception: continue
        op = [float(x) for x in json.loads(m["outcomePrices"])]
        # normalise trades to YES price + which side of OUR book they hit
        buy = tr.side == "B"; yes = tr.oi == 0
        p_yes = np.where(yes, tr.price, 1 - tr.price)
        hits_ask = (buy & yes) | (~buy & ~yes)     # taker acquiring YES exposure
        out.append(dict(cid=cid, y=int(op[0] > 0.5), end=ts(m["endDate"]), closed=ts(m["closedTime"]), q=m["question"],
                        t=np.array(ph["t"]), p=np.array(ph["p"]),
                        tt=tr.ts.values, tp=p_yes, tsz=tr["size"].values, tha=hits_ask.values))
    return out

def run(data, d=0.02, N=20, cap=60, mode="through", hmin=-1e9, hmax=1e9, pmin=0.0, pmax=1.0):
    rows = []
    for m in data:
        o = np.argsort(m["t"]); T = m["t"][o]; P = m["p"][o]
        oo = np.argsort(m["tt"]); TT = m["tt"][oo]; TP = m["tp"][oo]; TS = m["tsz"][oo]; HA = m["tha"][oo]
        inv = 0.0; cash = 0.0; mins = 0; nf = 0
        for i in range(len(T)):
            t = T[i]; p = P[i]
            h = (m["end"] - t) / 3600
            if not (hmin <= h < hmax) or not (pmin <= p <= pmax) or t >= m["closed"]: continue
            mins += 1
            tk = 0.001 if (p < 0.1 or p > 0.9) else 0.01
            bid = math.floor((p - d) / tk + 1e-9) * tk; ask = math.ceil((p + d) / tk - 1e-9) * tk
            j0 = np.searchsorted(TT, t, side="right"); j1 = np.searchsorted(TT, t + 60, side="right")
            for j in range(j0, j1):
                pr = TP[j]
                if HA[j]:   # taker buys YES -> hits our ask
                    ok = pr > ask + 1e-9 or (mode == "at" and pr >= ask - 1e-9)
                    if ok and bid > 0 and inv > -cap:
                        q = min(N, cap + inv); inv -= q; cash += q * ask; nf += 1
                else:       # taker sells YES -> hits our bid
                    ok = pr < bid - 1e-9 or (mode == "at" and pr <= bid + 1e-9)
                    if ok and bid > 0 and inv < cap:
                        q = min(N, cap - inv); inv += q; cash -= q * bid; nf += 1
        if mins == 0: continue
        pnl = cash + inv * m["y"]
        rows.append(dict(cid=m["cid"], mins=mins, fills=nf, pnl=pnl, inv=inv))
    return pd.DataFrame(rows)

if __name__ == "__main__":
    data = load(sys.argv[1] if len(sys.argv) > 1 else f"{ROOT}/data/sample_weather_recent.jsonl")
    print("markets", len(data))
    for mode in ["through", "at"]:
        for d in [0.01, 0.02, 0.03]:
            for (hmin, hmax) in [(24, 1e9), (12, 24), (0, 12), (-24, 0)]:
                R = run(data, d=d, mode=mode, hmin=hmin, hmax=hmax)
                if R.empty: continue
                qh = R.mins.sum() / 60
                print(f"{mode:8s} d={d:.2f} h_to_end[{hmin},{hmax}) mkts={len(R)} quote_hours={qh:.0f} fills={R.fills.sum()} "
                      f"PnL=${R.pnl.sum():.1f}  per_quote_hour=${R.pnl.sum() / qh:.4f}  per_mkt_day=${R.pnl.sum() / qh * 24:.3f}")
