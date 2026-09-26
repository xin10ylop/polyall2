"""Market state at each decision time from 10-min YES-equivalent taker trade bars.

For each (event, decision tau, bucket):
  last_px / last_age_h : VWAP of the most recent bar that closed at or before tau (any side) and its age
  lift_px_prev / hit_px_prev : VWAP of the most recent lift (taker buy YES-eq) / hit bar in the 3h before tau
  ask_*  : taker-buy (lift) prints in [tau, tau+W): shares, VWAP, min  -> evidence of executable YES ask
  bid_*  : taker-sell (hit) prints in [tau, tau+W): shares, VWAP, max -> evidence of executable YES bid (NO ask = 1-bid)
  vol24_sh : YES-eq shares traded in the 24h before tau (both sides)
"""
import os, sys, json
import numpy as np
import pandas as pd
from common import D

W = 1800  # fill window after decision (s)


def event_market_state(bars, taus, n_b):
    """Vectorised per-tau state for all buckets of one event."""
    out = []
    if bars is None or len(bars) == 0:
        return out
    bt = bars.bt.values.astype(np.int64); mi = bars.mi.values.astype(int); kd = bars.kind.values.astype(int)
    sh = bars.shares.values.astype(float); pv = bars.vwap.values.astype(float) * sh
    pmin = bars.pmin.values.astype(float); pmax = bars.pmax.values.astype(float)
    ok = (mi >= 0) & (mi < n_b)
    bt, mi, kd, sh, pv, pmin, pmax = bt[ok], mi[ok], kd[ok], sh[ok], pv[ok], pmin[ok], pmax[ok]
    for dname, tau in taus:
        t = int(tau.timestamp())
        res = {k: np.full(n_b, np.nan) for k in ["last_px", "last_age_h", "lift_px_prev", "hit_px_prev", "ask_sh", "ask_vwap",
                                                 "ask_min", "bid_sh", "bid_vwap", "bid_max"]}
        prev = bt + 600 <= t
        # last bar per bucket
        if prev.any():
            lastbt = np.full(n_b, -1, np.int64)
            np.maximum.at(lastbt, mi[prev], bt[prev])
            sel = prev & (bt == lastbt[mi])
            num = np.bincount(mi[sel], pv[sel], n_b); den = np.bincount(mi[sel], sh[sel], n_b)
            has = den > 0
            res["last_px"][has] = num[has] / den[has]
            res["last_age_h"][has] = (t - (lastbt[has] + 600)) / 3600
            for kname, kval in (("lift_px_prev", 1), ("hit_px_prev", -1)):
                m3 = prev & (bt >= t - 3 * 3600) & (kd == kval)
                if m3.any():
                    lb = np.full(n_b, -1, np.int64); np.maximum.at(lb, mi[m3], bt[m3])
                    s2 = m3 & (bt == lb[mi])
                    num = np.bincount(mi[s2], pv[s2], n_b); den = np.bincount(mi[s2], sh[s2], n_b)
                    h2 = den > 0; res[kname][h2] = num[h2] / den[h2]
        post = (bt >= t) & (bt < t + W)
        for side, kval in (("ask", 1), ("bid", -1)):
            m = post & (kd == kval)
            if m.any():
                den = np.bincount(mi[m], sh[m], n_b); num = np.bincount(mi[m], pv[m], n_b)
                h2 = den > 0
                res[f"{side}_sh"][h2] = den[h2]; res[f"{side}_vwap"][h2] = num[h2] / den[h2]
                if side == "ask":
                    mn = np.full(n_b, np.inf); np.minimum.at(mn, mi[m], pmin[m]); res["ask_min"][h2] = mn[h2]
                else:
                    mx = np.full(n_b, -np.inf); np.maximum.at(mx, mi[m], pmax[m]); res["bid_max"][h2] = mx[h2]
        p24 = prev & (bt >= t - 86400)
        res["vol24_sh"] = np.bincount(mi[p24], sh[p24], n_b)
        for j in range(n_b):
            r = {k: v[j] for k, v in res.items()}
            r["dec"] = dname; r["mi"] = j
            out.append(r)
    return out


def main():
    from features import DECISIONS, local_ts
    from common import TZ
    R = pd.read_parquet(f"{D}/events_resolved.parquet")
    R = R[(R.kind == "highest") & R.clean & R.icao.isin(list(TZ))]
    from common import load_bars
    ALL = load_bars()
    rows = []
    n = 0
    for _, ev in R.iterrows():
        bars = ALL.get(int(ev.event_id))
        if bars is None:
            continue
        tz = TZ[ev.icao]
        taus = []
        for dname, doff, hr in DECISIONS:
            ddate = (pd.Timestamp(ev.date) + pd.Timedelta(days=doff)).date()
            taus.append((dname, local_ts(ddate, hr, tz)))
        for r in event_market_state(bars, taus, ev.n_b):
            r["event_id"] = ev.event_id
            rows.append(r)
        n += 1
        if n % 1000 == 0:
            print(n, flush=True)
    S = pd.DataFrame(rows)
    S.to_parquet(f"{D}/market_state.parquet")
    print(S.shape)


if __name__ == "__main__":
    main()
