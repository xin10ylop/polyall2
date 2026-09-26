"""Underlying data for finance barrier markets.
Yahoo chart API 1h bars (730d) for GC=F, SI=F, CL=F, NG=F, SPY, NVDA (+5m for last 60d);
Binance USD-M perps XAUUSDT / XAGUSDT 1h (spot-gold/silver proxies, 24/7) from data.binance.vision.
Output: data/crypto/fin/<name>_<interval>.parquet with ts (bar open, unix s), o,h,l,c."""
import io, zipfile, datetime as dt
import numpy as np, pandas as pd, requests
from common import DATA, session

OUT = DATA / 'fin'
OUT.mkdir(exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0'}


def yahoo(sym, interval, rng):
    r = session().get(f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}',
                      params={'interval': interval, 'range': rng, 'includePrePost': 'false'}, headers=UA, timeout=60)
    j = r.json()['chart']['result'][0]
    q = j['indicators']['quote'][0]
    df = pd.DataFrame({'ts': j['timestamp'], 'o': q['open'], 'h': q['high'], 'l': q['low'], 'c': q['close']}).dropna()
    df['ts'] = df.ts.astype('int64')
    return df


def binance_um(sym, interval='1h', start='2025-06'):
    frames = []
    y, m = map(int, start.split('-'))
    cur = dt.date(y, m, 1)
    today = dt.date.today()
    while cur < dt.date(today.year, today.month, 1):
        u = f'https://data.binance.vision/data/futures/um/monthly/klines/{sym}/{interval}/{sym}-{interval}-{cur:%Y-%m}.zip'
        r = session().get(u, timeout=60)
        if r.status_code == 200:
            z = zipfile.ZipFile(io.BytesIO(r.content))
            d = pd.read_csv(z.open(z.namelist()[0]))
            if not str(d.columns[0]).isdigit() and 'open_time' not in d.columns:
                d = pd.read_csv(z.open(z.namelist()[0]), header=None)
            d = d.iloc[:, :5]; d.columns = ['ts', 'o', 'h', 'l', 'c']
            d = d[pd.to_numeric(d.ts, errors='coerce').notna()].astype(float)
            frames.append(d)
        cur = (cur.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    d = cur
    while d < today:
        u = f'https://data.binance.vision/data/futures/um/daily/klines/{sym}/{interval}/{sym}-{interval}-{d:%Y-%m-%d}.zip'
        r = session().get(u, timeout=60)
        if r.status_code == 200:
            z = zipfile.ZipFile(io.BytesIO(r.content))
            x = pd.read_csv(z.open(z.namelist()[0]))
            if 'open_time' not in x.columns:
                x = pd.read_csv(z.open(z.namelist()[0]), header=None)
            x = x.iloc[:, :5]; x.columns = ['ts', 'o', 'h', 'l', 'c']
            x = x[pd.to_numeric(x.ts, errors='coerce').notna()].astype(float)
            frames.append(x)
        d += dt.timedelta(days=1)
    df = pd.concat(frames)
    df['ts'] = (df.ts // 1000).astype('int64')
    return df.drop_duplicates('ts').sort_values('ts')


if __name__ == '__main__':
    for name, sym in [('GC', 'GC=F'), ('SI', 'SI=F'), ('CL', 'CL=F'), ('NG', 'NG=F'), ('SPY', 'SPY'), ('NVDA', 'NVDA')]:
        d = yahoo(sym, '1h', '730d'); d.to_parquet(OUT / f'{name}_1h.parquet')
        d5 = yahoo(sym, '5m', '60d'); d5.to_parquet(OUT / f'{name}_5m.parquet')
        print(name, len(d), pd.to_datetime(d.ts.min(), unit='s'), pd.to_datetime(d.ts.max(), unit='s'), '5m', len(d5), flush=True)
    for sym in ['XAUUSDT', 'XAGUSDT']:
        d = binance_um(sym, '1h', '2025-06')
        d.to_parquet(OUT / f'{sym}_1h.parquet')
        print(sym, len(d), pd.to_datetime(d.ts.min(), unit='s'), pd.to_datetime(d.ts.max(), unit='s'), flush=True)
