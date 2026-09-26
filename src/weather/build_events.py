"""Build the resolved-events table: one row per temperature event with station, unit, date, buckets and winner."""
import json
import numpy as np
import pandas as pd
from common import D, event_date

def main():
    E = pd.read_parquet(f"{D}/events.parquet")
    M = pd.read_parquet(f"{D}/markets.parquet")
    ES = pd.read_parquet(f"{D}/event_station.parquet")
    E = E[E.kind != "other"].merge(ES[["event_id", "icao", "source", "unit"]], on="event_id", how="left")
    E["date"] = [event_date(s, e) or pd.Timestamp(e).date() for s, e in zip(E.slug, E.endDate)]
    rows = []
    for eid, g in M[M.kind != "other"].groupby("event_id", sort=False):
        g = g.reset_index(drop=True)
        yf = g.yes_final.fillna(-1).values
        win = np.where(yf == 1.0)[0]
        clean = (len(win) == 1) and np.all((yf == 0) | (yf == 1))
        los = g.lo.values; his = g.hi.values
        rows.append(dict(event_id=eid, n_b=len(g), win_idx=int(win[0]) if len(win) == 1 else -1, clean=clean,
                         win_lo=los[win[0]] if len(win) == 1 else np.nan, win_hi=his[win[0]] if len(win) == 1 else np.nan,
                         los=json.dumps([None if pd.isna(x) else float(x) for x in los]),
                         his=json.dumps([None if pd.isna(x) else float(x) for x in his]),
                         fees=bool(g.feesEnabled.fillna(False).any()), mvol=float(g.volume.fillna(0).sum())))
    R = pd.DataFrame(rows)
    out = E.merge(R, on="event_id", how="inner")
    out.to_parquet(f"{D}/events_resolved.parquet")
    print(out.shape, out.clean.mean())
    return out

if __name__ == "__main__":
    main()
