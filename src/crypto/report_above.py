"""Produce markdown tables for the family (a)/(c) write-up from a panel file.
Walk-forward design: model already OOS (monthly expanding refits). Strategy hyper-parameters (h, theta, spec)
selected on TRAIN window (< 2026-03-01, pre-fee era), evaluated on TEST window (>= 2026-03-01)."""
import sys
import numpy as np, pandas as pd
from evaluate import (calibration, score_table, blend_regression, backtest, summarize, logloss, brier)

SPLIT = pd.Timestamp('2026-03-01', tz='UTC').timestamp()
PMIN, PMAX = 0.05, 0.95   # model strategy trades only tokens priced 5c-95c (tails analysed separately)


def md(df, floatfmt=3):
    return df.round(floatfmt).to_markdown()


def run(panel_path, label, specs=('p_combo', 'p_dvol', 'p_rv'), thetas=(0.0, 0.02, 0.03, 0.05, 0.08),
        hs=(120, 72, 48, 24, 12, 6, 3, 1, 0.5), out=sys.stdout):
    pn = pd.read_parquet(panel_path)
    pn = pn[pn.stale <= 1800].copy()
    specs = [s for s in specs if s in pn.columns]
    P = lambda *a: print(*a, file=out)
    P(f'\n#### {label}: sample')
    P(f'- rows (market × decision time): {len(pn):,}; markets {pn.cid.nunique():,}; events {pn.event_slug.nunique()}; '
      f'decision times {pd.to_datetime(pn.t.min(), unit="s"):%Y-%m-%d} → {pd.to_datetime(pn.t.max(), unit="s"):%Y-%m-%d}')
    if 'usd_24h' in pn:
        v = pn[pn.h == 24].usd_24h.sum() / max(pn[pn.h == 24].event_slug.nunique(), 1)
        P(f'- taker notional traded in the 24h before T−24h, per event (all strikes): ${v:,.0f}')
    # 1. scores
    st = score_table(pn.dropna(subset=[specs[0]]), ['mid'] + specs)
    P('\n**Out-of-sample log-loss (LL) and Brier (BS): market mid vs model** (lower is better)\n')
    P(st.set_index('h').round(4).to_markdown())
    # 2. calibration of market
    pn['hg'] = pd.cut(pn.h, [0, 1.5, 13, 50, 200], labels=['0.5–1h', '3–12h', '24–48h', '72–120h'])
    P('\n**Market calibration (YES mid bins → realised YES frequency), by horizon group**\n')
    tabs = []
    for g, d in pn.groupby('hg', observed=True):
        c = calibration(d, 'mid', extra_cols=[specs[0]])
        c.index = [f'{g} {i}' for i in c.index.astype(str)]
        tabs.append(c)
    P(pd.concat(tabs)[['n', 'mean_p', 'freq_y', f'mean_{specs[0]}', 'z']].round(4).to_markdown())
    # 3. blend regression
    P('\n**Logistic blend y ~ logit(mid) + logit(model), rows with 0.02<mid<0.98** (coef, z)\n')
    rows = []
    for h in hs:
        d = pn[(pn.h == h) & (pn.mid > 0.02) & (pn.mid < 0.98)].dropna(subset=[specs[0]])
        if len(d) < 50:
            continue
        b = blend_regression(d, ['mid', specs[0]])
        rows.append({'h': h, 'n': len(d), 'b_mid': b.loc['mid', 'coef'], 'z_mid': b.loc['mid', 'z'],
                     'b_model': b.loc[specs[0], 'coef'], 'z_model': b.loc[specs[0], 'z']})
    P(pd.DataFrame(rows).set_index('h').round(3).to_markdown())
    # 4. backtests: grid on TRAIN, chosen config on TEST
    grid = []
    for h in hs:
        for sp in specs:
            for th in thetas:
                for mode in ('mid0', 'mid5', 'trade_slow'):
                    d = pn[pn.h == h]
                    tr = backtest(d, sp, th, mode, pmin=PMIN, pmax=PMAX)
                    for per, sub in (('train', tr[tr.t < SPLIT]), ('test', tr[tr.t >= SPLIT])):
                        s = summarize(sub)
                        s.update(h=h, spec=sp, theta=th, mode=mode, period=per)
                        grid.append(s)
    G = pd.DataFrame(grid)
    return pn, G


def pick_and_report(G, out=sys.stdout, min_train_n=30):
    P = lambda *a: print(*a, file=out)
    cols = ['n', 'hit', 'avg_price', 'roi', 't_clustered', 'pnl_10', 'pnl_50', 'pnl_200', 'maxdd_50', 'trades_per_day']
    tr = G[(G.period == 'train') & (G['mode'] == 'mid0') & (G.n >= min_train_n)].copy()
    tr = tr.sort_values('roi', ascending=False)
    P(f'\nBacktest universe: token prices in [{PMIN}, {PMAX}]; fee = 0.07·p·(1−p) per share; fills: mid0 = mid + cost(h,p) at t; '
      'mid5 = signal at t, execute at mid(t+5min)+cost; trade_slow = first real taker fill in (t+60s,t+15m] (fallback mid0; skip if > signal price+1c).')
    P('\n**Top-5 configurations on TRAIN (<2026-03-01, mid+cost fills)** and the same configs on TEST (≥2026-03-01):\n')
    rows = []
    for _, r in tr.head(5).iterrows():
        for per in ('train', 'test'):
            for mode in ('mid0', 'mid5', 'trade_slow'):
                x = G[(G.h == r.h) & (G.spec == r.spec) & (G.theta == r.theta) & (G['mode'] == mode) & (G.period == per)]
                if len(x):
                    x = x.iloc[0]
                    rows.append({'h': r.h, 'spec': r.spec, 'theta': r.theta, 'period': per, 'fill': mode,
                                 **{c: x.get(c) for c in cols}})
    T = pd.DataFrame(rows)
    P(T.round(3).to_markdown(index=False))
    # all-config test summary: distribution of test ROI across all configs
    te = G[(G.period == 'test') & (G['mode'] == 'mid0') & (G.n >= 20)]
    P(f'\nAcross all {len(te)} (h, spec, θ) configs with ≥20 TEST trades (mid+cost fills): median TEST ROI '
      f'{te.roi.median()*100:.2f}%, share with ROI>0: {(te.roi>0).mean()*100:.0f}%, share with clustered t>2: {(te.t_clustered>2).mean()*100:.0f}%.')
    return T


if __name__ == '__main__':
    path, label = sys.argv[1], sys.argv[2]
    pn, G = run(path, label)
    G.to_parquet(path.replace('.parquet', '_grid.parquet'))
    pick_and_report(G)
