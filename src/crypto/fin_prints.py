"""Print-based (executable) backtest for finance barrier markets, needed because the CLOB midpoint is
meaningless in these books (live snapshot: weekly gold YES bid 0.02-0.50 / ask 0.98).
At each 16:00-UTC decision time t the model gives p. We 'take' NO only at a price someone actually traded at:
the first taker YES-sell / NO-buy print (YES bid hit => NO available at 1-px) in (t+60s, t+W] whose NO price q
satisfies (1-p) - q - fee(q) > theta; symmetric for YES using taker YES-buy prints (YES ask lifted).
Size is capped by the print size. No look-ahead in the signal (p is computed at t)."""
import numpy as np, pandas as pd
from common import DATA
from panel import load_shards, yes_equiv
from fin_backtest import fee, summ, SPLIT


def prints_backtest(pn, theta=0.05, W=3600, sides=(-1, 1)):
    out = []
    for series, d in pn.groupby('series'):
        tr = load_shards(series, 'tr')
        if not len(tr):
            continue
        tr = yes_equiv(tr[tr.cid.isin(d.cid.unique())])
        tg = {k: g.sort_values('t') for k, g in tr.groupby('cid')}
        for r in d.itertuples():
            g = tg.get(r.cid)
            if g is None:
                continue
            tt = g.t.values
            a = np.searchsorted(tt, r.t + 60, side='right'); b = np.searchsorted(tt, r.t + W, side='right')
            w = g.iloc[a:b]
            if not len(w):
                continue
            best = None
            if -1 in sides:
                s = w[w.dir == -1]
                q = 1 - s.px.values
                ok = ((1 - r.p_model) - q - fee(q, r.fee_rate)) > theta
                if ok.any():
                    j = np.argmax(ok)
                    best = (-1, q[j], s['size'].values[j], s.t.values[j])
            if 1 in sides and best is None:
                s = w[w.dir == 1]
                pz = s.px.values
                ok = (r.p_model - pz - fee(pz, r.fee_rate)) > theta
                if ok.any():
                    j = np.argmax(ok)
                    best = (1, pz[j], s['size'].values[j], s.t.values[j])
            if best is None:
                continue
            side, px, sz, tfill = best
            win = r.y if side == 1 else 1 - r.y
            out.append(dict(series=series, fam=r.fam, event_slug=r.event_slug, cid=r.cid, t=r.t, t_fill=tfill, side=side,
                            price=px, size=sz, p_model=r.p_model, mid=r.mid, y=r.y, win=win, fee_rate=r.fee_rate, x=r.x))
    t = pd.DataFrame(out)
    if not len(t):
        return t
    t['fee'] = fee(t.price, t.fee_rate)
    t['pnl'] = t.win - t.price - t.fee
    t['roi'] = t.pnl / (t.price + t.fee)
    t['usd_avail'] = t['size'] * t.price
    return t
