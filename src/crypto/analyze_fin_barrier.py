"""Finance / commodity barrier markets ("Will Gold (XAUUSD) hit (HIGH) $X Week of ...", monthly variants,
Silver XAGUSD, WTI, Natural Gas, SPY, NVDA). Resolution: Pyth 1-minute candles during trading sessions
(futures: Sun 18:00 ET - Fri 17:00 ET with daily 17-18 ET break; equities/ETF: RTH only), after market creation.

Underlying proxies (hourly OHLC): Yahoo GC=F/SI=F/CL=F/NG=F/SPY/NVDA; Binance USD-M perps XAUUSDT/XAGUSDT
(spot-gold/silver proxies, restricted to Pyth session hours). Resolution agreement per proxy = basis-risk measure.

Model (walk-forward, no look-ahead): hourly-bar EWMA vol sigma (half-life 60 bars) at the last completed bar;
remaining bars n in the window (deterministic session schedule); x = |ln(H/S)|/(sigma*sqrt(n));
P(hit) = empirical survival of the standardised running extreme over n bars, pooled up/down, estimated on
bars whose horizon ended before the first day of the decision month (expanding window).
Decision times: 16:00 UTC (noon ET) on each weekday while the strike is live and untouched.
"""
import sys, glob
import numpy as np, pandas as pd
from common import DATA, to_unix, taker_fee_per_share
from panel import load_shards, yes_equiv

FIN = DATA / 'fin'
FAMILY = {  # series -> (family label, candidate proxies in order of preference, fee rate)
    'gold-hit-price-weekly': ('gold', ['XAUUSDT', 'GC'], 0.04), 'xauusd-hit-month': ('gold', ['XAUUSDT', 'GC'], 0.04),
    'silver-hit-price-weekly': ('silver', ['XAGUSDT', 'SI'], 0.04), 'xagusd-hit-month': ('silver', ['XAGUSDT', 'SI'], 0.04),
    'wti-crude-oil-hit-price-weekly': ('wti', ['CL'], 0.04), 'natural-gas-hit-price-weekly': ('ng', ['NG'], 0.04),
    'ng-hit-month': ('ng', ['NG'], 0.04), 'spy-hit-price-weekly': ('spy', ['SPY'], 0.04), 'spy-hit-month': ('spy', ['SPY'], 0.04),
    'nvidia-hit-price-weekly': ('nvda', ['NVDA'], 0.04), 'nvidia-hit-price-monthly': ('nvda', ['NVDA'], 0.04),
}
ALT_FAMILY = {  # Binance-resolved alt monthly barriers (crypto fee rate 0.07); hourly bars aggregated from Binance 1m
    'hyperliquid-hit-price-monthly': ('hype', ['HYPEUSDT'], 0.07), 'dogecoin-hit-price-monthly': ('doge', ['DOGEUSDT'], 0.07),
    'bnb-hit-price-monthly': ('bnb', ['BNBUSDT'], 0.07), 'solana-hit-price-monthly': ('sol', ['SOLUSDT'], 0.07),
    'xrp-hit-price-monthly': ('xrp', ['XRPUSDT'], 0.07),
}
NS = np.array([2, 4, 7, 12, 16, 23, 35, 46, 69, 92, 115, 160, 230, 350, 460])


def session_mask(ts, kind):
    """True for hourly bars inside Pyth sessions. kind 'fut' (Sun 18:00 ET - Fri 17:00 ET, break 17-18 ET)."""
    et = pd.to_datetime(ts, unit='s', utc=True).tz_convert('America/New_York')
    wd, hr = et.dayofweek, et.hour
    if kind == 'fut':
        ok = ~((wd == 5) | ((wd == 4) & (hr >= 17)) | ((wd == 6) & (hr < 18)) | (hr == 17))
        return np.asarray(ok)
    return np.ones(len(ts), bool)


def load_under(name):
    d = pd.read_parquet(FIN / f'{name}_1h.parquet').sort_values('ts')
    if name in ('XAUUSDT', 'XAGUSDT'):
        d = d[session_mask(d.ts.values, 'fut')]
    d = d.dropna().reset_index(drop=True)
    d['r'] = np.log(d.c / d.c.shift(1))
    v = (d.r ** 2).ewm(halflife=60, min_periods=30).mean()
    d['sig'] = np.sqrt(v)   # per-bar vol known at bar close
    return d


def window_start(row):
    W1 = row['event_end']
    if row['series'].endswith('weekly') or 'week-of' in row['event_slug']:
        W0 = (W1.tz_convert('America/New_York').normalize() - pd.Timedelta(days=5)).replace(hour=18)  # Sunday 18:00 ET
    else:
        e = W1.tz_convert('America/New_York') - pd.Timedelta(hours=1)
        W0 = e.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    W0 = W0.tz_convert('UTC')
    c = row['m_created'] if pd.notna(row['m_created']) else row['m_start']
    return max(W0, c)


def touched(d, W0, W1, H, up):
    seg = d[(d.ts >= W0 // 3600 * 3600) & (d.ts < W1)]
    if not len(seg):
        return np.nan, None
    idx = np.where(seg.h.values >= H)[0] if up else np.where(seg.l.values <= H)[0]
    return (1.0 if len(idx) else 0.0), (int(seg.ts.values[idx[0]]) if len(idx) else None)


def train_extremes(d):
    """For every bar i and horizon n in NS: standardised running extreme z = max(ln(h/c_i), -ln(l/c_i))/(sig_i*sqrt(n))."""
    h = np.log(d.h.values); l = np.log(d.l.values); c = np.log(d.c.values); s = d.sig.values
    out = []
    for n in NS:
        fmax = pd.Series(h[::-1]).rolling(n, min_periods=n).max().values[::-1]
        fmin = pd.Series(l[::-1]).rolling(n, min_periods=n).min().values[::-1]
        up = np.full(len(c), np.nan); dn = np.full(len(c), np.nan)
        up[:-1] = fmax[1:] - c[:-1]; dn[:-1] = c[:-1] - fmin[1:]
        endts = np.full(len(c), np.nan)
        endts[:len(c) - n] = d.ts.values[n:] + 3600
        sc = s * np.sqrt(n)
        out.append(pd.DataFrame({'ts_end_h': endts, 'n': n, 'zu': up / sc, 'zd': dn / sc}))
    t = pd.concat(out, ignore_index=True).dropna()
    return t


def p_hit_table(tr, cut, n):
    sub = tr[(tr.n == n) & (tr.ts_end_h <= cut)]
    if len(sub) < 500:
        return None
    return np.sort(np.concatenate([sub.zu.values, sub.zd.values]))


def build(series_list=None, rebuild=False):
    out = DATA / 'panel_fin_barrier.parquet'
    if out.exists() and not rebuild:
        return pd.read_parquet(out)
    series_list = series_list or list(FAMILY) + ['fin-extra']
    unders = {n: load_under(n) for n in ['XAUUSDT', 'GC', 'XAGUSDT', 'SI', 'CL', 'NG', 'SPY', 'NVDA']}
    trains = {n: train_extremes(d) for n, d in unders.items()}
    rows, rescheck = [], []
    for series in series_list:
        p = DATA / f'markets_{series}.parquet'
        ph = load_shards(series, 'ph')
        if not p.exists() or not len(ph):
            continue
        mk = pd.read_parquet(p)
        mk = mk[mk.kind.isin(['touch_up', 'touch_down']) & mk.res_yes.notna() & mk.condition_id.isin(ph.cid.unique())].copy()
        if series == 'fin-extra':
            mk = mk[~mk.event_slug.str.contains('wti-hit-in-(april|may)', regex=True)] if False else mk
        tr = load_shards(series, 'tr')
        tr = yes_equiv(tr) if len(tr) else tr
        tr_g = {k: g.sort_values('t') for k, g in tr.groupby('cid')} if len(tr) else {}
        ph_g = {k: g.sort_values('t') for k, g in ph.groupby('cid')}
        for m in mk.itertuples():
            s = m.event_slug
            fam, proxies, fr = FAMILY.get(series, (None, None, 0.04))
            if fam is None:   # fin-extra
                fam, proxies = (('gold', ['XAUUSDT', 'GC']) if 'xauusd' in s else ('silver', ['XAGUSDT', 'SI']) if 'xagusd' in s
                                else ('wti', ['CL']) if 'wti' in s else (None, None))
                fr = 0.04
            if fam is None:
                continue
            row0 = {'event_end': m.event_end, 'series': series, 'event_slug': s, 'm_created': m.m_created, 'm_start': m.m_start}
            W0 = int(window_start(row0).timestamp()); W1 = int(m.event_end.timestamp())
            up = m.kind == 'touch_up'
            chk = {}
            for pxy in proxies:
                y_p, t_hit = touched(unders[pxy], W0, W1, m.k1, up)
                chk[pxy] = (y_p, t_hit)
                rescheck.append(dict(fam=fam, proxy=pxy, series=series, cid=m.condition_id, y=m.res_yes, y_proxy=y_p, H=m.k1, up=up))
            pxy = proxies[0]
            d = unders[pxy]
            t_hit = chk[pxy][1]
            g = ph_g[m.condition_id]; trg = tr_g.get(m.condition_id)
            closed_ts = int(m.closed_time.timestamp()) if pd.notna(m.closed_time) else W1
            day0 = (W0 // 86400) * 86400 + 16 * 3600
            for t in range(day0, W1 - 3600, 86400):
                if t <= W0 + 3600 or t >= min(W1, closed_ts) - 1800:
                    continue
                if pd.Timestamp(t, unit='s').dayofweek >= 5:
                    continue
                if t_hit is not None and t_hit + 3600 <= t:
                    continue
                i = np.searchsorted(g.t.values, t, side='right') - 1
                if i < 0 or t - g.t.values[i] > 3600:
                    continue
                k = np.searchsorted(d.ts.values, t - 3600, side='right') - 1   # last completed bar
                if k < 60:
                    continue
                S = d.c.values[k]; sig = d.sig.values[k]
                n_rem = int(((d.ts.values > d.ts.values[k]) & (d.ts.values < W1)).sum())
                if n_rem <= 0:
                    continue
                if (up and S >= m.k1) or ((not up) and S <= m.k1):
                    continue
                row = dict(fam=fam, series=series, proxy=pxy, event_slug=s, cid=m.condition_id, kind=m.kind, H=m.k1, W0=W0, W1=W1,
                           t=t, tau_h=(W1 - t) / 3600, n_rem=n_rem, S=S, sig=sig, x=abs(np.log(m.k1 / S)) / (sig * np.sqrt(n_rem)),
                           mid=float(g.p.values[i]), y=m.res_yes, y_proxy=chk[pxy][0], fee_rate=fr, volume=m.volume)
                if trg is not None and len(trg):
                    tt = trg.t.values
                    a2 = np.searchsorted(tt, t + 60, side='right'); b2 = np.searchsorted(tt, t + 900, side='right')
                    w2 = trg.iloc[a2:b2]
                    by = w2[w2.dir == 1]; sy = w2[w2.dir == -1]
                    row['ask_slow'] = float(by.px.iloc[0]) if len(by) else np.nan
                    row['bid_slow'] = float(sy.px.iloc[0]) if len(sy) else np.nan
                    a24 = np.searchsorted(tt, t - 86400); a0 = np.searchsorted(tt, t)
                    row['usd_24h'] = float(trg.usd.values[a24:a0].sum())
                rows.append(row)
    pn = pd.DataFrame(rows)
    rc = pd.DataFrame(rescheck)
    rc.to_parquet(DATA / 'fin_rescheck.parquet')
    # walk-forward empirical hit probability
    pn['month'] = pd.to_datetime(pn.t, unit='s').dt.strftime('%Y-%m')
    pn['n_fit'] = NS[np.argmin(np.abs(np.log(NS)[None, :] - np.log(pn.n_rem.values)[:, None]), axis=1)]
    pn['p_model'] = np.nan
    for (pxy, mth, n), idx in pn.groupby(['proxy', 'month', 'n_fit']).groups.items():
        cut = int(pd.Timestamp(mth + '-01', tz='UTC').timestamp())
        z = p_hit_table(trains[pxy], cut, n)
        if z is None:
            continue
        x = pn.loc[idx, 'x'].values
        pn.loc[idx, 'p_model'] = 1 - np.searchsorted(z, x, side='left') / len(z)
    pn.to_parquet(out, compression='zstd')
    return pn


if __name__ == '__main__':
    pn = build(rebuild=True)
    print(len(pn), pn.groupby(['fam', 'series']).size().to_string())
    rc = pd.read_parquet(DATA / 'fin_rescheck.parquet')
    print(rc.groupby(['fam', 'proxy']).apply(lambda g: pd.Series({'n': len(g), 'agree': (g.y == g.y_proxy).mean(),
          'proxy_yes_actual_no': ((g.y_proxy == 1) & (g.y == 0)).sum(), 'proxy_no_actual_yes': ((g.y_proxy == 0) & (g.y == 1)).sum()}), include_groups=False))
