"""When does volume trade (hours relative to the start of the local target day)? Taker notional per event/bucket."""
import os
import numpy as np
import pandas as pd
from common import D, TZ
from features import local_ts


def main(sample=3000):
    R = pd.read_parquet(f"{D}/events_resolved.parquet")
    R = R[(R.kind == "highest") & R.clean & R.icao.isin(list(TZ))]
    R = R[pd.to_datetime(R.date) >= "2026-05-01"]
    R = R.sample(min(sample, len(R)), random_state=0)
    from common import load_bars
    ALL = load_bars(R.event_id)
    rows = []
    for _, ev in R.iterrows():
        b = ALL.get(int(ev.event_id))
        if b is None:
            continue
        d0 = local_ts(pd.Timestamp(ev.date).date(), 0, TZ[ev.icao]).timestamp()
        b["h"] = np.floor((b.bt - d0) / 3600)
        b["usd"] = b.vwap * b.shares
        g = b.groupby("h").usd.sum()
        for h, v in g.items():
            rows.append((ev.event_id, h, v))
    X = pd.DataFrame(rows, columns=["event_id", "h", "usd"])
    tot = X.groupby("event_id").usd.sum()
    X["frac"] = X.usd / X.event_id.map(tot)
    prof = X.groupby("h").frac.sum() / X.event_id.nunique()
    prof = prof[(prof.index >= -60) & (prof.index <= 36)]
    blocks = pd.cut(prof.index, [-61, -36, -24, -12, 0, 7, 11, 14, 16, 18, 24, 37], right=False)
    print("events", X.event_id.nunique(), "median taker notional/event $", round(tot.median()))
    print(prof.groupby(blocks, observed=True).sum().round(3).to_string())
    return prof


if __name__ == "__main__":
    main()
