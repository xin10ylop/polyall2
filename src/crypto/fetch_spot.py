"""Binance spot 1m klines (the resolution source for Polymarket crypto markets) from
data.binance.vision archive (monthly+daily zips) + data-api.binance.vision for the tail.
Saves data/crypto/spot/<SYMBOL>_1m.parquet with columns ts (UTC open time, int64 seconds), o,h,l,c,v.
Also Deribit DVOL hourly for BTC/ETH -> data/crypto/spot/DVOL_<CUR>.parquet
"""
import io, sys, zipfile, datetime as dt, time
import numpy as np, pandas as pd
from common import DATA, session, get_json

OUT = DATA / 'spot'
OUT.mkdir(parents=True, exist_ok=True)
ARCH = 'https://data.binance.vision/data/spot'


def _parse_zip(content):
    z = zipfile.ZipFile(io.BytesIO(content))
    name = z.namelist()[0]
    df = pd.read_csv(z.open(name), header=None, usecols=[0, 1, 2, 3, 4, 5])
    df.columns = ['ts', 'o', 'h', 'l', 'c', 'v']
    # 2025+ files are in microseconds
    ts = df['ts'].astype('int64')
    ts = np.where(ts > 1e15, ts // 1_000_000, np.where(ts > 1e12, ts // 1000, ts))
    df['ts'] = ts.astype('int64')
    return df


def fetch_symbol(sym, start='2024-09', end_day=None):
    end_day = end_day or dt.date.today()
    frames = []
    s = session()
    y, m = map(int, start.split('-'))
    cur = dt.date(y, m, 1)
    # monthly files up to last full month
    first_of_this_month = dt.date(end_day.year, end_day.month, 1)
    while cur < first_of_this_month:
        url = f'{ARCH}/monthly/klines/{sym}/1m/{sym}-1m-{cur:%Y-%m}.zip'
        r = s.get(url, timeout=120)
        if r.status_code == 200:
            frames.append(_parse_zip(r.content))
        else:
            print('missing', url, r.status_code)
        cur = (cur.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    # daily files for current month
    d = first_of_this_month
    while d < end_day:
        url = f'{ARCH}/daily/klines/{sym}/1m/{sym}-1m-{d:%Y-%m-%d}.zip'
        r = s.get(url, timeout=120)
        if r.status_code == 200:
            frames.append(_parse_zip(r.content))
        d += dt.timedelta(days=1)
    df = pd.concat(frames, ignore_index=True)
    # tail via REST
    last = int(df['ts'].max())
    while True:
        r = get_json('https://data-api.binance.vision/api/v3/klines',
                     params={'symbol': sym, 'interval': '1m', 'startTime': (last + 60) * 1000, 'limit': 1000})
        if not r:
            break
        t = pd.DataFrame([[x[0] // 1000, float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])] for x in r],
                         columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        df = pd.concat([df, t], ignore_index=True)
        last = int(t['ts'].max())
        if len(r) < 1000:
            break
    df = df.drop_duplicates('ts').sort_values('ts').reset_index(drop=True)
    for col in ['o', 'h', 'l', 'c']:
        df[col] = df[col].astype('float64')
    df['v'] = df['v'].astype('float32')
    df.to_parquet(OUT / f'{sym}_1m.parquet', compression='zstd')
    print(sym, len(df), pd.to_datetime(df.ts.min(), unit='s'), pd.to_datetime(df.ts.max(), unit='s'), flush=True)


def fetch_dvol(cur='BTC', start='2024-09-01'):
    t0 = int(pd.Timestamp(start, tz='UTC').timestamp() * 1000)
    t1 = int(time.time() * 1000)
    rows = []
    end = t1
    while True:
        r = get_json('https://www.deribit.com/api/v2/public/get_volatility_index_data',
                     params={'currency': cur, 'start_timestamp': t0, 'end_timestamp': end, 'resolution': 3600})
        data = r['result']['data']
        if not data:
            break
        rows += data
        cont = r['result'].get('continuation')
        if not cont or cont <= t0:
            break
        end = cont
    df = pd.DataFrame(rows, columns=['ts', 'o', 'h', 'l', 'c'])
    df['ts'] = df['ts'] // 1000
    df = df.drop_duplicates('ts').sort_values('ts').reset_index(drop=True)
    df.to_parquet(OUT / f'DVOL_{cur}.parquet')
    print('DVOL', cur, len(df), pd.to_datetime(df.ts.min(), unit='s'), pd.to_datetime(df.ts.max(), unit='s'), flush=True)


if __name__ == '__main__':
    what = sys.argv[1:] or ['DVOL', 'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT']
    for w in what:
        if w == 'DVOL':
            fetch_dvol('BTC'); fetch_dvol('ETH')
        else:
            fetch_symbol(w)
