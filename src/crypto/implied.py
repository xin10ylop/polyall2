"""Market-implied distribution per (event, decision time): fit log-normal location/scale to the strike ladder mids.
P(S_T > K) = Phi((m - ln K)/v)  with m = implied median log-price, v = implied st.dev of ln S_T.
Compares v with the model scale (Gaussian-equivalent st.dev) and with realised |r|."""
import numpy as np, pandas as pd
from scipy import optimize, stats


def fit_event(K, mid, S):
    ok = (mid > 0.03) & (mid < 0.97)
    if ok.sum() < 2:
        return np.nan, np.nan, ok.sum()
    k = np.log(K[ok]); p = mid[ok]
    z = stats.norm.ppf(p)
    # linear in probit space: z = (m - k)/v  -> z = a + b k, v = -1/b, m = a*v
    A = np.column_stack([np.ones_like(k), k])
    (a, b), *_ = np.linalg.lstsq(A, z, rcond=None)
    if b >= 0:
        return np.nan, np.nan, ok.sum()
    v = -1 / b; m = a * v
    return m - np.log(S), v, ok.sum()


def implied_table(pn, scol='s_combo'):
    rows = []
    for (ev, h), g in pn.groupby(['event_slug', 'h']):
        S = g.S_t.iloc[0]
        mu, v, n = fit_event(g.K.values, g.mid.values, S)
        nu = 4.5
        rows.append(dict(event_slug=ev, h=h, t=g.t.iloc[0], S_t=S, S_T=g.S_T.iloc[0], mu_imp=mu, v_imp=v, n_strikes=n,
                         v_model=g[scol].iloc[0] if scol in g else np.nan, r=np.log(g.S_T.iloc[0] / S)))
    return pd.DataFrame(rows)
