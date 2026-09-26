"""Pre-registered strategy evaluation (no parameter search): given panel, spec, theta, all horizons pooled."""
import sys
import numpy as np, pandas as pd
from evaluate import backtest, summarize

SPLIT = pd.Timestamp('2026-03-01', tz='UTC').timestamp()


def prereg(panel, spec='p_combo', theta=0.03, hs=None, pmin=0.05, pmax=0.95, modes=('mid0', 'mid5', 'trade_slow')):
    pn = panel[panel.stale <= 1800]
    if hs is not None:
        pn = pn[pn.h.isin(hs)]
    rows = []
    for mode in modes:
        if mode == 'trade_slow' and 'ask_slow' not in pn:
            continue
        tr = backtest(pn, spec, theta, mode, pmin=pmin, pmax=pmax)
        for per, sub in (('all', tr), ('train<2026-03', tr[tr.t < SPLIT]), ('test>=2026-03', tr[tr.t >= SPLIT])):
            s = summarize(sub)
            s.update(fill=mode, period=per)
            rows.append(s)
        if mode == 'mid0':
            byh = tr[tr.t >= SPLIT].groupby('h').apply(lambda g: pd.Series(summarize(g)), include_groups=False)
    cols = ['fill', 'period', 'n', 'n_events', 'hit', 'avg_price', 'avg_fee', 'roi', 't_clustered', 'pnl_10', 'pnl_50', 'pnl_200', 'maxdd_50', 'trades_per_day']
    return pd.DataFrame(rows)[cols], byh[['n', 'hit', 'avg_price', 'roi', 't_clustered', 'pnl_50']]


if __name__ == '__main__':
    pn = pd.read_parquet(sys.argv[1])
    spec = sys.argv[2] if len(sys.argv) > 2 else 'p_combo'
    a, b = prereg(pn, spec)
    print(a.round(3).to_markdown(index=False)); print(); print(b.round(3).to_markdown())
