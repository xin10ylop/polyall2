"""Executable backtest: buy NO (taker) on mentions markets when YES mid is in [lo, hi].
Decision times: 3-hourly clock marks while market open, from createdAt+min_age_h until endDate - min_left_h (no future info).
One entry per market (first qualifying time). Entry price for NO:
   q = max(1 - p_mid + hs, first taker NO-buy price within 30 min after t (if any))   (conservative)
Fee: rate*q*(1-q) per share. Hold to resolution. Inference clustered by event.
"""
import os, sys, json, glob, gzip
import numpy as np, pandas as pd, datetime as dt
ROOT = os.path.join(os.path.dirname(__file__), "../..")

def ts(s):
    if not s: return np.nan
    s = s.replace(" ", "T")
    if s.endswith("+00"): s += ":00"
    try: return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception: return np.nan

def load(fee_type="mentions_fees"):
    meta = {}
    for fn in glob.glob(f"{ROOT}/data/raw/markets/*.jsonl"):
        for l in open(fn):
            m = json.loads(l)
            if m.get("feeType") == fee_type: meta[m["conditionId"]] = m
    data = []
    for cid, m in meta.items():
        phf = f"{ROOT}/data/raw/ph/{cid}.json"; trf = f"{ROOT}/data/raw/trades/{cid}.csv.gz"
        if not (os.path.exists(phf) and os.path.exists(trf)): continue
        ph = json.load(open(phf))
        if len(ph["t"]) < 5: continue
        try: op = [float(x) for x in json.loads(m["outcomePrices"])]
        except Exception: continue
        if len(op) != 2 or max(op) < 0.99: continue
        try: tr = pd.read_csv(trf)
        except Exception: tr = pd.DataFrame(columns=["ts", "side", "oi", "price", "size", "wallet"])
        tr = tr.sort_values("ts")
        buy = tr.side == "B"
        tr["tok"] = np.where(buy, tr.oi, 1 - tr.oi); tr["q"] = np.where(buy, tr.price, 1 - tr.price)
        fs = m.get("feeSchedule") or {}
        data.append(dict(cid=cid, ev=m.get("eventId"), q=m["question"], y=int(op[0] > 0.5),
                         created=ts(m.get("createdAt")), end=ts(m.get("endDate")), closed=ts(m.get("closedTime")),
                         rate=fs.get("rate", 0) if m.get("feesEnabled") else 0,
                         t=np.array(ph["t"]), p=np.array(ph["p"]), tr=tr[["ts", "tok", "q", "size"]].values))
    return data

def backtest(data, lo, hi, side="NO", min_age_h=2, min_left_h=1, max_left_h=1e9, hs=0.01, step_h=3):
    rows = []
    for d in data:
        t0 = d["created"] + min_age_h * 3600
        t_end = min(d["end"], d["closed"]) - min_left_h * 3600
        o = np.argsort(d["t"]); T = d["t"][o]; P = d["p"][o]
        t = np.ceil(t0 / (step_h * 3600)) * step_h * 3600
        while t < t_end:
            left_h = (min(d["end"], d["closed"]) - t) / 3600   # uses closed only to stop (market no longer tradable)
            if left_h <= max_left_h:
                i = np.searchsorted(T, t, side="right") - 1
                if i >= 0 and t - T[i] < 3 * 3600:
                    p = P[i]
                    if lo <= p <= hi:
                        tr = d["tr"]
                        want = 1 if side == "NO" else 0
                        base = (1 - p + hs) if side == "NO" else (p + hs)
                        mask = (tr[:, 0] > t) & (tr[:, 0] <= t + 1800) & (tr[:, 1] == want)
                        q = max(base, tr[mask, 2][0]) if mask.any() else base
                        q = min(q, 0.999)
                        win = (1 - d["y"]) if side == "NO" else d["y"]
                        fee = d["rate"] * q * (1 - q)
                        rows.append(dict(cid=d["cid"], ev=d["ev"], t=t, p=p, q=q, fee=fee, win=win, left_h=left_h,
                                         roi=(win - q - fee) / (q + fee), month=dt.datetime.utcfromtimestamp(t).month, question=d["q"]))
                        break
            t += step_h * 3600
    return pd.DataFrame(rows)

def report(R, label=""):
    if R.empty: print(label, "no trades"); return
    ev = R.groupby("ev").roi.mean()
    se = ev.std(ddof=1) / np.sqrt(len(ev)) if len(ev) > 1 else np.nan
    print(f"{label} n={len(R)} events={len(ev)} win={R.win.mean():.3f} avg_q={R.q.mean():.3f} ROI={R.roi.mean():+.4f} "
          f"evROI={ev.mean():+.4f} se_ev={se:.4f} t={ev.mean()/se if se else np.nan:.2f} med_left_h={R.left_h.median():.1f}")

if __name__ == "__main__":
    data = load(sys.argv[1] if len(sys.argv) > 1 else "mentions_fees")
    print("markets loaded", len(data))
    for lo, hi in [(0.02, 0.1), (0.05, 0.15), (0.1, 0.2), (0.15, 0.3), (0.2, 0.35), (0.3, 0.5), (0.5, 0.7), (0.7, 0.9)]:
        R = backtest(data, lo, hi, "NO")
        report(R, f"NO  yes∈[{lo},{hi}] ALL ")
        report(R[R.month <= 6], "      May-Jun")
        report(R[R.month >= 7], "      Jul-Sep")
