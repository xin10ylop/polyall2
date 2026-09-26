"""Daily-max features from ECMWF IFS mx2t3 point series, strictly using runs available at each decision time
(run init + 8h <= tau). Output: data/weather/ecmwf_daily.parquet (icao, unit, date, dec, ec_max, ec_rem, ec_sofar, ec_age_h)."""
import glob, os
import numpy as np
import pandas as pd
from common import D, TZ, c2f
from features import DECISIONS, local_ts

LAG = pd.Timedelta(hours=8)


def main():
    fs = sorted(glob.glob(f"{D}/ecmwf/*.parquet"))
    E = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    E["run"] = pd.to_datetime(E.run, utc=True)
    E["vend"] = E.run + pd.to_timedelta(E.step, unit="h")      # window end
    E["vmid"] = E.vend - pd.Timedelta(minutes=90)               # window midpoint
    E["avail"] = E.run + LAG
    R = pd.read_parquet(f"{D}/events_resolved.parquet")
    R = R[(R.kind == "highest") & R.clean & R.icao.isin(list(TZ))]
    R["date"] = pd.to_datetime(R.date, errors="coerce")
    pairs = R.dropna(subset=["date"]).groupby(["icao", "unit"]).size().reset_index()[["icao", "unit"]]
    runs = np.array(sorted(E.run.dt.tz_convert(None).unique()), dtype="datetime64[ns]")
    avail = runs + np.timedelta64(8, "h")
    rows = []
    d0, d1 = E.run.min().normalize() + pd.Timedelta(days=2), E.run.max().normalize() + pd.Timedelta(days=2)
    for _, p in pairs.iterrows():
        tz = TZ[p.icao]
        e = E[E.icao == p.icao]
        by_run = {k: v.sort_values("vend") for k, v in e.groupby("run")}
        for date in pd.date_range(d0.tz_localize(None), d1.tz_localize(None), freq="D"):
            day0 = local_ts(date.date(), 0, tz); day1 = day0 + pd.Timedelta(days=1)
            for dname, doff, hr in DECISIONS:
                tau = local_ts((date + pd.Timedelta(days=doff)).date(), hr, tz)
                k = np.searchsorted(avail, np.datetime64(tau.tz_convert(None)), side="right") - 1
                if k < 0:
                    continue
                run = pd.Timestamp(runs[k])
                if run.tzinfo is None:
                    run = run.tz_localize("UTC")
                x = by_run.get(run)
                if x is None:
                    continue
                inday = x[(x.vmid >= day0) & (x.vmid < day1)]
                if len(inday) < 7:   # need (almost) full day coverage
                    continue
                v = inday.mx2t3.values
                conv = (lambda a: c2f(a)) if p.unit == "F" else (lambda a: a)
                r = dict(icao=p.icao, unit=p.unit, date=date, dec=dname, ec_max=float(conv(v.max())),
                         ec_age_h=(tau - run).total_seconds() / 3600)
                rem = inday[inday.vend > tau]
                so = inday[inday.vend <= tau]
                r["ec_rem"] = float(conv(rem.mx2t3.max())) if len(rem) else np.nan
                r["ec_sofar"] = float(conv(so.mx2t3.max())) if len(so) else np.nan
                rows.append(r)
        print(p.icao, p.unit, flush=True)
    out = pd.DataFrame(rows)
    out.to_parquet(f"{D}/ecmwf_daily.parquet")
    print(out.shape)


if __name__ == "__main__":
    main()
