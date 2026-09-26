"""Station-day decision-time features (all days with observations, not just market days, so that
walk-forward bias/sigma estimates have history before markets existed).

Decision times (station local clock): D-1 12:00, D-0 07:00, 11:00, 14:00, 16:00, 18:00.
No look-ahead rules:
  * NBM (US only): latest NBS run with runtime + 2h <= tau (NBM text products are out ~1h after cycle).
  * Open-Meteo previous_dayN (when available): for valid hour t use smallest N with t - 24N h + 8h <= tau.
  * Observations: METARs with obs time <= tau - 10 min, same local date.
"""
import os, sys, json
import numpy as np
import pandas as pd
from common import D, TZ, c2f
from obs import load_obs

DECISIONS = [("D-1 12h", -1, 12), ("D0 07h", 0, 7), ("D0 11h", 0, 11), ("D0 14h", 0, 14), ("D0 16h", 0, 16), ("D0 18h", 0, 18)]
OBS_LAG = pd.Timedelta(minutes=10)
NBM_LAG = pd.Timedelta(hours=2)
OM_LAG = pd.Timedelta(hours=8)
OM_MODELS = ["best_match", "ecmwf_ifs025", "gfs_seamless", "icon_seamless"]


def local_ts(date, hour, tz):
    return pd.Timestamp(year=date.year, month=date.month, day=date.day, hour=hour).tz_localize(tz).tz_convert("UTC")


def nbm_table(icao):
    fp = f"{D}/nbs/{icao}.parquet"
    if not os.path.exists(fp):
        return None
    n = pd.read_parquet(fp)
    n = n.dropna(subset=["tmp"])
    n["avail"] = n.runtime + NBM_LAG
    return n


def om_table(icao):
    for sub in ("fc", "fc_recent"):
        fp = f"{D}/{sub}/{icao}.parquet"
        if os.path.exists(fp):
            df = pd.read_parquet(fp)
            if df.filter(like="previous_day1").notna().mean().mean() > 0.5:
                return df.set_index("time").sort_index()
    return None


def om_daymax(om, date, tz, tau, unit, after=None):
    start = local_ts(date, 0, tz)
    hrs = pd.date_range(start, periods=24, freq="h")
    if after is not None:
        hrs = hrs[hrs > after]
    if len(hrs) == 0:
        return {}
    sub = om.reindex(hrs)
    out = {}
    for m in OM_MODELS:
        vals = np.full(len(hrs), np.nan)
        for N in (1, 2, 3):
            col = f"temperature_2m_previous_day{N}_{m}"
            if col not in sub:
                continue
            ok = (hrs - pd.Timedelta(hours=24 * N) + OM_LAG <= tau) & np.isnan(vals)
            vals = np.where(ok, sub[col].values, vals)
        if np.isnan(vals).mean() > 0.2:
            continue
        v = np.nanmax(vals)
        out[m] = float(c2f(v)) if unit == "F" else float(v)
    return out


def station_rows(icao, unit, d0, d1):
    tz = TZ[icao]
    obs = load_obs(icao, unit)
    if obs is None:
        return []
    nbm = nbm_table(icao) if unit == "F" else None
    om = om_table(icao)
    obs_by_date = {d: x for d, x in obs.groupby("ldate")}
    dm = obs.groupby("ldate").agg(y=("t", "max"), nobs=("t", "size"))
    if nbm is not None:
        txn = nbm[nbm.txn.notna() & (nbm.ftime.dt.hour == 0)].sort_values("avail")
        txn_by_ft = {k: v for k, v in txn.groupby("ftime")}
        nbm_by_run = {k: v.sort_values("ftime") for k, v in nbm.groupby("runtime")}
    rows = []
    for date in pd.date_range(d0, d1, freq="D").date:
        if date not in dm.index:
            continue
        y = dm.at[date, "y"]; nobs_day = dm.at[date, "nobs"]
        od = obs_by_date.get(date)
        for dname, doff, hr in DECISIONS:
            ddate = (pd.Timestamp(date) + pd.Timedelta(days=doff)).date()
            tau = local_ts(ddate, hr, tz)
            r = dict(icao=icao, unit=unit, date=date, dec=dname, tau=tau, y=y, nobs_day=nobs_day)
            if doff == 0 and od is not None:
                so = od[od.utc <= tau - OBS_LAG]
                if len(so):
                    r["obs_max"] = so.t.max(); r["obs_last"] = so.t.iloc[-1]; r["obs_last_f"] = so.tmpf.iloc[-1]
                    r["obs_last_age_h"] = (tau - so.utc.iloc[-1]).total_seconds() / 3600
                r["n_obs"] = len(so)
                rest = od[od.utc > tau - OBS_LAG]
                r["z"] = rest.t.max() if len(rest) else np.nan  # realized max after tau (target for intraday)
            if nbm is not None:
                ft = (pd.Timestamp(date) + pd.Timedelta(days=1)).tz_localize("UTC")
                c = txn_by_ft.get(ft)
                if c is not None:
                    c = c[c.avail <= tau]
                    if len(c):
                        last = c.iloc[-1]
                        r["nbm_txn"] = last.txn; r["nbm_xnd"] = last.xnd
                        r["nbm_age_h"] = (tau - last.runtime).total_seconds() / 3600
                        rr = nbm_by_run[last.runtime]
                        day_end = local_ts(date, 0, tz) + pd.Timedelta(days=1)
                        rem = rr[(rr.ftime > tau) & (rr.ftime < day_end)]
                        r["nbm_rem_max"] = rem.tmp.max() if len(rem) else np.nan
                        k = np.argmin(np.abs((rr.ftime - tau).dt.total_seconds().values))
                        r["nbm_tmp_now"] = rr.tmp.iloc[k]
            if om is not None:
                for m, v in om_daymax(om, date, tz, tau, unit).items():
                    r[f"om_{m}"] = v
                if doff == 0:
                    for m, v in om_daymax(om, date, tz, tau, unit, after=tau).items():
                        r[f"omrem_{m}"] = v
            rows.append(r)
    return rows


def build(only=None):
    R = pd.read_parquet(f"{D}/events_resolved.parquet")
    R = R[(R.kind == "highest") & R.clean & R.icao.isin(list(TZ))]
    R = R.assign(date=pd.to_datetime(R.date, errors="coerce")).dropna(subset=["date"])
    pairs = R.groupby(["icao", "unit"]).date.agg(["min", "max"]).reset_index()
    out = []
    for _, p in pairs.iterrows():
        if only and p.icao not in only:
            continue
        if p.icao in ("HKO", "CWA46692"):
            continue
        d0 = pd.Timestamp("2024-12-02"); d1 = pd.Timestamp(p["max"])
        rows = station_rows(p.icao, p.unit, d0, d1)
        print(p.icao, p.unit, len(rows), flush=True)
        if rows:
            df = pd.DataFrame(rows)
            df.to_parquet(f"{D}/feat/{p.icao}_{p.unit}.parquet")
            out.append(df)
    return pd.concat(out) if out else None


if __name__ == "__main__":
    os.makedirs(f"{D}/feat", exist_ok=True)
    only = sys.argv[1:] or None
    F = build(only)
    print(F.shape)
