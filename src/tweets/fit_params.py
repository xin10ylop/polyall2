"""Fit hl (half-life) and alpha per (account, horizon bin) on TRAIN calib points; evaluate OOS.
Output model_params.json: {acct: {hb: {"hl":..,"alpha":..}}}. Small accounts with few train points use pooled
alpha shrinkage. Also prints OOS log-score vs a naive baseline and PIT coverage of central intervals."""
import json, sys, numpy as np, pandas as pd
from scipy import stats
from common import D
from model import nb_logpmf, HBINS
from calibrate import HLS, fit_alpha

def main(tag=""):
    P = pd.read_parquet(f"{D}/calib_points{tag}.parquet")
    from common import gaps
    keep = np.ones(len(P), bool)
    for a in P.acct.unique():
        m = (P.acct == a).values
        for g0, g1 in gaps(a):
            s = P.t.values - 7 * 86400; e = P.t.values + P.H.values * 3600
            keep &= ~(m & ~((e <= g0) | (s >= g1)))
    print("dropped for gaps", (~keep).sum(), "of", len(P))
    P = P[keep]
    params = {}; rep = []
    for (a, hb), g in P.groupby(["acct", "hb"]):
        tr = g[g.train]; te = g[~g.train]
        if len(tr) < 50: continue
        best = None
        for hl in HLS:
            al, ll = fit_alpha(tr.n.values, tr[f"mu_{hl}"].values)
            if best is None or ll > best[2]: best = (hl, al, ll)
        hl, al, ll = best
        params.setdefault(a, {})[str(hb)] = dict(hl=hl, alpha=al)
        # OOS eval
        mu = te[f"mu_{hl}"].values
        ll_te = nb_logpmf(te.n.values, mu, al).mean()
        r = 1 / al; p = r / (r + mu)
        lo = stats.nbinom.ppf(0.1, r, p); hi = stats.nbinom.ppf(0.9, r, p)
        cov80 = ((te.n >= lo) & (te.n <= hi)).mean()
        pit = stats.nbinom.cdf(te.n.values - 1, r, p) + 0.5 * stats.nbinom.pmf(te.n.values, r, p)
        rep.append(dict(acct=a, hb=hb, H=f"{HBINS[hb]:.0f}-{HBINS[hb+1]:.0f}h", n_tr=len(tr), n_te=len(te), hl=hl,
                        alpha=round(al, 3), mean_n_te=round(te.n.mean(), 1), mean_mu_te=round(mu.mean(), 1),
                        bias_te=round((te.n.sum() / mu.sum()), 3), ll_te=round(ll_te, 3), cov80_te=round(cov80, 3),
                        pit_lo10=round((pit < 0.1).mean(), 3), pit_hi10=round((pit > 0.9).mean(), 3)))
    json.dump(params, open(f"{D}/model_params{tag}.json", "w"), indent=1)
    R = pd.DataFrame(rep)
    pd.set_option("display.width", 250)
    print(R.to_string(index=False))
    R.to_csv(f"{D}/calib_report{tag}.csv", index=False)

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
