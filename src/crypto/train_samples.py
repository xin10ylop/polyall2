"""Training samples for the spot vol model: for every hour T (UTC, on the hour) and horizon h,
features at t=T-h and realised r=ln(S_T/S_t) with S_T = close of 1m candle opened at T (daily-market convention).
Saved to data/crypto/train_<ASSET>.parquet. Every feature row uses only data available at t."""
import sys
import numpy as np, pandas as pd
from volmodel import Features
from common import DATA

H_LIST = [0.25, 0.5, 1, 2, 3, 6, 12, 24, 48, 72, 120, 168, 336, 720]


def build(asset, start='2024-10-15', end='2026-09-26'):
    F = Features(asset)
    T = pd.date_range(start, end, freq='h', tz='UTC')
    T = ((T - pd.Timestamp('1970-01-01', tz='UTC')) // pd.Timedelta('1s')).values.astype('int64')
    T = T[T + 120 < F.spot.index.max()]
    out = []
    for h in H_LIST:
        t = T - int(h * 3600)
        ok = t > F.spot.index.min() + 45 * 86400
        df = F.build(t[ok], T[ok])
        df['h'] = h
        out.append(df)
    d = pd.concat(out, ignore_index=True)
    d.to_parquet(DATA / f'train_{asset}.parquet', compression='zstd')
    print(asset, len(d), flush=True)
    return d


if __name__ == '__main__':
    for a in (sys.argv[1:] or ['BTC', 'ETH', 'SOL', 'XRP']):
        build(a)
