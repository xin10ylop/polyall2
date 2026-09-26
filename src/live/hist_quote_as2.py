"""Fast historical adverse-selection estimate for two-sided quoting around the 1-min price series.
Per trade (not per minute): our quotes at trade time are set from the last 1-min price p (<=120 s old):
bid = floor(p-d), ask = ceil(p+d). A taker print that is strictly through (mode=through) or at/through (mode=at)
our level fills N shares (inventory capped at +-cap). Hold to resolution. Returns per-market PnL, quote-hours, fills.
Window filter by hours-to-endDate [hmin,hmax) and optional price range [pmin,pmax].
"""
import os, sys, json, glob, math
import numpy as np, pandas as pd, datetime as dt
ROOT = os.path.join(os.path.dirname(__file__), "../..")
def ts(s):
    s = (s or "").replace(" ", "T")
    if s.endswith("+00"): s += ":00"
    try: return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception: return np.nan

def load(sample, phdir="ph10"):
    rows = [json.loads(l) for l in open(sample)]
    cids = {r["conditionId"]: r.get("feeType") for r in rows}
    meta = {}
    for fn in glob.glob(f"{ROOT}/data/raw/markets/*.jsonl"):
        for l in open(fn):
            m = json.loads(l)
            if m["conditionId"] in cids: meta[m["conditionId"]] = m
    out = []
    for cid, m in meta.items():
        pf = f"{ROOT}/data/raw/{phdir}/{cid}.json"; tf = f"{ROOT}/data/raw/trades/{cid}.csv.gz"
        if not (os.path.exists(pf) and os.path.exists(tf)): continue
        ph = json.load(open(pf))
        if len(ph["t"]) < 30: continue
        try: tr = pd.read_csv(tf)
        except Exception: continue
        if tr.empty: continue
        op = [float(x) for x in json.loads(m["outcomePrices"])]
        buy = (tr.side == "B").values; yes = (tr.oi == 0).values
        p_yes = np.where(yes, tr.price.values, 1 - tr.price.values)
        hits_ask = (buy & yes) | (~buy & ~yes)
        o = np.argsort(ph["t"]); T = np.array(ph["t"])[o]; P = np.array(ph["p"])[o]
        oo = np.argsort(tr.ts.values)
        out.append(dict(cid=cid, ft=m.get("feeType") or "none", q=m["question"], ev=m.get("eventTitle"), desc=(m.get("description") or "")[:600],
                        y=int(op[0] > 0.5), end=ts(m["endDate"]), closed=ts(m["closedTime"]), created=ts(m.get("createdAt")),
                        T=T, P=P, TT=tr.ts.values[oo], TP=p_yes[oo], HA=hits_ask[oo]))
    return out

def run_one(m, d=0.02, N=20, cap=60, mode="through", hmin=-1e9, hmax=1e9, pmin=0.0, pmax=1.0):
    T, P = m["T"], m["P"]
    hte = (m["end"] - T) / 3600
    live = (hte >= hmin) & (hte < hmax) & (P >= pmin) & (P <= pmax) & (T < m["closed"])
    mins = int(live.sum())
    if mins == 0: return None
    inv = 0.0; cash = 0.0; nf = 0
    idx = np.searchsorted(T, m["TT"], side="right") - 1
    for k in range(len(m["TT"])):
        i = idx[k]
        if i < 0 or not live[i] or m["TT"][k] - T[i] > 120: continue
        p = P[i]
        tk = 0.001 if (p < 0.1 or p > 0.9) else 0.01
        bid = math.floor((p - d) / tk + 1e-9) * tk; ask = math.ceil((p + d) / tk - 1e-9) * tk
        if bid <= 0 or ask >= 1: continue
        pr = m["TP"][k]
        if m["HA"][k]:
            if (pr > ask + 1e-9 or (mode == "at" and pr >= ask - 1e-9)) and inv > -cap:
                q = min(N, cap + inv); inv -= q; cash += q * ask; nf += 1
        else:
            if (pr < bid - 1e-9 or (mode == "at" and pr <= bid + 1e-9)) and inv < cap:
                q = min(N, cap - inv); inv += q; cash -= q * bid; nf += 1
    return dict(cid=m["cid"], ft=m["ft"], mins=mins, fills=nf, pnl=cash + inv * m["y"], inv=inv)

def run(data, **kw):
    return pd.DataFrame([r for r in (run_one(m, **kw) for m in data) if r])

if __name__ == "__main__":
    sample = sys.argv[1]
    data = load(sample)
    print("markets", len(data))
    for d in [0.01, 0.02, 0.03]:
        for (hmin, hmax) in [(72, 1e9), (24, 72), (12, 24), (0, 12), (-48, 0)]:
            R = run(data, d=d, hmin=hmin, hmax=hmax)
            if R.empty: continue
            g = R.groupby("ft").agg(mk=("cid", "size"), mins=("mins", "sum"), fills=("fills", "sum"), pnl=("pnl", "sum"))
            g["per_mkt_day"] = g.pnl / (g.mins / 1440)
            print(f"d={d} h[{hmin},{hmax}) ALL per_mkt_day=${R.pnl.sum() / (R.mins.sum() / 1440):.3f}  | " +
                  "  ".join(f"{k[:8]}:{v:.2f}" for k, v in g.per_mkt_day.items()))
