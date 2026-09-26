"""Family (d): Up/Down markets (hourly: Binance 1h candle close>=open; 15m: Chainlink 60s-TWAP end vs start,
≈ Binance terminal close vs start in 97.4% of 19,945 cases).
Decision times: offsets (minutes) relative to window start T0 (negative = before the window opens).
Model: P(Up) = P(S_T1 >= S_T0 | S_t) with walk-forward Student-t scale for the remaining time; before T0 -> 0.5."""
import sys
import numpy as np, pandas as pd
from common import DATA, to_unix
from panel import load_shards
from volmodel import Features, fit_t, scale
from walkforward import fit_all, nearest_h
from scipy import stats

CFG = {'btc-up-or-down-hourly': (60, [-10, 5, 10, 20, 30, 40, 50, 55]),
       'btc-up-or-down-15m': (15, [-5, 2, 5, 8, 10, 12])}


def make_panel(series, rebuild=False):
    L, offs = CFG[series]
    out = DATA / f'panel_updown_{series}.parquet'
    if out.exists() and not rebuild:
        return pd.read_parquet(out)
    mk = pd.read_parquet(DATA / f'markets_{series}.parquet')
    ph = load_shards(series, 'ph')
    mk = mk[mk.condition_id.isin(ph.cid.unique()) & mk.res_yes.notna()].copy()
    mk['T1'] = to_unix(mk.event_end); mk['T0'] = mk.T1 - L * 60
    mk['up_is_yes'] = mk.out0.str.lower().eq('up')
    ph_g = {k: g[g.fid == 1].sort_values('t') for k, g in ph.groupby('cid')}
    rows = []
    for m in mk.itertuples():
        g = ph_g.get(m.condition_id)
        if g is None or len(g) < 5:
            continue
        tv = g.t.values; pv = g.p.values
        for o in offs:
            t = int(m.T0 + o * 60)
            i = np.searchsorted(tv, t, side='right') - 1
            if i < 0 or t - tv[i] > 180:
                continue
            p_yes = float(pv[i])
            j = np.searchsorted(tv, t + 60, side='right') - 1
            j5 = np.searchsorted(tv, t + 180, side='right') - 1
            up = p_yes if m.up_is_yes else 1 - p_yes
            rows.append(dict(cid=m.condition_id, event_slug=m.event_slug, T0=m.T0, T1=m.T1, off=o, t=t,
                             mid=up, mid_d1=(pv[j] if m.up_is_yes else 1 - pv[j]),
                             mid_d3=(pv[j5] if m.up_is_yes else 1 - pv[j5]),
                             y=m.res_yes if m.up_is_yes else 1 - m.res_yes, stale=t - tv[i]))
    pn = pd.DataFrame(rows)
    asset = 'BTC'
    F = Features(asset)
    ft = F.build(pn.t.values, pn.T1.values - 60)   # S_T := close of last 1m candle in the window
    for c in ['S_t', 'S_T', 'tau_min', 'seas', 'rv6h', 'rv24h', 'rv168h', 'dvol']:
        pn[c] = ft[c].values
    pn['S_open'] = F.spot['c'].reindex(pn.T0.values - 60).values
    pn['y_bin'] = (pn.S_T >= pn.S_open).astype(float)
    train = pd.read_parquet(DATA / f'train_{asset}.parquet')
    months = sorted(pd.to_datetime(pn.t, unit='s').dt.strftime('%Y-%m').unique())
    hs = [0.25, 0.5, 1, 2]
    P = fit_all(train, months, hs, specs=['rv', 'combo'])
    pn['month'] = pd.to_datetime(pn.t, unit='s').dt.strftime('%Y-%m')
    for sp in ['rv', 'combo']:
        pn[f'p_{sp}'] = np.nan
        for (mth, o), idx in pn.groupby(['month', 'off']).groups.items():
            sub = pn.loc[idx]
            if o < 0:
                pn.loc[idx, f'p_{sp}'] = 0.5
                continue
            h = nearest_h((L - o) / 60, hs)
            prm = P.get((mth, h, sp))
            if prm is None:
                continue
            s = scale(prm, sub)
            x = np.log(sub.S_open.values / sub.S_t.values) / s
            pn.loc[idx, f'p_{sp}'] = stats.t.sf(x, prm['nu'])
    pn.to_parquet(out, compression='zstd')
    return pn


if __name__ == '__main__':
    s = sys.argv[1]
    pn = make_panel(s, rebuild='--rebuild' in sys.argv)
    print(len(pn), pn.groupby('off').size().to_dict())
    print('agreement binance vs resolution', (pn.y == pn.y_bin).mean())
