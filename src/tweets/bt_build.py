"""Build the decision table: for each event in the universe and each decision time t (hourly, from window
start-48h to end; plus every 10 min in the last 3 h), the model bucket probabilities q_k(t) and the market
state (mid, executable ask/bid proxies, recent traded liquidity) for every live bucket.

No-look-ahead rules:
  * model: posts with createdAt < t and importedAt <= t (strict) ; params from walk-forward month of t
  * price: FIRST mid sample at or after t+60s (<= t+11min) => market has >= the model's information
  * ask proxy = mid + max(1c, median lift premium over mid in the prior 24h); bid proxy symmetric
  * liquidity = YES-equivalent lift (resp. hit) notional in the prior 6h at prices <= ask+1c (>= bid-1c)
Output: data/tweets/bt/<event_id>.parquet
"""
import os, sys, json, numpy as np, pandas as pd
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(__file__))
from common import D, events, gaps
from model import Acct, bucket_probs, hbin
from calibrate import TRACK_START

MODE = os.environ.get("BT_MODE", "strict")          # strict = xtracker as-of ; loose = own X monitor (createdAt)
STRICT = MODE == "strict"
OUT = f"{D}/bt" + ("" if STRICT else "_loose"); os.makedirs(OUT, exist_ok=True)
WF = json.load(open(f"{D}/wf_params{'' if STRICT else '_loose'}.json"))

def params_for(acct, t, H):
    m = pd.Timestamp(t, unit="s", tz="UTC").strftime("%Y-%m")
    p = WF.get(m, {}).get(acct)
    if not p: return None
    hb = int(hbin(np.array([H]))[0])
    if str(hb) in p: return p[str(hb)]
    ks = sorted(int(k) for k in p)
    return p[str(min(ks, key=lambda k: abs(k - hb)))]

def yes_equiv(tr):
    isno = tr.oi.values == 1
    py = np.where(isno, 1 - tr.price.values, tr.price.values)
    lift = np.where(isno, tr.side.values < 0, tr.side.values > 0)
    return py, lift

_acct = {}
def get_acct(h):
    if h not in _acct: _acct[h] = Acct(h, STRICT)
    return _acct[h]

def build(e, b):
    fp = f"{OUT}/{e.event_id}.parquet"
    if os.path.exists(fp): return e.event_id, -1
    pf = f"{D}/prices/{e.event_id}.parquet"; tf = f"{D}/trades/{e.event_id}.parquet"
    if not (os.path.exists(pf) and os.path.exists(tf)): return e.event_id, -2
    PR = pd.read_parquet(pf); TR = pd.read_parquet(tf)
    a = get_acct(e.acct)
    S = int(e.start.timestamp()); E = int(e.end.timestamp())
    b = b.sort_values("k"); K = len(b)
    lo = b.lo.values; hi = b.hi.values
    closed = b.closedTime.map(lambda x: x.timestamp() if pd.notna(x) else 1e12).values
    won = b.won.values.astype(int)
    # decision grid
    t0 = max(S - 48 * 3600, int(PR.t.min()) if len(PR) else S)
    t0 = (t0 // 3600 + 1) * 3600
    grid = list(range(t0, E - 3 * 3600, 3600)) + list(range(max(E - 3 * 3600, t0), E - 60, 600))
    grid = np.array(sorted(set(grid)))
    # prices: per bucket sorted arrays
    pk = {k: g.sort_values("t") for k, g in PR.groupby("k")}
    # trades yes-equivalent with mid at print
    TR = TR.sort_values("ts")
    py, lift = yes_equiv(TR)
    TR = TR.assign(py=py, lift=lift, usd=py * TR["size"].values)
    rows = []
    # per-bucket trade arrays with premium over mid
    tk = {}
    for k, g in TR.groupby("k"):
        if k not in pk: continue
        m = pk[k]; idx = np.searchsorted(m.t.values, g.ts.values, side="right") - 1
        mid_at = np.where(idx >= 0, m.p.values[np.clip(idx, 0, None)], np.nan)
        tk[k] = dict(ts=g.ts.values, py=g.py.values, lift=g.lift.values, usd=g.usd.values,
                     prem=np.where(g.lift.values, g.py.values - mid_at, mid_at - g.py.values))
    for t in grid:
        ts_ = max(t, S)
        H = (E - ts_) / 3600
        pr = params_for(e.acct, t, H)
        if pr is None: continue
        C = a.count(S, t) if t > S else 0
        R, prof = a.state(t, pr["hl"])
        mu = a.expected(ts_, E, R, prof)
        q = bucket_probs(C, mu, pr["alpha"], lo, hi)
        for k in range(K):
            if closed[k] <= t or k not in pk: continue
            m = pk[k]; j = np.searchsorted(m.t.values, t + 60, side="left")
            if j >= len(m) or m.t.values[j] > t + 660: continue
            mid = float(m.p.values[j])
            ja = np.searchsorted(m.t.values, t, side="right") - 1
            mid_before = float(m.p.values[ja]) if ja >= 0 and m.t.values[ja] >= t - 1800 else np.nan
            hs_a = hs_b = np.nan; liq_a = liq_b = 0.0; n24 = 0; last_lift = np.nan
            if k in tk:
                d = tk[k]; i0, i1 = np.searchsorted(d["ts"], [t - 86400, t])
                sl = slice(i0, i1); n24 = i1 - i0
                lf = d["lift"][sl]; pm = d["prem"][sl]
                if (lf & ~np.isnan(pm)).any(): hs_a = float(np.nanmedian(pm[lf]))
                if ((~lf) & ~np.isnan(pm)).any(): hs_b = float(np.nanmedian(pm[~lf]))
                i6 = np.searchsorted(d["ts"], t - 6 * 3600)
                s6 = slice(i6, i1)
                ask_p = mid + max(0.01, hs_a if not np.isnan(hs_a) else 0.02)
                bid_p = mid - max(0.01, hs_b if not np.isnan(hs_b) else 0.02)
                liq_a = float(d["usd"][s6][d["lift"][s6] & (d["py"][s6] <= ask_p + 0.01)].sum())
                liq_b = float(((1 - d["py"][s6]) * d["usd"][s6] / np.maximum(d["py"][s6], 1e-6))[(~d["lift"][s6]) & (d["py"][s6] >= bid_p - 0.01)].sum())
                jl = np.where(d["lift"][i0:i1])[0]
                if len(jl) and d["ts"][i0 + jl[-1]] >= t - 1800: last_lift = float(d["py"][i0 + jl[-1]])
            rows.append((t, k, C, mu, q[k], mid, mid_before, hs_a, hs_b, liq_a, liq_b, n24, last_lift, won[k], H))
    df = pd.DataFrame(rows, columns=["t", "k", "C", "mu", "q", "mid", "mid_before", "hs_a", "hs_b", "liq_a", "liq_b",
                                     "n24", "last_lift", "won", "H"])
    df["event_id"] = e.event_id
    for c in ["q", "mid", "mid_before", "hs_a", "hs_b", "last_lift", "mu", "H"]: df[c] = df[c].astype("float32")
    df.to_parquet(fp, index=False, compression="zstd")
    return e.event_id, len(df)

def universe_bt():
    E, B = events()
    E = E[E.closed & E.resolved & ~E.slug.str.startswith("arch-") & E.start.notna()].copy()
    E = E[E.apply(lambda r: r.start >= pd.Timestamp(TRACK_START[r.acct], tz="UTC") + pd.Timedelta("28D"), axis=1)]
    E["gap"] = E.apply(lambda r: any(not (r.end.timestamp() <= g0 or r.start.timestamp() - 7 * 86400 >= g1) for g0, g1 in gaps(r.acct)), axis=1)
    return E, B

def _job(args):
    e, b = args
    try: return build(e, b)
    except Exception as ex:
        import traceback; traceback.print_exc(); return e.event_id, str(ex)

if __name__ == "__main__":
    E, B = universe_bt()
    print("events", len(E), "gap-affected", E.gap.sum(), flush=True)
    jobs = [(e, B[B.event_id == e.event_id]) for _, e in E.iterrows()]
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    with Pool(n) as pool:
        for i, (eid, r) in enumerate(pool.imap_unordered(_job, jobs)):
            if isinstance(r, str) or (i % 50 == 0): print(i, eid, r, flush=True)
