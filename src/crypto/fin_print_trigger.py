"""Print-triggered executable backtest (finance barrier markets): every historical taker print reveals liquidity
at that price at that time. For each print we evaluate the walk-forward barrier model at the print time using only
hourly bars completed >= 1h before (no look-ahead) and 'take' the revealed side if edge > theta:
  YES-bid hit at px  -> NO purchasable at 1-px ; YES-ask lifted at px -> YES purchasable at px.
At most one trade per market per hour; size = min(print size, cap). Fee 0.04*p*(1-p)."""
import sys
import numpy as np, pandas as pd
from common import DATA, to_unix
from panel import load_shards, yes_equiv
from analyze_fin_barrier import load_under, train_extremes, p_hit_table, window_start, touched, NS, FAMILY, ALT_FAMILY
from fin_backtest import fee, summ, SPLIT


def run(theta=0.05, cap_usd=100, series_list=None):
    series_list = series_list or list(FAMILY) + ['fin-extra']
    unders, trains, ztab = {}, {}, {}
    rows = []
    for series in series_list:
        mk = pd.read_parquet(DATA / f'markets_{series}.parquet')
        mk = mk[mk.kind.isin(['touch_up', 'touch_down']) & mk.res_yes.notna()]
        tr = load_shards(series, 'tr')
        if not len(tr):
            continue
        tr = yes_equiv(tr)
        tg = {k: g.sort_values('t') for k, g in tr.groupby('cid')}
        for m in mk.itertuples():
            s = m.event_slug
            fam, proxies, fr = {**FAMILY, **ALT_FAMILY}.get(series, (None, None, 0.04))
            if fam is None:
                fam, proxies = (('gold', ['XAUUSDT']) if 'xauusd' in s else ('silver', ['XAGUSDT']) if 'xagusd' in s
                                else ('wti', ['CL']) if 'wti' in s else (None, None))
            if fam is None or m.condition_id not in tg:
                continue
            pxy = proxies[0]
            if pxy not in unders:
                unders[pxy] = load_under(pxy); trains[pxy] = train_extremes(unders[pxy])
            d = unders[pxy]; ts = d.ts.values
            W0 = int(window_start({'event_end': m.event_end, 'series': series, 'event_slug': s, 'm_created': m.m_created, 'm_start': m.m_start}).timestamp())
            W1 = int(m.event_end.timestamp())
            up = m.kind == 'touch_up'
            _, t_hit = touched(d, W0, W1, m.k1, up)
            g = tg[m.condition_id]
            g = g[(g.t > W0 + 1800) & (g.t < W1 - 900)]
            if t_hit is not None:
                g = g[g.t < t_hit]
            if not len(g):
                continue
            k = np.searchsorted(ts, g.t.values - 3600, side='right') - 1
            ok = k >= 60
            g = g[ok]; k = k[ok]
            if not len(g):
                continue
            S = d.c.values[k]; sig = d.sig.values[k]
            n_rem = np.searchsorted(ts, W1, side='left') - (k + 1)
            beyond = (S >= m.k1) if up else (S <= m.k1)
            keep = (n_rem > 0) & ~beyond
            g = g[keep]; S = S[keep]; sig = sig[keep]; n_rem = n_rem[keep]
            if not len(g):
                continue
            x = np.abs(np.log(m.k1 / S)) / (sig * np.sqrt(n_rem))
            n_fit = NS[np.argmin(np.abs(np.log(NS)[None, :] - np.log(n_rem)[:, None]), axis=1)]
            months = pd.to_datetime(g.t.values, unit='s').strftime('%Y-%m')
            p = np.full(len(g), np.nan)
            for i, (mo, nf) in enumerate(zip(months, n_fit)):
                key = (pxy, mo, nf)
                if key not in ztab:
                    ztab[key] = p_hit_table(trains[pxy], int(pd.Timestamp(mo + '-01', tz='UTC').timestamp()), nf)
                z = ztab[key]
                if z is not None:
                    p[i] = 1 - np.searchsorted(z, x[i], side='left') / len(z)
            g = g.assign(p=p, x=x)
            g = g[np.isfinite(g.p)]
            q_no = 1 - g.px.values
            e_no = (1 - g.p.values) - q_no - fee(q_no, fr)
            e_yes = g.p.values - g.px.values - fee(g.px.values, fr)
            take_no = (g.dir.values == -1) & (e_no > theta) & (q_no >= 0.03) & (q_no <= 0.97)
            take_yes = (g.dir.values == 1) & (e_yes > theta) & (g.px.values >= 0.03) & (g.px.values <= 0.97)
            sel = take_no | take_yes
            if not sel.any():
                continue
            c = g[sel].copy()
            c['side'] = np.where(take_no[sel], -1, 1)
            c['price'] = np.where(c.side == -1, 1 - c.px, c.px)
            c['edge'] = np.where(c.side == -1, e_no[sel], e_yes[sel])
            c['hour'] = c.t // 3600
            c = c.groupby('hour').head(1)
            for r in c.itertuples():
                win = m.res_yes if r.side == 1 else 1 - m.res_yes
                rows.append(dict(series=series, fam=fam, event_slug=s, cid=m.condition_id, t=r.t, side=r.side, price=r.price,
                                 p_model=r.p, edge=r.edge, x=r.x, size=r.size, usd=min(r.size * r.price, cap_usd), win=win, fee_rate=fr,
                                 h_left=(W1 - r.t) / 3600))
    t = pd.DataFrame(rows)
    t['fee'] = fee(t.price, t.fee_rate)
    t['pnl'] = t.win - t.price - t.fee
    t['roi'] = t.pnl / (t.price + t.fee)
    t['pnl_usd'] = t.usd * t.roi
    return t


if __name__ == '__main__':
    theta = float(sys.argv[1]) if len(sys.argv) > 1 else 0.05
    alt = '--alt' in sys.argv
    t = run(theta, series_list=list(ALT_FAMILY) if alt else None)
    now = pd.Timestamp('2026-09-26', tz='UTC').timestamp()
    t = t[~t.event_slug.str.contains('before-|hit-in-20\\d\\d$', regex=True)]
    t.to_parquet(DATA / f'fin_print_trigger_{"alt_" if alt else ""}{int(theta*100)}.parquet')
    t['per'] = np.where(t.series.str.contains('week'), 'weekly', 'monthly')
    t['half'] = np.where(t.t < SPLIT, 'H1', 'H2')
    def S(g):
        s = summ(g); s['usd_capped'] = g.usd.sum(); s['pnl_capped'] = g.pnl_usd.sum(); return pd.Series(s)
    cols = ['n', 'events', 'hit', 'avg_px', 'ROI%', 't_ev', 'trades/day', 'usd_capped', 'pnl_capped']
    print('theta', theta)
    print(S(t)[cols].round(3).to_dict())
    for by in (['half'], ['per'], ['side'], ['per', 'half'], ['fam', 'per']):
        print(t.groupby(by).apply(S, include_groups=False)[cols].round(3).to_string())
