"""Summarize live order book snapshots: spreads and depth by price level and days-to-target."""
import json, glob, sys
import numpy as np
import pandas as pd
from common import D


def book_stats(b):
    bids = sorted([(float(x["price"]), float(x["size"])) for x in b.get("bids", [])], key=lambda t: -t[0])
    asks = sorted([(float(x["price"]), float(x["size"])) for x in b.get("asks", [])], key=lambda t: t[0])
    r = {}
    r["bb"] = bids[0][0] if bids else np.nan
    r["ba"] = asks[0][0] if asks else np.nan
    for w in (0.01, 0.02, 0.05):
        if asks:
            r[f"ask_usd_{int(w*100)}c"] = sum(p * s for p, s in asks if p <= asks[0][0] + w + 1e-9)
            r[f"ask_sh_{int(w*100)}c"] = sum(s for p, s in asks if p <= asks[0][0] + w + 1e-9)
        if bids:
            r[f"bid_usd_{int(w*100)}c"] = sum(p * s for p, s in bids if p >= bids[0][0] - w - 1e-9)
    r["ask_top_usd"] = asks[0][0] * asks[0][1] if asks else np.nan
    return r, bids, asks


def sweep_cost(asks, usd):
    """Average price paid to buy `usd` dollars of shares by sweeping asks."""
    spent = 0; sh = 0
    for p, s in asks:
        take = min(s, (usd - spent) / p)
        spent += take * p; sh += take
        if spent >= usd - 1e-9:
            break
    return (spent / sh if sh else np.nan), spent


def main(fn):
    snap = json.load(open(fn))
    ts = pd.Timestamp(snap["ts"])
    T = pd.DataFrame(snap["markets"])
    rows = []
    for _, m in T.iterrows():
        b = snap["books"].get(m.yes)
        if not b:
            continue
        st, bids, asks = book_stats(b)
        st.update(event_slug=m.event_slug, date=m.date, bucket=m.bucket, vol=m.vol)
        for usd in (20, 100, 500):
            avgp, spent = sweep_cost(asks, usd)
            st[f"sweep{usd}_px"] = avgp; st[f"sweep{usd}_filled"] = spent
        rows.append(st)
    X = pd.DataFrame(rows)
    X["mid"] = (X.bb + X.ba) / 2
    X["spread"] = X.ba - X.bb
    X["days"] = (pd.to_datetime(X.date) - pd.Timestamp(ts.date())).dt.days
    X["kind"] = np.where(X.event_slug.str.startswith("highest"), "highest", "lowest")
    X["pbin"] = pd.cut(X.mid, [0, 0.03, 0.1, 0.25, 0.5, 0.75, 0.9, 0.97, 1.0])
    live = X[(X.bb > 0.0) & X.ba.notna() & (X.ba < 1)]
    print("snapshot", ts, "markets", len(X), "two-sided", len(live))
    g = live.groupby(["kind", "days", "pbin"], observed=True).agg(n=("spread", "size"), spread_med=("spread", "median"),
        ask1c_usd=("ask_usd_1c", "median"), ask5c_usd=("ask_usd_5c", "median"), bid5c_usd=("bid_usd_5c", "median"),
        sw100=("sweep100_px", "median"), filled500=("sweep500_filled", "median"))
    pd.set_option("display.width", 200)
    print(g.round(3).to_string())
    X.drop(columns=["pbin"]).to_parquet(fn.replace(".json", "_stats.parquet"))
    return X


if __name__ == "__main__":
    for fn in sys.argv[1:]:
        main(fn)
