"""Evaluate model vs market and taker trading rules on the decision table (data/tweets/bt/*.parquet)."""
import os, sys, glob, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from common import D, events
from bt_build import universe_bt

OOS_START = pd.Timestamp("2026-06-01", tz="UTC").value // 10**9
HB_EDGES = [0, 1, 3, 6, 12, 24, 48, 96, 1e9]
HB_LAB = ["<1h", "1-3h", "3-6h", "6-12h", "12-24h", "24-48h", "48-96h", ">96h"]

_imp = {}
def since_import(t, acct):
    """minutes since xtracker last imported a post (any X account; Trump/Tate: own feed) at time t."""
    from common import posts, ACCTS
    key = acct if acct in ("realDonaldTrump", "Cobratate") else "X"
    if key not in _imp:
        hs = [acct] if key != "X" else [h for h in ACCTS if h not in ("realDonaldTrump", "Cobratate")]
        _imp[key] = np.sort(np.concatenate([posts(h).importedAt.values.astype("datetime64[s]").astype("int64") for h in hs]))
    imp = _imp[key]; j = np.searchsorted(imp, t, side="right") - 1
    return np.where(j >= 0, (t - imp[np.clip(j, 0, None)]) / 60, 1e9)

def load(extra_slip=0.0, min_spread=0.01, mode="strict"):
    E, B = universe_bt()
    fs = glob.glob(f"{D}/bt{'' if mode == 'strict' else '_loose'}/*.parquet")
    df = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    meta = E[["event_id", "acct", "series", "start", "end", "fee_rate", "gap", "title"]]
    df = df.merge(meta, on="event_id", how="inner")
    df["oos"] = df.t >= OOS_START
    df["stall"] = 0.0
    for a in df.acct.unique():
        m = (df.acct == a).values
        df.loc[m, "stall"] = np.asarray(since_import(df.t.values[m].astype("int64"), a), dtype="float64")
    df["hbin"] = pd.cut(df.H, HB_EDGES, labels=HB_LAB, right=False)
    hs_a = df.hs_a.fillna(0.02).clip(lower=0); hs_b = df.hs_b.fillna(0.02).clip(lower=0)
    df["ask"] = (df.mid + np.maximum(min_spread, hs_a) + extra_slip).clip(0.001, 0.999)
    df["bid"] = (df.mid - np.maximum(min_spread, hs_b) - extra_slip).clip(0.001, 0.999)
    # conservative: never assume an ask below the last lift print of the previous 30 min
    df["ask"] = np.where(df.last_lift.notna(), np.maximum(df.ask, df.last_lift.clip(upper=0.999)), df.ask)
    r = df.fee_rate
    df["cost_y"] = df.ask + r * df.ask * (1 - df.ask)
    df["no_ask"] = 1 - df.bid
    df["cost_n"] = df.no_ask + r * df.no_ask * (1 - df.no_ask)
    df["edge_y"] = df.q - df.cost_y
    df["edge_n"] = (1 - df.q) - df.cost_n
    df["pay_y"] = df.won.astype(float); df["pay_n"] = 1 - df.pay_y
    return df

def trades(df, th, side="both", first_only=True, pmin=0.0, pmax=1.0, reentry_h=None, hmin=0, hmax=1e9, accts=None):
    """Signals -> trades. Returns DataFrame with side, price(cost), pay, event, etc."""
    out = []
    for s in (["y", "n"] if side == "both" else [side]):
        px = df["ask"] if s == "y" else df["no_ask"]
        m = (df[f"edge_{s}"] > th) & (px >= pmin) & (px <= pmax) & (df.H >= hmin) & (df.H < hmax)
        if accts is not None: m &= df.acct.isin(accts)
        x = df[m].copy()
        x["side"] = s; x["cost"] = x[f"cost_{s}"]; x["pay"] = x[f"pay_{s}"]; x["edge"] = x[f"edge_{s}"]
        x["px"] = px[m]; x["liq"] = x["liq_a"] if s == "y" else x["liq_b"]
        out.append(x)
    x = pd.concat(out).sort_values("t")
    if first_only:
        x = x.drop_duplicates(["event_id", "k", "side"], keep="first")
    elif reentry_h:
        x["slot"] = (x.t // (reentry_h * 3600))
        x = x.drop_duplicates(["event_id", "k", "side", "slot"], keep="first")
    x["ret"] = (x.pay - x.cost) / x.cost    # return per $ staked
    return x

def summarize(x, stakes=(10, 50, 200), cap_frac=0.25):
    if len(x) == 0: return dict(n=0)
    r = dict(n=len(x), events=x.event_id.nunique(), hit=x.pay.mean(), avg_px=x.px.mean(), avg_edge=x.edge.mean(),
             roi=x.ret.mean())
    # event-clustered t-stat of per-$ return
    ev = x.groupby("event_id").ret.sum()
    r["t_ev"] = ev.mean() / (ev.std(ddof=1) / np.sqrt(len(ev))) if len(ev) > 2 and ev.std() > 0 else np.nan
    for st in stakes:
        pnl = st * x.ret
        r[f"pnl_{st}"] = pnl.sum()
        eq = pnl.groupby(x.t).sum().cumsum()     # resolution is later, but mark PnL at entry for ordering
        r[f"mdd_{st}"] = (eq.cummax() - eq).max()
    capped = np.minimum(200, cap_frac * x.liq)
    r["pnl_capped200"] = (capped * x.ret).sum(); r["usd_capped200"] = capped.sum()
    return r

if __name__ == "__main__":
    df = load()
    print(len(df), df.event_id.nunique())

def snapshot_scores(df):
    """Per (event, t) snapshot: log-loss of the realized bucket under the model q vs the market (mids normalized
    over live buckets). Only snapshots where the winning bucket is live and priced."""
    g = df.groupby(["event_id", "t"])
    s = g.agg(msum=("mid", "sum"), qsum=("q", "sum"), acct=("acct", "first"), oos=("oos", "first"),
              hbin=("hbin", "first"), H=("H", "first"), nlive=("k", "size"))
    w = df[df.won == 1].set_index(["event_id", "t"])[["q", "mid"]]
    s = s.join(w, how="inner")
    s["p_mkt"] = (s.mid / s.msum).clip(1e-4, 1)
    s["p_mod"] = (s.q / s.qsum).clip(1e-4, 1)
    s["ll_mkt"] = -np.log(s.p_mkt); s["ll_mod"] = -np.log(s.p_mod)
    s["ll_mix"] = -np.log((0.5 * s.p_mkt + 0.5 * s.p_mod).clip(1e-4, 1))
    return s.reset_index()
