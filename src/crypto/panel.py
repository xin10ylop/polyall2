"""Build the market panel: for each market and each decision offset h (hours before expiry T),
record the Polymarket YES mid at t=T-h (no look-ahead: last observed point <= t) and
trade-based executable prices in the window [t, t+W] (fills that actually happened after the signal).
"""
import glob
import numpy as np, pandas as pd
from common import DATA, to_unix


def load_shards(series, prefix):
    fs = sorted(glob.glob(str(DATA / 'ph' / series / f'{prefix}_*.parquet')))
    if not fs:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)


def yes_equiv(tr):
    """Convert taker trades to YES-equivalent direction/price.
    dir=+1: taker bought YES exposure at price px (YES ask evidence); dir=-1: taker sold YES exposure (YES bid)."""
    tr = tr.copy()
    buy_yes = (tr.is_yes == 1) & (tr.side == 1)
    sell_no = (tr.is_yes == 0) & (tr.side == -1)
    sell_yes = (tr.is_yes == 1) & (tr.side == -1)
    buy_no = (tr.is_yes == 0) & (tr.side == 1)
    tr['dir'] = np.where(buy_yes | sell_no, 1, -1)
    tr['px'] = np.where(tr.is_yes == 1, tr.price, 1 - tr.price).astype('float64')
    tr['usd'] = tr['size'] * tr['price']
    return tr


def build(series, markets, hours, W=600, tcol_T='T'):
    """markets: DataFrame with cid, T (unix of expiry/decision reference). Returns panel rows."""
    ph = load_shards(series, 'ph')
    tr = load_shards(series, 'tr')
    ph = ph[ph.cid.isin(markets.cid)]
    tr = yes_equiv(tr[tr.cid.isin(markets.cid)]) if len(tr) else tr
    ph_g = {k: g for k, g in ph.groupby('cid')}
    tr_g = {k: g.sort_values('t') for k, g in tr.groupby('cid')} if len(tr) else {}
    rows = []
    for m in markets.itertuples():
        g = ph_g.get(m.cid)
        if g is None:
            continue
        fine = g[g.fid == 1].sort_values('t')
        coarse = g[g.fid == 15].sort_values('t')
        trg = tr_g.get(m.cid)
        for h in hours:
            t = int(getattr(m, tcol_T) - h * 3600)
            src = fine if (len(fine) and fine.t.iloc[0] <= t) else coarse
            i = np.searchsorted(src.t.values, t, side='right') - 1
            if i < 0:
                continue
            mid = float(src.p.values[i]); stale = t - int(src.t.values[i])
            row = dict(cid=m.cid, h=h, t=t, mid=mid, stale=stale)
            # delayed mids (for 'slow execution' tests): last mid <= t+300 / t+900
            for lab, dly in (('mid_d5', 300), ('mid_d15', 900)):
                j = np.searchsorted(src.t.values, t + dly, side='right') - 1
                row[lab] = float(src.p.values[j]) if j >= 0 and (t + dly - src.t.values[j]) <= 1800 else np.nan
            if trg is not None and len(trg):
                tt = trg.t.values
                a = np.searchsorted(tt, t, side='left'); b = np.searchsorted(tt, t + W, side='right')
                w = trg.iloc[a:b]
                by = w[w.dir == 1]; sy = w[w.dir == -1]
                row['ask_tr'] = float(np.average(by.px, weights=by['size'])) if len(by) else np.nan
                row['ask_first'] = float(by.px.iloc[0]) if len(by) else np.nan
                row['ask_sz'] = float(by['size'].sum())
                row['bid_tr'] = float(np.average(sy.px, weights=sy['size'])) if len(sy) else np.nan
                row['bid_first'] = float(sy.px.iloc[0]) if len(sy) else np.nan
                row['bid_sz'] = float(sy['size'].sum())
                # slow-execution window (t+60s, t+15min]
                a2 = np.searchsorted(tt, t + 60, side='right'); b2 = np.searchsorted(tt, t + 900, side='right')
                w2 = trg.iloc[a2:b2]
                by2 = w2[w2.dir == 1]; sy2 = w2[w2.dir == -1]
                row['ask_slow'] = float(by2.px.iloc[0]) if len(by2) else np.nan
                row['bid_slow'] = float(sy2.px.iloc[0]) if len(sy2) else np.nan
                row['ask_slow_sz'] = float(by2['size'].sum()); row['bid_slow_sz'] = float(sy2['size'].sum())
                # most recent trades before t (stale but pre-decision)
                pre = trg.iloc[max(0, a - 50):a]
                pb = pre[pre.dir == 1]; ps = pre[pre.dir == -1]
                row['ask_prev'] = float(pb.px.iloc[-1]) if len(pb) and t - pb.t.iloc[-1] <= 1800 else np.nan
                row['bid_prev'] = float(ps.px.iloc[-1]) if len(ps) and t - ps.t.iloc[-1] <= 1800 else np.nan
                # activity in the previous 24h
                a24 = np.searchsorted(tt, t - 86400, side='left')
                row['usd_24h'] = float(trg.usd.values[a24:a].sum())
                row['ntr_24h'] = int(a - a24)
            rows.append(row)
    return pd.DataFrame(rows)


def effective_spread(series, markets, max_trades=None):
    """For every taker trade, compare YES-equivalent trade price to the prevailing mid (last fine/coarse mid <= trade time)."""
    ph = load_shards(series, 'ph')
    tr = load_shards(series, 'tr')
    ph = ph[ph.cid.isin(markets.cid)]
    tr = yes_equiv(tr[tr.cid.isin(markets.cid)])
    out = []
    Tmap = dict(zip(markets.cid, markets['T']))
    for cid, g in tr.groupby('cid'):
        p = ph[ph.cid == cid]
        p = p[p.fid == 1].sort_values('t')
        if len(p) < 10:
            continue
        g = g[(g.t >= p.t.iloc[0]) & (g.t <= Tmap[cid] - 60)]
        if not len(g):
            continue
        i = np.searchsorted(p.t.values, g.t.values - 1, side='right') - 1
        ok = i >= 0
        g = g[ok]; i = i[ok]
        mid = p.p.values[i]
        out.append(pd.DataFrame({'cid': cid, 't': g.t.values, 'dir': g.dir.values, 'px': g.px.values,
                                 'size': g['size'].values, 'mid': mid, 'lag': g.t.values - p.t.values[i],
                                 'tte': Tmap[cid] - g.t.values}))
    d = pd.concat(out, ignore_index=True)
    d['half_spread'] = (d.px - d.mid) * d.dir
    return d
