"""Same-day observation ("dead bucket") strategy on daily HIGHEST-temperature markets.

Opportunities: for each event (station, local day D) and bucket j,
  NO_dead(m):  first METAR (routine/special) of day D whose running max >= hi_j + m      -> buy NO on bucket j
  YES_top(m):  first METAR with running max >= lo_top + (m-1) on the open-ended top bucket -> buy YES
m = 1 is the strict rule (bucket strictly below the running max), m = 2 adds a one-degree safety margin.
We record the observation time `valid` of the killing METAR; the decision time is valid + LAG (publication delay)
+ REACT (our reaction time), set at simulation time.

Execution evidence: exact taker prints on the bucket (data-api), stored relative to `valid`:
  NO side: taker BUY NO or taker SELL YES  -> NO price = 1 - YES-eq price
  YES side: taker BUY YES or taker SELL NO -> YES price
"""
import os, sys, glob, json
import numpy as np
import pandas as pd
from common import D, TZ, taker_fee_per_share
from obs import load_obs
from features import local_ts

WINDOW = (-7200, 8 * 3600)  # prints kept relative to the killing METAR time


def deaths_for_event(ev, od, margins=(1, 2)):
    los = json.loads(ev.los); his = json.loads(ev.his)
    o = od.sort_values("utc")
    vt = o.utc.dt.tz_convert(None).values.astype("datetime64[s]").astype(np.int64)
    rm = np.maximum.accumulate(o.t.values)
    out = []
    for m in margins:
        for j, (lo, hi) in enumerate(zip(los, his)):
            if hi is not None:
                k = np.where(rm >= hi + m)[0]; kind = "NO_dead"
            elif lo is not None:
                k = np.where(rm >= lo + (m - 1))[0]; kind = "YES_top"
            else:
                continue
            if len(k):
                i = k[0]
                out.append(dict(mi=j, kind=kind, margin=m, valid=int(vt[i]), runmax=float(rm[i]), lo=lo, hi=hi,
                                win=int(j == ev.win_idx), first_obs=int(vt[0])))
    return out


def build(months=None):
    R = pd.read_parquet(f"{D}/events_resolved.parquet")
    R = R[(R.kind == "highest") & R.clean & R.icao.isin(list(TZ))].copy()
    R["date"] = pd.to_datetime(R.date, errors="coerce")
    files = sorted(glob.glob(f"{D}/raw_d0/*_highest.parquet"))
    if months:
        files = [f for f in files if os.path.basename(f)[:7] in months]
    T = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    R = R[R.event_id.astype(int).isin(set(T.event_id.unique()))]
    rows = []
    for (icao, unit), g in R.groupby(["icao", "unit"]):
        if icao in ("HKO", "CWA46692"):
            continue
        o = load_obs(icao, unit)
        if o is None:
            continue
        byd = {d: x for d, x in o.groupby("ldate")}
        for _, ev in g.iterrows():
            od = byd.get(ev.date.date())
            if od is None or len(od) < 12:
                continue
            for d in deaths_for_event(ev, od):
                d.update(event_id=int(ev.event_id), icao=icao, unit=unit, city=ev.city, date=ev.date, fees=bool(ev.fees),
                         source=ev.source, day0=int(local_ts(ev.date.date(), 0, TZ[icao]).timestamp()))
                rows.append(d)
    O = pd.DataFrame(rows).reset_index(drop=True)
    O["opp"] = O.index
    # prints relative to killing METAR
    isno = T.oi == 1
    T = T.assign(py=np.where(isno, 1 - T.price, T.price), sy=np.where(isno, -T.side, T.side))
    groups = {k: g for k, g in T.groupby(["event_id", "mi"])}
    P = []
    for r in O.itertuples():
        g = groups.get((r.event_id, r.mi))
        if g is None:
            continue
        dtv = g.ts.values.astype(np.int64) - r.valid
        keep = (dtv >= WINDOW[0]) & (dtv < WINDOW[1])
        if not keep.any():
            continue
        gg = g[keep]
        side_ok = (gg.sy == -1) if r.kind == "NO_dead" else (gg.sy == 1)
        px = np.where(r.kind == "NO_dead", 1 - gg.py.values, gg.py.values)
        P.append(pd.DataFrame(dict(opp=r.opp, dtv=dtv[keep].astype(np.int32), exe=side_ok.values, px=px.astype(np.float32),
                                   sh=gg["size"].values.astype(np.float32), w=gg.w.values, yes_eq=gg.py.values.astype(np.float32))))
    P = pd.concat(P, ignore_index=True)
    return O, P


if __name__ == "__main__":
    O, P = build()
    O.to_parquet(f"{D}/dead_opps.parquet")
    P.to_parquet(f"{D}/dead_prints.parquet", compression="zstd")
    print(O.shape, P.shape)
