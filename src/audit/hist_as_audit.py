"""AUDIT version of the historical adverse-selection simulator (src/live/hist_quote_as.py).

Fixes / changes vs the original (see research/audit_lp_rewards.md, section 1b):
  * fill size is capped by the taker print size (original: every crossing print fills the full N shares,
    even a 1-share print), and our resting size depletes within a minute (original: instantly replenished);
  * ask-side eligibility uses ask < 1 (original required bid > 0 on BOTH sides -> tails never quoted);
  * quotes are re-centred on the most recent 1-min midpoint at or before the trade (<=120 s old);
  * windows are measured against the LOCAL observation day of the city (the endDate of temperature markets is
    12:00 UTC of the observation date, which for East-Asia/Oceania is at or after the end of the local day and for
    the Americas is 8-10 h into it) -- 'h_obs' = hours until local midnight that starts the observation day;
  * PnL is decomposed into spread capture (fill price vs mid at fill) and markout (mid at fill -> resolution).
Rewards are NOT modelled here (see wallet ground truth in the audit note).

Usage: python src/audit/hist_as_audit.py [sample.jsonl]
"""
import os, sys, json, glob, math, re
import numpy as np, pandas as pd, datetime as dt

ROOT = os.path.join(os.path.dirname(__file__), "../..")
TZ = {"Paris": 2, "Hong Kong": 8, "New York City": -4, "London": 1, "Tokyo": 9, "Seoul (Incheon)": 9, "Seoul": 9, "Miami": -4,
      "Shanghai": 8, "Madrid": 2, "San Francisco": -7, "Seattle": -7, "Los Angeles": -7, "Shenzhen": 8, "Beijing": 8, "Milan": 2,
      "Taipei": 8, "Wuhan": 8, "Kuala Lumpur": 8, "Guangzhou": 8, "Moscow": 3, "Manila": 8, "Munich": 2, "Wellington": 12,
      "Chengdu": 8, "Dallas": -5, "Denver": -6, "Ankara": 3, "Cape Town": 2, "Buenos Aires": -3, "Chongqing": 8, "Jeddah": 3,
      "Qingdao": 8, "Amsterdam": 2, "Sao Paulo": -3, "Atlanta": -4, "Austin": -5, "Istanbul": 3, "Tel Aviv": 3, "Warsaw": 2,
      "Singapore": 8, "Chicago": -5, "Busan": 9, "Helsinki": 3, "Karachi": 5, "Houston": -5, "Lucknow": 5.5, "Panama City": -5,
      "Mexico City": -6, "Toronto": -4, "Zhengzhou": 8, "Jinan": 8, "Hong Kong SAR": 8}
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September",
                                      "October", "November", "December"], 1)}


def ts(s):
    s = (s or "").replace(" ", "T")
    if s.endswith("+00"): s += ":00"
    try: return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception: return np.nan


def obs_start(q, end_ts):
    """UTC timestamp of local midnight starting the observation day, or nan."""
    mc = re.search(r"(?:temperature|precipitation) in (.+?) (?:be|on|have)", q)
    md = re.search(r"on (" + "|".join(MONTHS) + r") (\d{1,2})", q)
    if not mc or not md or mc.group(1) not in TZ or not np.isfinite(end_ts): return np.nan
    y = dt.datetime.utcfromtimestamp(end_ts).year
    d0 = dt.datetime(y, MONTHS[md.group(1)], int(md.group(2)), tzinfo=dt.timezone.utc).timestamp()
    return d0 - TZ[mc.group(1)] * 3600


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
        if tr.empty: continue
        op = [float(x) for x in json.loads(m["outcomePrices"])]
        if max(op) < 0.99: continue  # unresolved / 50-50
        buy = (tr.side == "B").values; yes = (tr.oi == 0).values
        p_yes = np.where(yes, tr.price.values, 1 - tr.price.values)
        hits_ask = (buy & yes) | (~buy & ~yes)
        o = np.argsort(ph["t"]); T = np.array(ph["t"], dtype=float)[o]; P = np.array(ph["p"], dtype=float)[o]
        oo = np.argsort(tr.ts.values, kind="stable")
        end = ts(m["endDate"])
        out.append(dict(cid=cid, q=m["question"], y=int(op[0] > 0.5), end=end, closed=ts(m["closedTime"]),
                        obs=obs_start(m["question"], end), T=T, P=P, TT=tr.ts.values[oo].astype(float), TP=p_yes[oo],
                        TS=tr["size"].values[oo].astype(float), HA=hits_ask[oo]))
    return out


def run_one(m, d=0.02, N=20, cap=60, mode="through", clock="hobs", hmin=-1e9, hmax=1e9, pmin=0.0, pmax=1.0, size_cap=True):
    T, P = m["T"], m["P"]
    ref = m["obs"] if clock == "hobs" else m["end"]
    if not np.isfinite(ref): return None
    h = (ref - T) / 3600
    live = (h >= hmin) & (h < hmax) & (P >= pmin) & (P <= pmax) & (T < m["closed"]) & (P > 0.0) & (P < 1.0)
    mins = int(live.sum())
    if mins == 0: return None
    inv = 0.0; cash = 0.0; nf = 0; sh = 0.0; spread_cap = 0.0; mark = 0.0
    rem_b = {}; rem_a = {}
    idx = np.searchsorted(T, m["TT"], side="right") - 1
    for k in range(len(m["TT"])):
        i = idx[k]
        if i < 0 or not live[i] or m["TT"][k] - T[i] > 120: continue
        p = P[i]
        tk = 0.001 if (p < 0.1 or p > 0.9) else 0.01
        bid = round(math.floor((p - d) / tk + 1e-9) * tk, 4); ask = round(math.ceil((p + d) / tk - 1e-9) * tk, 4)
        pr = m["TP"][k]; psz = m["TS"][k] if size_cap else 1e18
        if m["HA"][k]:
            if ask >= 1: continue
            if (pr > ask + 1e-9 or (mode == "at" and pr >= ask - 1e-9)) and inv > -cap:
                r = rem_a.get(i, N)
                q = min(r, cap + inv, psz)
                if q <= 0: continue
                rem_a[i] = r - q; inv -= q; cash += q * ask; nf += 1; sh += q
                spread_cap += q * (ask - p); mark += -q * (m["y"] - p)
        else:
            if bid <= 0: continue
            if (pr < bid - 1e-9 or (mode == "at" and pr <= bid + 1e-9)) and inv < cap:
                r = rem_b.get(i, N)
                q = min(r, cap - inv, psz)
                if q <= 0: continue
                rem_b[i] = r - q; inv += q; cash -= q * bid; nf += 1; sh += q
                spread_cap += q * (p - bid); mark += q * (m["y"] - p)
    return dict(cid=m["cid"], mins=mins, fills=nf, shares=sh, pnl=cash + inv * m["y"], spread=spread_cap, markout=mark, inv=inv,
                pmed=float(np.median(P[live])))


def run(data, **kw):
    return pd.DataFrame([r for r in (run_one(m, **kw) for m in data) if r])


def summary(R):
    md = R.mins.sum() / 1440
    return dict(mkts=len(R), mkt_days=md, fills=int(R.fills.sum()), sh_per_mkt_day=R.shares.sum() / md, pnl_per_mkt_day=R.pnl.sum() / md,
                spread_per_mkt_day=R.spread.sum() / md, markout_per_mkt_day=R.markout.sum() / md,
                pnl_per_share=R.pnl.sum() / max(1, R.shares.sum()))


if __name__ == "__main__":
    data = load(sys.argv[1] if len(sys.argv) > 1 else f"{ROOT}/data/sample_weather_recent.jsonl")
    print("markets", len(data), "with obs-day parsed", sum(np.isfinite(m["obs"]) for m in data))
    out = []
    for size_cap in [False, True]:
        for mode in ["through", "at"]:
            for d in [0.01, 0.02]:
                for clock, wins in [("hte", [(24, 1e9), (12, 24), (0, 12)]), ("hobs", [(24, 1e9), (12, 24), (0, 12), (-24, 0)])]:
                    for hmin, hmax in wins:
                        R = run(data, d=d, mode=mode, clock=clock, hmin=hmin, hmax=hmax, size_cap=size_cap)
                        if R.empty: continue
                        s = summary(R); s.update(size_cap=size_cap, mode=mode, d=d, clock=clock, win=f"[{hmin},{hmax})")
                        out.append(s)
                        print(f"size_cap={size_cap!s:5s} {mode:7s} d={d:.2f} {clock}{s['win']:12s} mkts={s['mkts']:4d} mkt_days={s['mkt_days']:6.0f} "
                              f"fills={s['fills']:6d} sh/mkt-day={s['sh_per_mkt_day']:6.1f} PnL/mkt-day=${s['pnl_per_mkt_day']:7.3f} "
                              f"(spread ${s['spread_per_mkt_day']:6.3f} markout ${s['markout_per_mkt_day']:7.3f}) PnL/share={s['pnl_per_share']:+.4f}",
                              flush=True)
    pd.DataFrame(out).to_csv(os.path.join(os.path.dirname(__file__), "hist_as_audit_results.csv"), index=False)
