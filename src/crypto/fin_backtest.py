"""Backtests for finance barrier markets (panel_fin_barrier.parquet). Taker entries at 16:00 UTC decision times.
Fill models: 'mid' = mid +/- cost (cost by family & price bucket: max(1c, 1.5x median effective half-spread));
'real' = first actual taker fill in (t+60s, t+15min] on the needed side (fallback mid-based; skip if > planned+1c).
Fee = rate*p*(1-p) per share (finance rate 0.04). H1 = t < 2026-06-15, H2 >= 2026-06-15."""
import numpy as np, pandas as pd
from common import DATA

SPLIT = pd.Timestamp('2026-06-15', tz='UTC').timestamp()


def fee(p, rate):
    return rate * p * (1 - p)


def cost(d):
    q = np.minimum(d.mid.values, 1 - d.mid.values)
    base = np.where(q < 0.03, 0.005, np.where(q < 0.1, 0.01, 0.015))
    wide = d.fam.isin(['ng', 'nvda', 'silver', 'spy']).values
    return base + np.where(wide & (q >= 0.03), 0.005, 0.0)


def run(pn, pcol='p_model', theta=0.05, fill='mid', pmin=0.03, pmax=0.97, sides=(1, -1)):
    d = pn.dropna(subset=[pcol]).copy()
    c = cost(d); r = d.fee_rate.values
    ya = np.clip(d.mid.values + c, 0.001, 0.999); na = np.clip(1 - d.mid.values + c, 0.001, 0.999)
    p = d[pcol].values
    ey = p - ya - fee(ya, r); en = (1 - p) - na - fee(na, r)
    by = (ey > theta) & (ey >= en) & (ya >= pmin) & (ya <= pmax) & (1 in sides)
    bn = (en > theta) & (en > ey) & (na >= pmin) & (na <= pmax) & (-1 in sides)
    sel = by | bn
    t = d[sel].copy(); side = np.where(by, 1, -1)[sel]; plan = np.where(by, ya, na)[sel]
    if fill == 'real':
        rp = np.where(side == 1, t.ask_slow.values, 1 - t.bid_slow.values)
        px = np.where(np.isfinite(rp), rp, plan)
        px = np.where(px <= plan + 0.01, px, np.nan)
    else:
        px = plan
    t['side'] = side; t['price'] = px; t['fee'] = fee(px, t.fee_rate.values)
    t = t[np.isfinite(t.price)]
    t['win'] = np.where(t.side == 1, t.y, 1 - t.y)
    t['pnl'] = t.win - t.price - t.fee
    t['roi'] = t.pnl / (t.price + t.fee)
    return t


def summ(t, stakes=(10, 50, 200)):
    if not len(t):
        return {'n': 0}
    t = t.sort_values('t')
    ev = t.groupby('event_slug').roi.sum()
    o = {'n': len(t), 'events': t.event_slug.nunique(), 'hit': t.win.mean(), 'avg_px': t.price.mean(),
         'ROI%': 100 * t.pnl.sum() / (t.price + t.fee).sum(),
         't_ev': ev.mean() / ev.std() * np.sqrt(len(ev)) if len(ev) > 2 and ev.std() > 0 else np.nan,
         'trades/day': len(t) / max((t.t.max() - t.t.min()) / 86400, 1)}
    for s in stakes:
        pnl = s * t.roi.values; cum = np.cumsum(pnl)
        o[f'PnL${s}'] = pnl.sum(); o[f'maxDD${s}'] = float(np.max(np.maximum.accumulate(np.concatenate([[0], cum]))[1:] - cum))
    return o
