"""Family (a): 'X above K on <date>' (noon-ET daily) — model vs market, calibration, walk-forward backtest.
Usage: python analyze_above.py BTC btc-multi-strikes-weekly bitcoin-above-on
Outputs: data/crypto/panel_above_<ASSET>.parquet (panel with market mids, trade fills and OOS model probs)
"""
import sys
import numpy as np, pandas as pd
from common import DATA, to_unix
from panel import build
from volmodel import Features
from walkforward import fit_all, predict, SPECS
from train_samples import H_LIST

HOURS = [120, 72, 48, 24, 12, 6, 3, 1, 0.5]


def make_panel(asset, series, prefix, res_offset=0, hours=HOURS, rebuild=False, suffix=''):
    out = DATA / f'panel_above_{asset}_{prefix}{suffix}.parquet'
    if out.exists() and not rebuild:
        return pd.read_parquet(out)
    mk = pd.read_parquet(DATA / f'markets_{series}.parquet')
    mk = mk[mk.event_slug.str.startswith(prefix) & mk.res_yes.notna() & (mk.kind == 'above')].copy()
    mk['cid'] = mk.condition_id
    mk['T'] = to_unix(mk.event_end)
    pn = build(series, mk, hours)
    pn = pn.merge(mk[['cid', 'T', 'k1', 'res_yes', 'event_slug', 'volume', 'fees_enabled']], on='cid')
    pn = pn.rename(columns={'k1': 'K', 'res_yes': 'y'})
    F = Features(asset)
    ft = F.build(pn.t.values, pn['T'].values, res_offset=res_offset)
    for c in ['S_t', 'S_T', 'tau_min', 'seas', 'rv6h', 'rv24h', 'rv168h', 'dvol']:
        pn[c] = ft[c].values
    # sanity: realised outcome consistent with Binance
    pn['y_bin'] = (pn.S_T > pn.K).astype(float)
    train = pd.read_parquet(DATA / f'train_{asset}.parquet')
    months = sorted(pd.to_datetime(pn.t, unit='s').dt.strftime('%Y-%m').unique())
    specs = SPECS if asset in ('BTC', 'ETH') else ['rv']
    P = fit_all(train, months, H_LIST, specs=specs)
    pn = predict(pn, P, K_col='K', specs=specs, hs_train=H_LIST)
    pn.to_parquet(out, compression='zstd')
    return pn


if __name__ == '__main__':
    asset, series, prefix = sys.argv[1:4]
    if '--early' in sys.argv:
        pn = make_panel(asset, series, prefix, hours=[160, 144, 96], rebuild=True, suffix='_early')
    else:
        pn = make_panel(asset, series, prefix, rebuild='--rebuild' in sys.argv)
    print(pn.groupby('h').size())
    print('outcome mismatch vs binance:', (pn.y != pn.y_bin).sum())
