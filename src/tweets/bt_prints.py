"""Print-confirmed execution columns for the decision table.
For each (event, t, k): the LAST YES-equivalent lift print (taker buys YES-equiv) and hit print in [t-30min, t),
with price, USD size, and n_new = # posts xtracker imported (for this window) between the print and t.
A fill at the print price is only credited if n_new == 0 (the print happened with the same information set
as the model at t). Output: data/tweets/bt_pc/<event_id>.parquet (t, k, pl, ul, nl, ph, uh, nh)."""
import os, sys, glob, numpy as np, pandas as pd
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(__file__))
from common import D, events
from model import Acct
from bt_build import yes_equiv

OUT = f"{D}/bt_pc"; os.makedirs(OUT, exist_ok=True)
E, B = events(); E = E.set_index("event_id")
_a = {}

def job(eid):
    fp = f"{OUT}/{eid}.parquet"
    if os.path.exists(fp): return eid, -1
    bt = pd.read_parquet(f"{D}/bt/{eid}.parquet", columns=["t", "k"])
    TR = pd.read_parquet(f"{D}/trades/{eid}.parquet").sort_values("ts")
    e = E.loc[eid]
    if e.acct not in _a: _a[e.acct] = Acct(e.acct, True)
    a = _a[e.acct]; S = int(e.start.timestamp())
    py, lift = yes_equiv(TR)
    TR = TR.assign(py=py, lift=lift, usd=np.where(TR.oi.values == 1, TR.price.values, py) * TR["size"].values)
    res = []
    for k, g in bt.groupby("k"):
        tr = TR[TR.k == k]
        out = {"t": g.t.values, "k": np.full(len(g), k, "int8")}
        for nm, sel in [("l", tr.lift.values), ("h", ~tr.lift.values)]:
            ts = tr.ts.values[sel]; pp = tr.py.values[sel]; uu = tr.usd.values[sel]
            j = np.searchsorted(ts, g.t.values, side="left") - 1
            ok = (j >= 0) & (ts[np.clip(j, 0, None)] >= g.t.values - 1800) if len(ts) else np.zeros(len(g), bool)
            jj = np.clip(j, 0, None)
            out["p" + nm] = np.where(ok, pp[jj] if len(ts) else np.nan, np.nan).astype("float32")
            out["u" + nm] = np.where(ok, uu[jj] if len(ts) else 0, 0).astype("float32")
            tp = np.where(ok, ts[jj] if len(ts) else 0, 0)
            # posts imported in (tp, t] belonging to window (created >= S)
            nn = np.zeros(len(g), "int16")
            for i in np.where(ok)[0]:
                t = g.t.values[i]
                nn[i] = a.count(S, t) - a.count(S, int(tp[i])) if t > S else 0
            out["n" + nm] = nn
        res.append(pd.DataFrame(out))
    df = pd.concat(res) if res else pd.DataFrame()
    df.to_parquet(fp, index=False, compression="zstd")
    return eid, len(df)

if __name__ == "__main__":
    ids = [os.path.basename(f)[:-8] for f in glob.glob(f"{D}/bt/*.parquet")]
    with Pool(int(sys.argv[1]) if len(sys.argv) > 1 else 3) as p:
        for i, r in enumerate(p.imap_unordered(job, ids)):
            if i % 100 == 0: print(i, r, flush=True)
