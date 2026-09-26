"""Dead-bucket prints relative to the AWC METAR receipt time (last ~15 days only)."""
import numpy as np
import pandas as pd
from common import D
from dead_latency import FINE

O = pd.read_parquet(f"{D}/dead_opps.parquet")
P = pd.read_parquet(f"{D}/dead_prints.parquet")
R = pd.read_parquet(f"{D}/metar_receipts.parquet")
R["valid"] = R.obs.dt.tz_convert(None).values.astype("datetime64[s]").astype(np.int64)
R = R.sort_values("receipt").drop_duplicates(["icao", "valid"])  # first receipt of each obs
R["rdelay"] = R.delay_s
o = O.merge(R[["icao", "valid", "rdelay"]], on=["icao", "valid"], how="inner")
print("deaths matched to AWC receipts:", len(o), "of", (O.date >= R.obs.min().tz_convert(None).normalize()).sum(), "deaths since", R.obs.min())
print("AWC receipt delay of killing METARs (s):", o.rdelay.quantile([.1, .25, .5, .75, .9]).round(0).to_dict())
p = P.merge(o[["opp", "rdelay", "kind", "margin", "win"]], on="opp")
p["dtr"] = p.dtv - p.rdelay
bins = [-900, -300, -120, -60, -30, 0, 10, 20, 30, 60, 120, 300, 600, 1800, 7200]
for kind, m in [("NO_dead", 1)]:
    x = p[(p.kind == kind) & (p.margin == m) & p.exe]
    n = ((o.kind == kind) & (o.margin == m)).sum()
    x = x.assign(bin=pd.cut(x.dtr, bins, right=False))
    g = x.groupby("bin", observed=False)
    t = pd.DataFrame({"opps_with_print": g.opp.nunique() / n, "shares": g.sh.sum(), "med_px": g.px.median(),
                      "opps_px<=0.99": g.apply(lambda y: y[y.px <= 0.99].opp.nunique()) / n,
                      "sh_px<=0.99": g.apply(lambda y: y[y.px <= 0.99].sh.sum()),
                      "usd_edge_px<=0.99": g.apply(lambda y: ((1 - y.px) * y.sh)[y.px <= 0.99].sum())})
    print(f"== {kind} m={m}: {n} deaths, relative to AWC receipt time")
    print(t.round(4).to_string())
