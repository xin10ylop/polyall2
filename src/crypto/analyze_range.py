"""Family (c): 'Bitcoin price on <date>' range buckets (neg-risk, noon-ET Binance 1m close).
Model prob of bucket = P(S_T > K1) - P(S_T > K2) from the walk-forward Student-t model."""
import sys
import numpy as np, pandas as pd
from common import DATA, to_unix
from panel import build
from volmodel import Features
from walkforward import fit_all, predict, SPECS
from train_samples import H_LIST

HOURS = [120, 72, 48, 24, 12, 6, 3, 1, 0.5]


def make_panel(asset, series, prefix, rebuild=False):
    out = DATA / f'panel_range_{asset}.parquet'
    if out.exists() and not rebuild:
        return pd.read_parquet(out)
    mk = pd.read_parquet(DATA / f'markets_{series}.parquet')
    mk = mk[mk.event_slug.str.startswith(prefix) & mk.res_yes.notna() & (mk.kind == 'range')].copy()
    mk['cid'] = mk.condition_id
    mk['T'] = to_unix(mk.event_end)
    pn = build(series, mk, HOURS)
    pn = pn.merge(mk[['cid', 'T', 'k1', 'k2', 'res_yes', 'event_slug', 'volume']], on='cid')
    pn = pn.rename(columns={'res_yes': 'y'})
    pn['K1'] = pn.k1.fillna(1e-9); pn['K2'] = pn.k2.fillna(1e12)
    F = Features(asset)
    ft = F.build(pn.t.values, pn['T'].values)
    for c in ['S_t', 'S_T', 'tau_min', 'seas', 'rv6h', 'rv24h', 'rv168h', 'dvol']:
        pn[c] = ft[c].values
    pn['y_bin'] = ((pn.S_T > pn.K1) & (pn.S_T <= pn.K2)).astype(float)
    train = pd.read_parquet(DATA / f'train_{asset}.parquet')
    months = sorted(pd.to_datetime(pn.t, unit='s').dt.strftime('%Y-%m').unique())
    specs = SPECS if asset in ('BTC', 'ETH') else ['rv']
    P = fit_all(train, months, H_LIST, specs=specs)
    a = predict(pn, P, K_col='K1', specs=specs, hs_train=H_LIST)
    b = predict(pn, P, K_col='K2', specs=specs, hs_train=H_LIST)
    for sp in specs:
        for suf in ('', '_g'):
            pn[f'p_{sp}{suf}'] = np.clip(a[f'p_{sp}{suf}'].values - b[f'p_{sp}{suf}'].values, 0, 1)
    pn.to_parquet(out, compression='zstd')
    return pn


if __name__ == '__main__':
    pn = make_panel('BTC', 'bitcoin-neg-risk-weekly', 'bitcoin-price-on', rebuild='--rebuild' in sys.argv)
    print(pn.groupby('h').size())
    print('outcome mismatch vs binance:', (pn.y != pn.y_bin).sum(), 'of', len(pn))
