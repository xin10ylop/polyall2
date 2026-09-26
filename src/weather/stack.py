"""Does the model add information to market prices?  Multinomial-logit stacking per decision time:
   P_j  proportional to  exp(a*log p_mkt_j + b*log q_j)
Fit (a, b) on a training period, evaluate log-loss out of sample vs the market alone (a=1, b=0)."""
import numpy as np
import pandas as pd
from scipy.optimize import minimize


def _prep(B):
    B = B.sort_values(["event_id", "dec", "mi"]).copy()
    B["lp"] = np.log(np.clip(B.p_mkt, 0.002, 1)); B["lq"] = np.log(np.clip(B.q, 0.002, 1))
    B["g"] = B.groupby(["event_id", "dec"]).ngroup()
    return B


def nll(params, lp, lq, g, win, ng):
    a, b = params
    s = a * lp + b * lq
    m = np.zeros(ng); np.maximum.at(m, g, s) if False else None
    e = np.exp(s - s.max())
    den = np.bincount(g, e, ng)
    num = np.bincount(g, e * win, ng)
    return -np.mean(np.log(np.clip(num / den, 1e-9, 1)))


def fit(B):
    B = _prep(B)
    ng = B.g.max() + 1
    r = minimize(nll, x0=[1.0, 0.0], args=(B.lp.values, B.lq.values, B.g.values, B.win.values, ng), method="Nelder-Mead")
    return r.x


def evaluate(B, split_date):
    out = []
    for dec, x in B.groupby("dec"):
        tr = x[x.date < split_date]; te = x[x.date >= split_date]
        if tr.event_id.nunique() < 50 or te.event_id.nunique() < 20:
            continue
        a, b = fit(tr)
        T = _prep(te); ng = T.g.max() + 1
        ll_mkt = nll([1, 0], T.lp.values, T.lq.values, T.g.values, T.win.values, ng)
        ll_mod = nll([0, 1], T.lp.values, T.lq.values, T.g.values, T.win.values, ng)
        ll_stk = nll([a, b], T.lp.values, T.lq.values, T.g.values, T.win.values, ng)
        out.append(dict(dec=dec, n_train=tr.event_id.nunique(), n_test=te.event_id.nunique(), a=a, b=b,
                        ll_mkt=ll_mkt, ll_model=ll_mod, ll_stack=ll_stk, gain=ll_mkt - ll_stk))
    return pd.DataFrame(out)


def apply_stack(B, split_date):
    """Walk-forward: returns B with q_stack for rows on/after split_date (params fit on rows before)."""
    parts = []
    for dec, x in B.groupby("dec"):
        tr = x[x.date < split_date]; te = x[x.date >= split_date].copy()
        a, b = fit(tr)
        T = _prep(te)
        s = a * T.lp + b * T.lq
        e = np.exp(s)
        T["q_stack"] = e / e.groupby(T.g).transform("sum")
        parts.append(T)
    return pd.concat(parts)
