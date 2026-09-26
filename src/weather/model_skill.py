"""Model skill on station-days (independent of markets): walk-forward log score / calibration of the
integer daily max for each decision type and forecast source combination."""
import sys
import numpy as np
import pandas as pd
from scipy import stats
from evaluate import load_features, attach_ecmwf
from wf_model import prepeak, intraday, PRE, INTRA, add_base_forecasts
from model import cdf


def int_logscore(y, mu, sig, floor=None):
    lo = cdf(y - 0.5, mu, sig); hi = cdf(y + 0.5, mu, sig)
    if floor is not None:
        lo = np.where(y <= floor, 0.0, lo)
    p = np.clip(hi - lo, 1e-4, 1)
    return -np.log(p)


def pit(y, mu, sig):
    return cdf(y, mu, sig)


def run(stations=None, combos=None):
    F = add_base_forecasts(attach_ecmwf(load_features(stations)))
    F["obs_now"] = np.where(F.unit == "F", F.obs_last_f, F.obs_last)
    combos = combos or [["nbm_txn"], ["f_om"], ["nbm_txn", "f_om"], ["ec_max"], ["nbm_txn", "ec_max"], ["nbm_txn", "f_om", "ec_max"]]
    res = []
    for dec in PRE:
        x = F[F.dec == dec]
        for c in combos:
            if not all(k in x and x[k].notna().mean() > 0.3 for k in c):
                continue
            m = prepeak(x, c)
            m = m[m.mu.notna() & m.sigma.notna() & m.y.notna()]
            for k in c:
                m = m[m[k].notna()]
            ls = int_logscore(m.y.values, m.mu.values, m.sigma.values)
            res.append(dict(dec=dec, src="+".join(c), n=len(m), logscore=ls.mean(), mae=(m.y - m.mu).abs().mean(),
                            sd=(m.y - m.mu).std(), sigma=m.sigma.mean(), pit_lo=(pit(m.y, m.mu, m.sigma) < .1).mean(),
                            pit_hi=(pit(m.y, m.mu, m.sigma) > .9).mean()))
    return pd.DataFrame(res)


if __name__ == "__main__":
    st = sys.argv[1:] or None
    pd.set_option("display.width", 200)
    print(run(st).round(3).to_string())
