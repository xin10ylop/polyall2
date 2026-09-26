"""Walk-forward fitting of the Student-t scale model and OOS prediction for panel rows.
Model used for a decision at time t is fitted only on training rows whose outcome time T (+2 min)
is <= first day of the calendar month containing t (expanding window)."""
import numpy as np, pandas as pd
from volmodel import fit_t, p_above, scale
from common import DATA

SPECS = ['dvol', 'rv', 'combo']


def month_start_ts(m):
    return int(pd.Timestamp(m + '-01', tz='UTC').timestamp())


def nearest_h(h, hs):
    hs = np.asarray(hs)
    return hs[np.argmin(np.abs(np.log(hs) - np.log(h)))]


def fit_all(train, months, hs, specs=SPECS, min_train_days=60):
    """returns dict[(month, h, spec)] -> params"""
    P = {}
    for m in months:
        cut = month_start_ts(m)
        for h in hs:
            tr = train[(train.h == h) & (train['T'] + 120 <= cut)]
            if tr['T'].nunique() < min_train_days * 24:
                continue
            for sp in specs:
                if sp in ('dvol', 'combo') and tr.dvol.isna().all():
                    continue
                P[(m, h, sp)] = fit_t(tr, sp)
    return P


def predict(panel, P, K_col='K', specs=SPECS, hs_train=None):
    """panel must have columns t, T, h, S_t, tau_min, seas, rv*, dvol, and K_col.
    Adds p_<spec> and p_<spec>_g (gaussian with same variance) + s_<spec>."""
    panel = panel.copy()
    panel['month'] = pd.to_datetime(panel.t, unit='s').dt.strftime('%Y-%m')
    for sp in specs:
        panel[f'p_{sp}'] = np.nan; panel[f'p_{sp}_g'] = np.nan; panel[f's_{sp}'] = np.nan
    for (m, h), idx in panel.groupby(['month', 'h']).groups.items():
        hh = h if hs_train is None else nearest_h(h, hs_train)
        for sp in specs:
            prm = P.get((m, hh, sp))
            if prm is None:
                continue
            sub = panel.loc[idx]
            panel.loc[idx, f'p_{sp}'] = p_above(prm, sub, sub[K_col].values)
            panel.loc[idx, f'p_{sp}_g'] = p_above(prm, sub, sub[K_col].values, gaussian=True)
            panel.loc[idx, f's_{sp}'] = scale(prm, sub)
    return panel
