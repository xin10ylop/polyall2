"""What do the flagged wallets actually do?  For each of their fills on daily temperature markets:
local time at the station, side/outcome/price, and the bucket state per METAR at fill time
(dead = impossible given running max; alive), seconds since the killing METAR observation time."""
import glob, json, os
import numpy as np
import pandas as pd
from common import D, TZ
from obs import load_obs


def main():
    M = pd.read_parquet(f"{D}/markets.parquet", columns=["conditionId", "event_id", "kind", "city", "lo", "hi", "yes_final", "bucket"])
    R = pd.read_parquet(f"{D}/events_resolved.parquet")[["event_id", "icao", "unit", "date", "win_idx", "clean"]]
    R["date"] = pd.to_datetime(R.date, errors="coerce")
    M = M.merge(R, on="event_id")
    out = []
    for f in sorted(glob.glob(f"{D}/wallets/*.parquet")):
        name = os.path.basename(f)[:-8]
        W = pd.read_parquet(f)
        W = W.merge(M, on="conditionId", how="inner")
        W["wallet"] = name
        out.append(W)
    W = pd.concat(out, ignore_index=True)
    W = W[W.icao.isin(list(TZ)) & ~W.icao.isin(["HKO", "CWA46692"])]
    rows = []
    for (icao, unit), g in W.groupby(["icao", "unit"]):
        o = load_obs(icao, unit)
        if o is None:
            continue
        o = o.assign(vt=o.utc.dt.tz_convert(None).values.astype("datetime64[s]").astype(np.int64))
        byd = {d: x.sort_values("vt") for d, x in o.groupby("ldate")}
        for r in g.itertuples():
            od = byd.get(r.date.date())
            rec = dict(idx=r.Index)
            tloc = pd.Timestamp(r.timestamp, unit="s", tz="UTC").tz_convert(TZ[icao])
            rec["local_h"] = (tloc - pd.Timestamp(r.date).tz_localize(TZ[icao])).total_seconds() / 3600
            if od is not None and len(od):
                vt = od.vt.values; rm = np.maximum.accumulate(od.t.values)
                k = np.searchsorted(vt, r.timestamp, side="right") - 1   # METARs with obs time <= fill time
                rmax = rm[k] if k >= 0 else np.nan
                rec["runmax"] = rmax
                if r.kind == "highest":
                    dead_no = (r.hi == r.hi) and rmax >= r.hi + 1            # bucket below running max
                    top_yes = (r.hi != r.hi) and (r.lo == r.lo) and rmax >= r.lo
                    rec["state"] = "dead" if dead_no else ("top_hit" if top_yes else "alive")
                    if dead_no or top_yes:
                        thr = (r.hi + 1) if dead_no else r.lo
                        kk = np.where(rm >= thr)[0][0]
                        rec["since_kill_s"] = r.timestamp - vt[kk]
                    else:
                        rec["gap"] = (r.lo - rmax) if r.lo == r.lo else np.nan  # degrees still needed to reach bucket
            rows.append(rec)
    S = pd.DataFrame(rows).set_index("idx")
    W = W.join(S)
    W["win_bucket"] = (W.yes_final == 1)
    W["held_outcome_wins"] = np.where(W.outcome == "Yes", W.win_bucket, ~W.win_bucket)
    W.to_parquet(f"{D}/wallet_fills.parquet")
    return W


if __name__ == "__main__":
    W = main()
    pd.set_option("display.width", 220)
    for name, g in W.groupby("wallet"):
        b = g[g.side == "BUY"]
        print("=====", name, "fills", len(g), "buys", len(b), "period", pd.to_datetime(g.timestamp.min(), unit="s").date(), pd.to_datetime(g.timestamp.max(), unit="s").date())
        print(" kinds", g.kind.value_counts().to_dict(), "outcome of buys", b.outcome.value_counts().to_dict())
        print(" buy state", b.state.value_counts(normalize=True).round(3).to_dict())
        print(" buy price quantiles", b.price.quantile([.1, .25, .5, .75, .9]).round(3).to_dict())
        print(" buy local hour quantiles", b.local_h.quantile([.1, .25, .5, .75, .9]).round(1).to_dict())
        d = b[b.state == "dead"]
        if len(d):
            print(" dead buys: n", len(d), "median secs since kill", d.since_kill_s.median(), "q10/q90", d.since_kill_s.quantile([.1, .9]).tolist(),
                  "median px", d.price.median(), "share of $", round((d.price * d["size"]).sum() / (b.price * b["size"]).sum(), 3))
        a = b[b.state == "alive"]
        if len(a):
            print(" alive buys: n", len(a), "outcome", a.outcome.value_counts().to_dict(), "px median", a.price.median(),
                  "gap quantiles", a.gap.quantile([.1, .5, .9]).tolist(), "win rate", a.held_outcome_wins.mean().round(3),
                  "PnL/$ (hold to resolution, ex fees)", round(((a.held_outcome_wins - a.price) * a["size"]).sum() / (a.price * a["size"]).sum(), 4))
        print(" all buys win rate", b.held_outcome_wins.mean().round(4), "hold-to-res PnL/$", round(((b.held_outcome_wins - b.price) * b["size"]).sum() / (b.price * b["size"]).sum(), 4))
