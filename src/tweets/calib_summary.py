"""OOS calibration summary of the count model using walk-forward monthly params (decision points t >= 2026-06-01)."""
import json, numpy as np, pandas as pd
from scipy import stats
from common import D
from walkforward import load
from model import nb_logpmf, HBINS

W = json.load(open(f"{D}/wf_params.json"))
P = load("")
cut = pd.Timestamp("2026-06-01", tz="UTC").value // 10**9
te = P[P.t >= cut].copy()
te["m"] = pd.to_datetime(te.t, unit="s", utc=True).dt.strftime("%Y-%m")
rows = []
for (a, hb, m), g in te.groupby(["acct", "hb", "m"]):
    p = W.get(m, {}).get(a, {}).get(str(hb))
    if not p: continue
    mu = g[f"mu_{p['hl']}"].values; al = p["alpha"]; r = 1 / al; pp = r / (r + mu)
    pit = stats.nbinom.cdf(g.n.values - 1, r, pp) + stats.uniform.rvs(size=len(g), random_state=0) * stats.nbinom.pmf(g.n.values, r, pp)
    rows.append(pd.DataFrame(dict(acct=a, hb=hb, n=g.n.values, mu=mu, pit=pit, ll=nb_logpmf(g.n.values, mu, al))))
R = pd.concat(rows)
R["H"] = pd.cut(R.hb, [-1, 2, 4, 6, 9], labels=["<8h", "8-32h", "32-128h", ">128h"])
out = R.groupby(["acct", "H"], observed=True).agg(points=("n", "size"), mean_actual=("n", "mean"), mean_pred=("mu", "mean"),
                                   cov80=("pit", lambda x: ((x > 0.1) & (x < 0.9)).mean()),
                                   below10=("pit", lambda x: (x < 0.1).mean()), above90=("pit", lambda x: (x > 0.9).mean()))
out["ratio"] = out.mean_actual / out.mean_pred
print(out.round(3).to_string())
out.round(3).to_csv(f"{D}/calib_oos_summary.csv")
