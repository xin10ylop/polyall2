"""Compare Vagabund97's actual fills in finance/commodity barrier markets with the walk-forward barrier model
evaluated at each fill time (same machinery as analyze_fin_barrier; no look-ahead)."""
import json, re
import numpy as np, pandas as pd
from common import DATA
from analyze_fin_barrier import load_under, train_extremes, p_hit_table, window_start, NS, FAMILY
from fin_backtest import fee


def fam_of(slug):
    if re.search('xauusd|gold-hit', slug): return 'gold', 'XAUUSDT'
    if re.search('xagusd|silver-hit', slug): return 'silver', 'XAGUSDT'
    if re.search('wti', slug): return 'wti', 'CL'
    if re.search('(-ng-|natural-gas)', slug): return 'ng', 'NG'
    if re.search('spy', slug): return 'spy', 'SPY'
    if re.search('nvda|nvidia', slug): return 'nvda', 'NVDA'
    return None, None


def main():
    f = pd.read_parquet(DATA / 'vaga' / 'fills_fin.parquet')
    vm = pd.read_parquet(DATA / 'vaga' / 'markets.parquet').drop_duplicates('condition_id').set_index('condition_id')
    f = f[f.fam.isin(['gold-w', 'gold-m', 'silver-w', 'silver-m', 'wti-w', 'wti-m', 'spy'])].copy()
    unders, trains = {}, {}
    rows = []
    for r in f.itertuples():
        fam, pxy = fam_of(r.event_slug)
        if fam is None or r.condition_id not in vm.index:
            continue
        m = vm.loc[r.condition_id]
        git = (m.git or '')
        up = git.startswith('↑') or '(HIGH)' in m.question or 'reach' in m.question.lower()
        try:
            H = float(re.sub(r'[^\d\.]', '', git.split('$')[-1]) if '$' in git else re.sub(r'[^\d\.]', '', git))
        except ValueError:
            continue
        if pxy not in unders:
            unders[pxy] = load_under(pxy); trains[pxy] = train_extremes(unders[pxy])
        d = unders[pxy]
        W1 = int(pd.Timestamp(m.end).timestamp())
        t = int(r.timestamp)
        k = np.searchsorted(d.ts.values, t - 3600, side='right') - 1
        if k < 60 or t >= W1:
            continue
        S = d.c.values[k]; sig = d.sig.values[k]
        n_rem = int(((d.ts.values > d.ts.values[k]) & (d.ts.values < W1)).sum())
        if n_rem <= 0:
            continue
        beyond = (up and S >= H) or ((not up) and S <= H)
        x = abs(np.log(H / S)) / (sig * np.sqrt(n_rem))
        n_fit = NS[np.argmin(np.abs(np.log(NS) - np.log(n_rem)))]
        cut = int(pd.Timestamp(pd.Timestamp(t, unit='s').strftime('%Y-%m') + '-01', tz='UTC').timestamp())
        z = p_hit_table(trains[pxy], cut, n_fit)
        if z is None:
            continue
        p = 1.0 if beyond else 1 - np.searchsorted(z, x, side='left') / len(z)
        yes_tok = r.outcome.lower() == 'yes'
        p_tok = p if yes_tok else 1 - p     # model prob of the token traded
        sgn = 1 if r.side == 'BUY' else -1
        edge = sgn * (p_tok - r.price) - fee(r.price, 0.04) * (1 if r.taker else 0)
        rows.append(dict(fam=r.fam, event_slug=r.event_slug, t=t, side=r.side, outcome=r.outcome, price=r.price, size=r['size'] if False else r.size,
                         usd=r.usd, pnl=r.pnl, res=r.res, taker=r.taker, p_model_tok=p_tok, edge=edge, x=x, h_left=(W1 - t) / 3600, beyond=beyond))
    out = pd.DataFrame(rows)
    out.to_parquet(DATA / 'vaga' / 'fills_fin_model.parquet')
    return out


if __name__ == '__main__':
    o = main()
    o = o[o.res.notna()]
    print(len(o), 'fills with model value; usd', round(o.usd.sum()), 'pnl', round(o.pnl.sum()))
    o['eb'] = pd.cut(o.edge, [-1, -0.1, -0.03, 0.03, 0.1, 0.2, 1])
    print(o.groupby('eb', observed=True).agg(n=('usd', 'size'), usd=('usd', 'sum'), pnl=('pnl', 'sum'), avg_px=('price', 'mean'), p_model=('p_model_tok', 'mean'))
          .assign(roi=lambda x: x.pnl / x.usd).round(3).to_string())
    print(o.groupby('fam').agg(n=('usd', 'size'), usd=('usd', 'sum'), pnl=('pnl', 'sum'), edge_mean=('edge', 'mean'), agree_share=('edge', lambda e: (e > 0).mean()))
          .assign(roi=lambda x: x.pnl / x.usd).round(3).to_string())
    print('corr(edge, per-$ pnl):', round(np.corrcoef(o.edge, o.pnl / o.usd)[0, 1], 3))
