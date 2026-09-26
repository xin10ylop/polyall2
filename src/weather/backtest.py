"""Scoring (model vs market) and trading-rule backtests on the long (event, decision, bucket) table."""
import numpy as np
import pandas as pd
from common import taker_fee_per_share

HALF_SPREAD = {"D-1 12h": 0.01, "D0 07h": 0.015, **{f"D0 {h:02d}h": 0.02 for h in range(10, 20)}}


def market_probs(B, max_age_h=12.0, floor=0.002):
    B = B.copy()
    p = B.last_px.where(B.last_age_h <= max_age_h)
    B["p_raw"] = p
    p = p.fillna(floor).clip(lower=floor)
    B["p_mkt"] = p / p.groupby([B.event_id, B.dec]).transform("sum")
    return B


def scores(B, qcol="q", pcol="p_mkt"):
    g = B.groupby(["event_id", "dec"])
    w = B[B.win == 1].set_index(["event_id", "dec"])
    ll_m = -np.log(np.clip(w[qcol], 0.002, 1)); ll_k = -np.log(np.clip(w[pcol], 0.002, 1))
    br_m = g.apply(lambda x: ((x[qcol] - x.win) ** 2).sum()); br_k = g.apply(lambda x: ((x[pcol] - x.win) ** 2).sum())
    return pd.DataFrame({"ll_model": ll_m, "ll_mkt": ll_k, "brier_model": br_m, "brier_mkt": br_k})


def simulate(B, thr=0.05, fill="prints", stake=20.0, frac=0.5, extra_slip=0.0, pmin=0.02, pmax=0.98,
             max_age_h=3.0, sides=("yes", "no"), fee_rate=0.05, qcol="q", once=True):
    """Return one row per executed trade.
    Signal (uses only info <= tau): est ask = last_px + half-spread(dec); est bid = last_px - half-spread.
      YES if q - ask_est - fee(ask_est) > thr ; NO if (1-q) - (1-bid_est) - fee(1-bid_est) > thr.
    Fill:
      'prints': taker prints in [tau, tau+30m]: YES fills at lift VWAP (+extra_slip) if that still clears thr,
                size <= frac * lifted shares; NO fills at 1 - hit VWAP likewise.
      'quote' : fill at ask_est/bid_est (+extra_slip), unlimited size.
    """
    X = B[B.last_px.notna() & (B.last_age_h <= max_age_h) & B[qcol].notna()].copy()
    X["q"] = X[qcol]
    hs = X.dec.map(HALF_SPREAD)
    X["ask_est"] = (X.last_px + hs).clip(upper=0.999)
    X["bid_est"] = (X.last_px - hs).clip(lower=0.001)
    fr = np.where(X.fees.fillna(False), fee_rate, 0.0)
    trades = []
    if "yes" in sides:
        e = X.q - X.ask_est - fr * X.ask_est * (1 - X.ask_est)
        s = X[(e > thr) & (X.ask_est >= pmin) & (X.ask_est <= pmax)].copy()
        s["side"] = "YES"; s["frate"] = np.where(s.fees.fillna(False), fee_rate, 0.0)
        if fill == "prints":
            s["px"] = s.ask_vwap + extra_slip
            s["cap_sh"] = frac * s.ask_sh
        else:
            s["px"] = s.ask_est + extra_slip; s["cap_sh"] = np.inf
        s["q_side"] = s.q; s["payoff"] = s.win
        trades.append(s)
    if "no" in sides:
        pno = 1 - X.bid_est
        e = (1 - X.q) - pno - fr * pno * (1 - pno)
        s = X[(e > thr) & (pno >= pmin) & (pno <= pmax)].copy()
        s["side"] = "NO"; s["frate"] = np.where(s.fees.fillna(False), fee_rate, 0.0)
        if fill == "prints":
            s["px"] = 1 - s.bid_vwap + extra_slip
            s["cap_sh"] = frac * s.bid_sh
        else:
            s["px"] = 1 - s.bid_est + extra_slip; s["cap_sh"] = np.inf
        s["q_side"] = 1 - s.q; s["payoff"] = 1 - s.win
        trades.append(s)
    T = pd.concat(trades, ignore_index=True)
    T = T[T.px.notna() & (T.px > 0) & (T.px < 1)]
    T["fee_sh"] = T.frate * T.px * (1 - T.px)
    T = T[T.q_side - T.px - T.fee_sh > thr * 0.5]  # re-check at the actual fill price (limit order)
    T["shares"] = np.minimum(stake / T.px, T.cap_sh)
    T["cost"] = T.shares * (T.px + T.fee_sh)
    T["pnl"] = T.shares * (T.payoff - T.px - T.fee_sh)
    T["edge_fill"] = T.q_side - T.px - T.fee_sh
    if once:  # first trigger per (event, bucket, side) only
        T = T.sort_values("dec_order" if "dec_order" in T else "dec").drop_duplicates(["event_id", "mi", "side"], keep="first")
    return T


def summarize(T, by=None):
    def f(t):
        t = t.sort_values("tau") if "tau" in t else t
        cum = t.pnl.cumsum()
        dd = (cum.cummax() - cum).max() if len(t) else 0
        return pd.Series(dict(n=len(t), hit=(t.payoff == 1).mean(), avg_px=t.px.mean(), avg_edge=t.edge_fill.mean(),
                              staked=t.cost.sum(), pnl=t.pnl.sum(), roi=t.pnl.sum() / t.cost.sum() if t.cost.sum() else np.nan,
                              pnl_per_trade=t.pnl.mean(), maxdd=dd,
                              t_stat=(t.pnl.mean() / t.pnl.std() * np.sqrt(len(t))) if len(t) > 2 and t.pnl.std() > 0 else np.nan))
    if by is None:
        return f(T)
    return T.groupby(by).apply(f)
