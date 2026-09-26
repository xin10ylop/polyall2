"""Family (b): 'What price will Bitcoin hit in <month>/<week>/on <day>?' barrier (touch) markets.

Window [W0, W1): standard markets = calendar window in ET (month / Mon-Sun week / day);
'-from-<date>' re-listings start at market creation. YES iff any Binance 1m High >= H (up) / Low <= H (down).

Model (no look-ahead):
  s = Student-t scale forecast for the remaining horizon tau = W1 - t (walk-forward t-model, nearest trained h)
  x = |ln(H/S_t)| / s
  P_hit = empirical survival of the standardised running extreme  M = max_{u in (t, t+h]} |ln(S_u/S_t)| / s
          (pooled up & down to avoid imprinting the training-period drift), estimated on TRAIN windows only
          (T+h <= first day of the decision month), by horizon bucket; plus the reflection-principle
          benchmark P = min(1, 2 * t_nu.sf(x)).
Decision times: every day at 16:00 UTC while the market is live and not yet touched, plus W1-{12,6,3,1}h.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
from common import DATA, to_unix
from panel import load_shards, yes_equiv
from volmodel import Features, load_spot, fit_t, scale
from walkforward import month_start_ts

H_TOUCH = [3, 6, 12, 24, 48, 72, 120, 168, 336, 720]


def window_start(row):
    W1 = row['event_end'].tz_convert('America/New_York')
    if '-from-' in (row['slug'] or ''):
        return row['m_created']
    fam = row['series']
    if fam.endswith('monthly'):
        return (W1 - pd.Timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0).tz_convert('UTC')
    if fam.endswith('weekly'):
        return (W1 - pd.Timedelta(days=7)).tz_convert('UTC')
    return (W1 - pd.Timedelta(days=1)).tz_convert('UTC')


def extreme_train(asset, F, hs=H_TOUCH, start='2024-10-20'):
    """For hourly t and horizon h: running max/min of ln(High/S_t), ln(Low/S_t) over (t, t+h], plus features."""
    spot = F.spot
    hi = spot['h'].values; lo = spot['l'].values; idx0 = spot.index.values[0]
    T0 = pd.date_range(pd.Timestamp(start, tz='UTC'), pd.Timestamp(int(spot.index.max()), unit='s', tz='UTC') - pd.Timedelta(days=1), freq='h')
    t = ((T0 - pd.Timestamp('1970-01-01', tz='UTC')) // pd.Timedelta('1s')).values.astype('int64')
    out = []
    # sparse-table style running max via pandas rolling on 1m series (forward windows)
    for h in hs:
        n = int(h * 60)
        tt = t[t + n * 60 <= spot.index.max()]
        # forward rolling max of high over next n minutes starting at candle opened at t
        fmax = pd.Series(hi[::-1]).rolling(n, min_periods=1).max().values[::-1]
        fmin = pd.Series(lo[::-1]).rolling(n, min_periods=1).min().values[::-1]
        pos = ((tt - idx0) // 60).astype(int)
        df = F.build(tt, tt + n * 60 - 60)   # S_t, features; T such that tau = h
        df['mx'] = np.log(fmax[pos] / df.S_t.values)
        df['mn'] = np.log(fmin[pos] / df.S_t.values)
        df['h'] = h
        out.append(df)
    return pd.concat(out, ignore_index=True)


def fit_models(tr, months, spec):
    """per (month, h): t-model params on terminal returns + empirical standardised extreme distribution."""
    P = {}
    for m in months:
        cut = month_start_ts(m)
        for h in H_TOUCH:
            d = tr[(tr.h == h) & (tr['T'] + 120 <= cut)].dropna(subset=['r', 'mx', 'mn', 'seas', 'rv24h'])
            if len(d) < 24 * 60:
                continue
            prm = fit_t(d, spec)
            s = scale(prm, d)
            z = np.sort(np.concatenate([d.mx.values / s, -d.mn.values / s]))
            P[(m, h)] = (prm, z)
    return P


def p_hit_emp(z_sorted, x):
    return 1.0 - np.searchsorted(z_sorted, x, side='left') / len(z_sorted)


def make_panel(asset='BTC', series_list=('bitcoin-hit-price-monthly', 'bitcoin-hit-price-weekly', 'bitcoin-hit-price-daily'),
               spec='combo', rebuild=False):
    out = DATA / f'panel_touch_{asset}.parquet'
    if out.exists() and not rebuild:
        return pd.read_parquet(out)
    F = Features(asset)
    spot = F.spot
    trp = (DATA if asset == 'BTC' else Path('/tmp/claude-0/-home-user-polyall2/23837d40-49ff-5c90-86c9-24d18e8ba96d/scratchpad')) / f'train_extreme_{asset}.parquet'
    if trp.exists():
        tr = pd.read_parquet(trp)
    else:
        tr = extreme_train(asset, F)
        tr.to_parquet(trp, compression='zstd')
    rows = []
    for series in series_list:
        mk = pd.read_parquet(DATA / f'markets_{series}.parquet')
        mk = mk[mk.kind.isin(['touch_up', 'touch_down']) & mk.res_yes.notna()].copy()
        ph = load_shards(series, 'ph')
        if not len(ph):
            continue
        mk = mk[mk.condition_id.isin(ph.cid.unique())]
        mk['W0'] = [window_start(r) for _, r in mk.iterrows()]
        mk['W0'] = to_unix(pd.to_datetime(mk.W0, utc=True))
        mk['W1'] = to_unix(mk.event_end)
        mk['t_open'] = to_unix(mk.m_start.fillna(mk.m_created))
        ph_g = {k: g.sort_values('t') for k, g in ph.groupby('cid')}
        trd = load_shards(series, 'tr')
        trd = yes_equiv(trd) if len(trd) else trd
        tr_g = {k: g.sort_values('t') for k, g in trd.groupby('cid')} if len(trd) else {}
        for m in mk.itertuples():
            H = m.k1
            up = m.kind == 'touch_up'
            W0, W1 = int(m.W0) // 60 * 60, int(m.W1)
            seg = spot.loc[W0: W1 - 60]
            if len(seg) == 0:
                continue
            y_bin = float((seg.h.max() >= H) if up else (seg.l.min() <= H))
            # first touch time
            hit_idx = np.where(seg.h.values >= H)[0] if up else np.where(seg.l.values <= H)[0]
            t_hit = int(seg.index.values[hit_idx[0]]) if len(hit_idx) else None
            g = ph_g.get(m.condition_id)
            trg = tr_g.get(m.condition_id)
            dts = list(range((max(W0, m.t_open) // 86400) * 86400 + 16 * 3600, W1 - 3600, 86400))
            dts += [W1 - int(x * 3600) for x in (12, 6, 3, 1)]
            for t in sorted(set(dts)):
                if t <= max(W0, m.t_open) + 1800 or t >= W1 - 1800:
                    continue
                if t_hit is not None and t_hit < t:
                    continue    # already touched -> resolved/trivial
                i = np.searchsorted(g.t.values, t, side='right') - 1
                if i < 0 or t - g.t.values[i] > 3600:
                    continue
                row = dict(cid=m.condition_id, series=series, event_slug=m.event_slug, slug=m.slug, kind=m.kind, H=H,
                           W0=W0, W1=W1, t=t, tau_h=(W1 - t) / 3600, mid=float(g.p.values[i]), stale=t - int(g.t.values[i]),
                           y=m.res_yes, y_bin=y_bin, volume=m.volume)
                j = np.searchsorted(g.t.values, t + 300, side='right') - 1
                row['mid_d5'] = float(g.p.values[j])
                j = np.searchsorted(g.t.values, t + 900, side='right') - 1
                row['mid_d15'] = float(g.p.values[j])
                if trg is not None and len(trg):
                    tt = trg.t.values
                    a2 = np.searchsorted(tt, t + 60, side='right'); b2 = np.searchsorted(tt, t + 900, side='right')
                    w2 = trg.iloc[a2:b2]
                    by2 = w2[w2.dir == 1]; sy2 = w2[w2.dir == -1]
                    row['ask_slow'] = float(by2.px.iloc[0]) if len(by2) else np.nan
                    row['bid_slow'] = float(sy2.px.iloc[0]) if len(sy2) else np.nan
                    a24 = np.searchsorted(tt, t - 86400); a0 = np.searchsorted(tt, t)
                    row['usd_24h'] = float(trg.usd.values[a24:a0].sum())
                rows.append(row)
    pn = pd.DataFrame(rows)
    # features at t with horizon tau
    ft = F.build(pn.t.values, pn.W1.values - 60)
    for c in ['S_t', 'tau_min', 'seas', 'rv6h', 'rv24h', 'rv168h', 'dvol']:
        pn[c] = ft[c].values
    months = sorted(pd.to_datetime(pn.t, unit='s').dt.strftime('%Y-%m').unique())
    P = fit_models(tr, months, spec)
    pn['month'] = pd.to_datetime(pn.t, unit='s').dt.strftime('%Y-%m')
    hs = np.array(H_TOUCH)
    pn['h_fit'] = hs[np.argmin(np.abs(np.log(hs)[None, :] - np.log(pn.tau_h.values)[:, None]), axis=1)]
    pn['p_emp'] = np.nan; pn['p_refl'] = np.nan; pn['x'] = np.nan
    for (m, h), idx in pn.groupby(['month', 'h_fit']).groups.items():
        if (m, h) not in P:
            continue
        prm, z = P[(m, h)]
        sub = pn.loc[idx]
        s = scale(prm, sub)
        x = np.abs(np.log(sub.H.values / sub.S_t.values)) / s
        pn.loc[idx, 'x'] = x
        pn.loc[idx, 'p_emp'] = p_hit_emp(z, x)
        pn.loc[idx, 'p_refl'] = np.minimum(1, 2 * stats.t.sf(x, prm['nu']))
    # if barrier is on the wrong side already (should not happen as untouched) -> prob 1
    pn.to_parquet(out, compression='zstd')
    return pn


if __name__ == '__main__':
    pn = make_panel(rebuild='--rebuild' in sys.argv)
    print(len(pn), pn.series.value_counts().to_dict())
    print('resolution mismatch vs binance:', (pn.y != pn.y_bin).sum())
