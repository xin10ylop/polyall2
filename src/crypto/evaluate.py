"""Generic evaluation: market calibration, model-vs-market scoring, walk-forward trading backtests.
Panel columns required: cid, event_slug, h, t, T, y (1/0), mid, and model prob columns (p_*).
Optional trade-fill columns: ask_tr, bid_tr, ask_sz, bid_sz (YES-equivalent, from fills in [t, t+10min])."""
import numpy as np, pandas as pd
from scipy import stats
from common import taker_fee_per_share

EPS = 1e-4
CAL_BINS = [0, 0.02, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98, 1.0]


def logloss(p, y):
    p = np.clip(p, EPS, 1 - EPS)
    return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))


def brier(p, y):
    return np.mean((p - y) ** 2)


def calibration(df, pcol='mid', bins=CAL_BINS, extra_cols=()):
    d = df.copy()
    d['bin'] = pd.cut(d[pcol], bins, include_lowest=True)
    agg = {'n': ('y', 'size'), 'mean_p': (pcol, 'mean'), 'freq_y': ('y', 'mean')}
    for c in extra_cols:
        agg['mean_' + c] = (c, 'mean')
    g = d.groupby('bin', observed=True).agg(**agg)
    g['se'] = np.sqrt(g.freq_y * (1 - g.freq_y) / g.n.clip(lower=1))
    g['z'] = (g.freq_y - g.mean_p) / np.sqrt(g.mean_p * (1 - g.mean_p) / g.n.clip(lower=1))
    return g


def logit(p):
    p = np.clip(p, 0.001, 0.999)
    return np.log(p / (1 - p))


def blend_regression(df, cols):
    """Logistic regression y ~ a + sum b_i logit(col_i); returns coefs and std errors (cluster-naive)."""
    import numpy.linalg as la
    X = np.column_stack([np.ones(len(df))] + [logit(df[c].values) for c in cols])
    y = df.y.values
    b = np.zeros(X.shape[1])
    for _ in range(50):
        p = 1 / (1 + np.exp(-X @ b))
        W = p * (1 - p)
        H = X.T @ (X * W[:, None]) + 1e-9 * np.eye(len(b))
        g = X.T @ (y - p)
        step = la.solve(H, g)
        b += step
        if np.max(np.abs(step)) < 1e-8:
            break
    se = np.sqrt(np.diag(la.inv(H)))
    return pd.DataFrame({'coef': b, 'se': se, 'z': b / se}, index=['const'] + list(cols))


def score_table(df, pcols):
    rows = []
    for h, g in df.groupby('h'):
        r = {'h': h, 'n': len(g), 'n_events': g.event_slug.nunique()}
        for c in pcols:
            gg = g.dropna(subset=[c])
            r[f'LL_{c}'] = logloss(gg[c].values, gg.y.values)
            r[f'BS_{c}'] = brier(gg[c].values, gg.y.values)
        rows.append(r)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ fills & backtest
def fill_prices(df, mode, slip=0.01, hs_min=0.005):
    """Returns (yes_ask, no_ask) executable prices under fill model.
    mode 'mid': mid + max(half-spread est, hs_min) + slip  (half-spread from trade analysis ~0.5-0.9c)
    mode 'trade': VWAP of actual YES-equivalent taker buys (for YES) / sells (for NO) in [t, t+10min]; NaN if none."""
    if mode == 'mid':
        mid = df.mid.values
        hs = np.where((mid < 0.03) | (mid > 0.97), 0.001, np.where((mid < 0.1) | (mid > 0.9), 0.005, 0.0085))
        hs = np.maximum(hs, np.where((mid < 0.03) | (mid > 0.97), 0.001, hs_min))
        yes_ask = np.minimum(mid + hs + slip, 0.999)
        no_ask = np.minimum(1 - mid + hs + slip, 0.999)
        return yes_ask, no_ask
    elif mode == 'trade':
        yes_ask = df.ask_tr.values
        no_ask = 1 - df.bid_tr.values
        return yes_ask, no_ask
    raise ValueError(mode)


def signals(df, pcol, theta, mode, slip=0.01, pmin=0.0, pmax=1.0):
    """Take-side decision: buy YES if p - yes_ask - fee > theta; buy NO if (1-p) - no_ask - fee > theta.
    Only prices in [pmin, pmax] (price of the token bought) are traded. Returns trade DataFrame."""
    ya, na = fill_prices(df, mode, slip)
    p = df[pcol].values
    fy = taker_fee_per_share(ya); fn = taker_fee_per_share(na)
    ey = p - ya - fy
    en = (1 - p) - na - fn
    buy_y = (ey > theta) & (ey >= en) & (ya >= pmin) & (ya <= pmax)
    buy_n = (en > theta) & (en > ey) & (na >= pmin) & (na <= pmax)
    tr = df.loc[buy_y | buy_n, ['cid', 'event_slug', 'h', 't', 'T', 'y', 'mid', pcol]].copy()
    side = np.where(buy_y, 1, -1)[buy_y | buy_n]
    price = np.where(buy_y, ya, na)[buy_y | buy_n]
    fee = np.where(buy_y, fy, fn)[buy_y | buy_n]
    edge = np.where(buy_y, ey, en)[buy_y | buy_n]
    tr['side'] = side; tr['price'] = price; tr['fee'] = fee; tr['edge_est'] = edge
    win = np.where(side == 1, tr.y.values, 1 - tr.y.values)
    tr['win'] = win
    tr['pnl_per_share'] = win - price - fee
    tr['roi'] = tr.pnl_per_share / (price + fee)
    if mode == 'trade':
        tr['avail_sz'] = np.where(side == 1, df.loc[tr.index, 'ask_sz'], df.loc[tr.index, 'bid_sz'])
    return tr.dropna(subset=['price'])


def summarize(tr, stakes=(10, 50, 200)):
    if len(tr) == 0:
        return {'n': 0}
    tr = tr.sort_values('t')
    out = {'n': len(tr), 'n_events': tr.event_slug.nunique(), 'hit': tr.win.mean(),
           'avg_price': tr.price.mean(), 'avg_fee': tr.fee.mean(), 'roi': tr.pnl_per_share.sum() / (tr.price + tr.fee).sum(),
           'roi_mean': tr.roi.mean(), 'roi_se': tr.roi.std(ddof=1) / np.sqrt(len(tr)) if len(tr) > 1 else np.nan}
    # event-clustered t-stat (strikes in the same event are highly correlated)
    ev = tr.groupby('event_slug').apply(lambda g: pd.Series({'pnl': g.pnl_per_share.div(g.price + g.fee).sum(), 'n': len(g)}), include_groups=False)
    out['t_clustered'] = ev.pnl.mean() / (ev.pnl.std(ddof=1) / np.sqrt(len(ev))) if len(ev) > 2 else np.nan
    for s in stakes:
        pnl = s * tr.roi.values  # fixed $ stake per trade (incl fee) -> pnl = stake*roi
        cum = np.cumsum(pnl)
        dd = np.max(np.maximum.accumulate(np.concatenate([[0], cum]))[1:] - cum) if len(cum) else 0
        out[f'pnl_{s}'] = pnl.sum(); out[f'maxdd_{s}'] = dd
    days = (tr.t.max() - tr.t.min()) / 86400 + 1
    out['trades_per_day'] = len(tr) / days
    return out


# ------------------------------------------------------------------ v2 backtest: signal at t, execution modes
def cost_from_mid(mid, h):
    """Total one-way cost (half-spread + slippage) relative to the mid, in price units.
    Calibrated conservatively from (i) effective half-spreads of 1.4M taker fills vs prevailing mid
    (median 0.5-0.75c mid-range) and (ii) live books (1c spread near expiry, ~4c for events >2d out)."""
    mid = np.asarray(mid); h = np.asarray(h, dtype=float)
    tail = np.minimum(mid, 1 - mid)
    base = np.where(h <= 6, 0.015, np.where(h <= 24, 0.02, 0.03))
    return np.where(tail < 0.03, 0.005, np.where(tail < 0.10, np.minimum(base, 0.01), base))


def backtest(df, pcol, theta, exec_mode='mid0', pmin=0.0, pmax=1.0, limit_slack=0.01, sides=(1, -1)):
    """Signal at t: buy YES if p - ask_est - fee > theta (ask_est = mid + cost), buy NO symmetric.
    exec_mode: 'mid0' execute at ask_est; 'mid5'/'mid15' execute at delayed mid + cost;
               'trade_slow' execute at first actual taker fill (YES-equiv) in (t+60s, t+15m] if <= ask_est + limit_slack
    """
    d = df.dropna(subset=[pcol, 'mid']).copy()
    mid = d.mid.values; p = d[pcol].values; h = d.h.values
    c = cost_from_mid(mid, h)
    ya = np.clip(mid + c, 0.001, 0.999); na = np.clip(1 - mid + c, 0.001, 0.999)
    ey = p - ya - taker_fee_per_share(ya)
    en = (1 - p) - na - taker_fee_per_share(na)
    buy_y = (ey > theta) & (ey >= en) & (ya >= pmin) & (ya <= pmax) & (1 in sides)
    buy_n = (en > theta) & (en > ey) & (na >= pmin) & (na <= pmax) & (-1 in sides)
    sel = buy_y | buy_n
    tr = d.loc[sel].copy()
    side = np.where(buy_y, 1, -1)[sel]
    sig_price = np.where(buy_y, ya, na)[sel]
    tr['side'] = side; tr['sig_price'] = sig_price; tr['edge_sig'] = np.where(buy_y, ey, en)[sel]
    if exec_mode == 'mid0':
        px = sig_price
    elif exec_mode in ('mid5', 'mid15'):
        md = tr['mid_d5' if exec_mode == 'mid5' else 'mid_d15'].values
        cc = cost_from_mid(md, tr.h.values)
        px = np.where(side == 1, md + cc, 1 - md + cc)
    elif exec_mode == 'trade_slow':
        # first actual taker fill (YES-equiv) in (t+60s, t+15m]; if none, fall back to the mid-based price
        # (never drop the trade: dropping would condition on future order flow = look-ahead)
        px = np.where(side == 1, tr.ask_slow.values, 1 - tr.bid_slow.values)
        px = np.where(np.isfinite(px), px, sig_price)
        px = np.where(px <= sig_price + limit_slack, px, np.nan)  # limit not reached -> no fill
    else:
        raise ValueError(exec_mode)
    tr['price'] = np.clip(px, 0.001, 0.999)
    tr = tr[np.isfinite(px)]
    tr['fee'] = taker_fee_per_share(tr.price.values)
    tr['win'] = np.where(tr.side == 1, tr.y, 1 - tr.y)
    tr['pnl_per_share'] = tr.win - tr.price - tr.fee
    tr['roi'] = tr.pnl_per_share / (tr.price + tr.fee)
    return tr
