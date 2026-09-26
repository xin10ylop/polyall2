"""Spot-based fair-value model for crypto price-threshold markets (no look-ahead).

Price/return convention (Binance 1m klines, ts = candle open time, seconds):
  price "at" time t  := close of the 1m candle opened at t-60 (last completed candle at t)
  daily 'above' markets resolve on close of the candle opened at T=event_end (noon ET)
  hourly 'above'  markets resolve on close of the candle opened at T-60 (1h candle ending at T)

Vol inputs available at decision time t:
  * DVOL (Deribit 30d implied vol index, hourly candles; we use close of the last *completed* hour)
  * RV EWMA of deseasonalised 5m returns (half-lives 6h, 1d, 7d)
  * minute-of-week seasonal variance profile estimated on trailing data only
Model: r = ln(S_T/S_t) ~ Student-t(nu) with scale s = exp(b . x) * sqrt(tau_years * seas_frac)
  x = [1, log dvol, log rv6h, log rv1d, log rv7d]  (fitted by MLE per horizon bucket, walk-forward)
"""
import numpy as np, pandas as pd
from scipy import stats, optimize
from common import DATA

YEAR_MIN = 365.0 * 1440
MOW = 10080  # minutes per week
SYMS = {'BTC': 'BTCUSDT', 'ETH': 'ETHUSDT', 'SOL': 'SOLUSDT', 'XRP': 'XRPUSDT'}
_cache = {}


def load_spot(asset):
    if ('spot', asset) not in _cache:
        df = pd.read_parquet(DATA / 'spot' / f'{SYMS[asset]}_1m.parquet')
        # regular 1m grid, forward fill gaps
        grid = np.arange(df.ts.min(), df.ts.max() + 60, 60)
        df = df.set_index('ts').reindex(grid)
        df['c'] = df['c'].ffill()
        for col in ['h', 'l']:
            df[col] = df[col].fillna(df['c'])
        _cache[('spot', asset)] = df
    return _cache[('spot', asset)]


def load_dvol(asset):
    cur = asset if asset in ('BTC', 'ETH') else 'ETH'   # proxy for SOL/XRP (only used if model includes it)
    if ('dvol', cur) not in _cache:
        d = pd.read_parquet(DATA / 'spot' / f'DVOL_{cur}.parquet').set_index('ts')['c']
        _cache[('dvol', cur)] = d
    return _cache[('dvol', cur)]


def price_at(spot, t):
    """t: array of unix seconds (multiple of 60). Returns last completed close at t."""
    return spot['c'].reindex(np.asarray(t) - 60).values


def dvol_at(asset, t):
    d = load_dvol(asset)
    # hourly candle with open ts covers [ts, ts+3600); completed if ts+3600 <= t
    key = (np.asarray(t) // 3600) * 3600 - 3600
    idx = d.index.values
    i = np.searchsorted(idx, key, side='right') - 1
    out = np.where(i >= 0, d.values[np.clip(i, 0, None)], np.nan)
    stale = key - idx[np.clip(i, 0, None)]
    return np.where(stale <= 3 * 3600, out, np.nan)


def seasonal_profile(spot, end_ts, days=365):
    """minute-of-week mean squared 1m log return, normalised to mean 1, using data in [end-days, end)."""
    s = spot.loc[max(spot.index[0], end_ts - days * 86400): end_ts - 60, 'c']
    r = np.log(s).diff().values[1:]
    ts = s.index.values[1:]
    mow = ((ts // 60) + 4 * 1440) % MOW  # 1970-01-01 is Thursday -> shift so 0 = Monday 00:00 UTC
    r2 = np.clip(r ** 2, 0, np.nanpercentile(r ** 2, 99.9))
    prof = np.bincount(mow, weights=np.nan_to_num(r2), minlength=MOW) / np.maximum(np.bincount(mow, minlength=MOW), 1)
    # circular smoothing (31 min)
    k = 31
    ext = np.concatenate([prof[-k:], prof, prof[:k]])
    sm = np.convolve(ext, np.ones(k) / k, mode='same')[k:-k]
    return sm / sm.mean()


def mow_of(ts):
    return ((np.asarray(ts) // 60) + 4 * 1440) % MOW


def seas_frac(prof, t0, t1):
    """mean seasonal weight over minutes (t0, t1] (vectorised via cumulative sum over 2 weeks)."""
    cs = np.concatenate([[0], np.cumsum(np.concatenate([prof, prof]))])
    t0 = np.asarray(t0); t1 = np.asarray(t1)
    n = (t1 - t0) // 60
    full_weeks = n // MOW
    rem = n % MOW
    a = mow_of(t0)
    part = cs[a + rem] - cs[a]
    return (full_weeks * prof.sum() + part) / np.maximum(n, 1)


def rv_series(spot, prof, halflives_h=(6, 24, 168)):
    """EWMA annualised vol of deseasonalised 5m log returns; value indexed by the 5m bar END time."""
    c = spot['c']
    c5 = c[(c.index % 300) == 240]  # close of candle opened at xx:x4 -> price at 5m boundary
    r = np.log(c5).diff()
    end_ts = c5.index.values + 60
    # average seasonal weight over the 5 minutes
    w5 = np.mean([prof[mow_of(end_ts - 60 * k)] for k in range(1, 6)], axis=0)
    x2 = (r.values ** 2) / w5
    x2 = np.clip(x2, 0, np.nanpercentile(x2, 99.95))
    out = {}
    for hl in halflives_h:
        e = pd.Series(x2, index=end_ts).ewm(halflife=hl * 12, min_periods=12 * 6, ignore_na=True).mean()
        out[f'rv{hl}h'] = np.sqrt(e * 288 * 365)
    return pd.DataFrame(out)


def rv_at(rv, t):
    key = (np.asarray(t) // 300) * 300
    return rv.reindex(key).values


class Features:
    """Precomputed features for one asset; seasonal profile re-estimated per calendar month (trailing)."""

    def __init__(self, asset):
        self.asset = asset
        self.spot = load_spot(asset)
        self.months = {}

    def prof_for(self, ts):
        m = pd.Timestamp(int(ts), unit='s').strftime('%Y-%m')
        if m not in self.months:
            start = int(pd.Timestamp(m + '-01', tz='UTC').timestamp())
            prof = seasonal_profile(self.spot, start)
            self.months[m] = (prof, None)
        return self.months[m][0]

    def rv_for_month(self, m):
        prof, rv = self.months[m]
        if rv is None:
            start = int(pd.Timestamp(m + '-01', tz='UTC').timestamp())
            sub = self.spot.loc[start - 40 * 86400: start + 32 * 86400]
            rv = rv_series(sub, prof)
            self.months[m] = (prof, rv)
        return rv

    def build(self, t, T, res_offset=0):
        """t, T arrays (unix s). res_offset: T candle-open offset: S_T = close of candle opened at T+res_offset.
        Returns DataFrame of features. S_T may be NaN for future T."""
        t = np.asarray(t, dtype='int64'); T = np.asarray(T, dtype='int64')
        df = pd.DataFrame({'t': t, 'T': T})
        df['S_t'] = price_at(self.spot, t)
        df['S_T'] = self.spot['c'].reindex(T + res_offset).values
        df['tau_min'] = (T + res_offset + 60 - t) / 60.0
        df['month'] = pd.to_datetime(t, unit='s').strftime('%Y-%m')
        df['seas'] = np.nan
        for c in ['rv6h', 'rv24h', 'rv168h']:
            df[c] = np.nan
        for m, idx in df.groupby('month').groups.items():
            self.prof_for(int(pd.Timestamp(m + '-01', tz='UTC').timestamp()) + 86400)
            prof = self.months[m][0]
            rv = self.rv_for_month(m)
            sub = df.loc[idx]
            df.loc[idx, 'seas'] = seas_frac(prof, sub['t'].values, (sub['T'].values + res_offset + 60))
            vals = rv_at(rv, sub['t'].values)
            df.loc[idx, ['rv6h', 'rv24h', 'rv168h']] = vals
        df['dvol'] = dvol_at(self.asset, t) / 100.0
        df['r'] = np.log(df.S_T / df.S_t)
        return df


# ---------------------------------------------------------------- Student-t scale model
XCOLS = {
    'dvol': ['dvol'],
    'rv': ['rv6h', 'rv24h', 'rv168h'],
    'combo': ['dvol', 'rv6h', 'rv24h', 'rv168h'],
}


def design(df, spec):
    X = [np.ones(len(df))] + [np.log(df[c].values) for c in XCOLS[spec]]
    return np.column_stack(X)


def base_scale(df):
    return np.sqrt(df.tau_min.values / YEAR_MIN * df.seas.values)


def fit_t(df, spec, weights=None, fix_nu=None):
    df = df.dropna(subset=['r', 'seas'] + XCOLS[spec])
    X = design(df, spec)
    b0 = base_scale(df)
    r = df.r.values
    w = np.ones(len(df)) if weights is None else weights

    def nll(theta):
        beta = theta[:-1]
        nu = fix_nu if fix_nu else 2.05 + np.exp(theta[-1])
        s = np.exp(X @ beta) * b0
        return -np.sum(w * (stats.t.logpdf(r / s, nu) - np.log(s))) / w.sum()

    beta0 = np.zeros(X.shape[1]); beta0[0] = np.log(np.nanmedian(np.abs(r) / b0) * 1.4)
    if X.shape[1] > 1:
        beta0[1] = 1.0 if spec == 'dvol' else 0.0
        if spec != 'dvol':
            beta0[1:] = 1.0 / (X.shape[1] - 1)
            beta0[0] = 0.0
    th0 = np.concatenate([beta0, [np.log(3.0)]])
    res = optimize.minimize(nll, th0, method='L-BFGS-B')
    beta = res.x[:-1]
    nu = fix_nu if fix_nu else 2.05 + np.exp(res.x[-1])
    return {'spec': spec, 'beta': beta, 'nu': nu, 'n': len(df), 'nll': res.fun}


def scale(params, df):
    return np.exp(design(df, params['spec']) @ params['beta']) * base_scale(df)


def p_above(params, df, K, gaussian=False):
    s = scale(params, df)
    x = np.log(np.asarray(K) / df.S_t.values) / s
    if gaussian:
        # match variance of the t: var = nu/(nu-2) * s^2
        nu = params['nu']
        return stats.norm.sf(x / np.sqrt(nu / (nu - 2)))
    return stats.t.sf(x, params['nu'])
