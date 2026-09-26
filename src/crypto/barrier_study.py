"""Barrier longshot sale: cross-asset replication, loss clustering, pre-registered risk filter.
Rule: strike untouched, <=12h to window end, YES mid in [0.5c,3c) (bucket A) or [3c,6c) (bucket B); buy NO.
Fills: 'mid' = 1-mid+0.3c (A) / +1c (B); 'real' = first actual taker NO-buy/YES-sell fill in (t+60s, t+15min]
(fallback to 'mid' price when no fill; share with a real fill reported). Taker fee 0.07 p(1-p) always charged.
Split: H1 = decision time < 2026-06-15, H2 >= 2026-06-15."""
import sys
import numpy as np, pandas as pd
from common import DATA, taker_fee_per_share as fee
from volmodel import load_spot, load_dvol

SPLIT = pd.Timestamp('2026-06-15', tz='UTC').timestamp()
NOW = pd.Timestamp('2026-09-26', tz='UTC').timestamp()
ASSETS = ['BTC', 'ETH', 'SOL', 'XRP']


def load():
    out = []
    for a in ASSETS:
        p = DATA / f'panel_touch_{a}_barrier.parquet'
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        d['asset'] = a
        out.append(d)
    pn = pd.concat(out, ignore_index=True)
    bad = pn.event_slug.str.contains('before-|hit-in-20\\d\\d$', regex=True)
    pn = pn[(pn.W1 < NOW) & ~bad & (pn.stale <= 3600)].copy()
    pn['fam'] = pn.series.str.extract(r'hit-price-(\w+)$')[0]
    pn['half'] = np.where(pn.t < SPLIT, 'H1', 'H2')
    pn['day'] = pd.to_datetime(pn.t, unit='s').dt.strftime('%Y-%m-%d')
    return pn


def price(d, bucket):
    c = 0.003 if bucket == 'A' else 0.01
    mid_px = np.clip(1 - d.mid.values + c, 0, 0.999)
    real = 1 - d.bid_slow.values if 'bid_slow' in d else np.full(len(d), np.nan)
    has_real = np.isfinite(real)
    real_px = np.where(has_real, real, mid_px)
    return mid_px, real_px, has_real


def add_pnl(d, bucket):
    d = d.copy()
    mid_px, real_px, has_real = price(d, bucket)
    d['has_real'] = has_real
    for lab, px in (('mid', mid_px), ('real', real_px)):
        d[f'px_{lab}'] = px
        d[f'pnl_{lab}'] = (1 - d.y.values) - px - fee(px)
        d[f'roi_{lab}'] = d[f'pnl_{lab}'] / (px + fee(px))
    return d


def select(pn, bucket, tmax=12, tmin=0):
    lo, hi = (0.005, 0.03) if bucket == 'A' else (0.03, 0.06)
    d = pn[(pn.mid >= lo) & (pn.mid < hi) & (pn.tau_h <= tmax) & (pn.tau_h > tmin)]
    return add_pnl(d, bucket)


def roi(g, lab):
    c = g[f'px_{lab}'] + fee(g[f'px_{lab}'])
    return g[f'pnl_{lab}'].sum() / c.sum() if len(g) else np.nan


def table(d):
    rows = []
    for key, g in d.groupby(['asset', 'fam']):
        first = g.sort_values('t').groupby('cid').head(1)
        ev = g.groupby('event_slug').roi_real.mean()
        rows.append({'asset': key[0], 'family': key[1], 'rows': len(g), 'markets': g.cid.nunique(), 'events': g.event_slug.nunique(),
                     'loss_rows': int(g.y.sum()), 'loss_days': g[g.y == 1].day.nunique(), 'avg_yes_mid': g.mid.mean(),
                     'ROI_mid%': 100 * roi(g, 'mid'), 'ROI_real%': 100 * roi(g, 'real'), 'real_fill_share': g.has_real.mean(),
                     'H1_n': int((g.half == 'H1').sum()), 'H1_ROI_real%': 100 * roi(g[g.half == 'H1'], 'real'),
                     'H2_n': int((g.half == 'H2').sum()), 'H2_ROI_real%': 100 * roi(g[g.half == 'H2'], 'real'),
                     'one_per_mkt_ROI_real%': 100 * roi(first, 'real'),
                     'realonly_n': int(g.has_real.sum()), 'realonly_ROI%': 100 * roi(g[g.has_real], 'real'),
                     't_event': ev.mean() / ev.std() * np.sqrt(len(ev)) if len(ev) > 2 and ev.std() > 0 else np.nan})
    return pd.DataFrame(rows)


def vol_thresholds(pn):
    """Pre-registered on H1: 90th percentile of hourly rv1h (all hours in H1 window) and of DVOL, per asset."""
    th = {}
    h1_start = pd.Timestamp('2026-03-01', tz='UTC').timestamp()
    for a in ASSETS:
        sp = load_spot(a)['c']
        s = sp.loc[h1_start - 3600: SPLIT]
        r = np.diff(np.log(s.values))
        n = len(r) // 60
        rv = np.sqrt((r[:n * 60].reshape(n, 60) ** 2).sum(1) * 365 * 24)
        dv = load_dvol(a)
        dv = dv[(dv.index >= h1_start) & (dv.index < SPLIT)]
        th[a] = {'rv1h_p90': float(np.percentile(rv, 90)), 'dvol_p90': float(np.percentile(dv.values, 90)) / 100}
    return th


def filters(d, th):
    rv_hi = np.array([d.rv1h.values[i] > th[a]['rv1h_p90'] for i, a in enumerate(d.asset.values)])
    dv_hi = np.array([d.dvol.values[i] > th[a]['dvol_p90'] for i, a in enumerate(d.asset.values)])
    F = {'none': np.zeros(len(d), bool), 'rv1h_top10': rv_hi, 'dvol_top10': dv_hi, 'rv_or_dvol_top10': rv_hi | dv_hi}
    for k in (2.0, 2.5, 3.0, 3.5):
        F[f'x<{k}'] = d.x.values < k
    return F


if __name__ == '__main__':
    pn = load()
    print(pn.groupby(['asset', 'fam']).size().unstack())
    A = select(pn, 'A')
    print(table(A).round(3).to_string())
    B = select(pn, 'B')
    print(table(B).round(3).to_string())
