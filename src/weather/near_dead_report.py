"""Scores and trading backtests for the intraday probabilistic model (near_dead_eval.parquet)."""
import sys
import numpy as np
import pandas as pd
from common import D
from backtest import simulate, summarize

B = pd.read_parquet(f"{D}/near_dead_eval.parquet")
B["date"] = pd.to_datetime(B.date)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300)


def bucket_logloss(p, y):
    p = np.clip(p, 0.003, 0.997)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def score_table(B):
    X = B[B.q_stack.notna() & B.q_mktcal.notna()]
    rows = []
    for dec, g in X.groupby("dec"):
        r = dict(dec=dec, events=g.event_id.nunique())
        for c in ["p_last", "q", "q_mktcal", "q_stack"]:
            r[f"LL_{c}"] = bucket_logloss(g[c].values, g.win.values).mean()
            r[f"BS_{c}"] = ((g[c] - g.win) ** 2).mean()
        rows.append(r)
    return pd.DataFrame(rows)


if __name__ == "__main__" and len(sys.argv) == 1:
    print("period", B.date.min().date(), B.date.max().date(), "events", B.event_id.nunique())
    print("== bucket-level log loss / Brier (walk-forward OOS rows with stack available)")
    print(score_table(B).round(4).to_string())


def sims(B, qcols=("q", "q_mktcal", "q_stack"), thrs=(0.01, 0.02, 0.03, 0.05, 0.08), stake=20.0):
    rows = []
    B = B[B.q_stack.notna()].copy()
    B["half"] = np.where(B.date < "2026-07-01", "A: Mar-Jun (tune)", "B: Jul-Sep (holdout)")
    specs = {"NO near-dead (NO px 0.80-0.99)": dict(sides=("no",), pmin=0.80, pmax=0.99),
             "NO any (NO px 0.02-0.98)": dict(sides=("no",), pmin=0.02, pmax=0.98),
             "YES any (px 0.02-0.98)": dict(sides=("yes",), pmin=0.02, pmax=0.98)}
    for sname, sp in specs.items():
        for qc in qcols:
            for thr in thrs:
                T = simulate(B, thr=thr, fill="prints", stake=stake, frac=0.5, qcol=qc, **sp)
                for half, t in T.groupby("half"):
                    s = summarize(t).to_dict()
                    s.update(spec=sname, q=qc, thr=thr, half=half)
                    rows.append(s)
    return pd.DataFrame(rows)


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "sims":
    R = sims(B)
    cols = ["spec", "q", "thr", "half", "n", "hit", "avg_px", "avg_edge", "staked", "pnl", "roi", "maxdd", "t_stat"]
    print(R[cols].round(4).to_string())
    R.to_csv(f"{D}/near_dead_sims.csv", index=False)
