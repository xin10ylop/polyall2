"""Keep the cache under budget: drop long descriptions from big market tables; thin 1-min price
history older than 2h before expiry to 5-min spacing (panels already built keep full detail)."""
import glob, sys
import pandas as pd
from common import DATA, to_unix

for f in ['markets_bitcoin-multi-strikes-hourly', 'markets_ethereum-multi-strikes-hourly', 'markets_btc-up-or-down-15m',
          'markets_btc-up-or-down-5m', 'markets_btc-up-or-down-hourly', 'markets_eth-up-or-down-hourly']:
    p = DATA / f'{f}.parquet'
    d = pd.read_parquet(p)
    if 'desc' in d:
        d['desc'] = d['desc'].str[:120]
        d.to_parquet(p, compression='zstd')


def thin(series):
    mk = pd.concat([pd.read_parquet(p) for p in glob.glob(str(DATA / 'markets_*.parquet')) if series in p])
    T = dict(zip(mk.condition_id, to_unix(mk.event_end)))
    for f in sorted(glob.glob(str(DATA / 'ph' / series / 'ph_*.parquet'))):
        d = pd.read_parquet(f)
        Te = d.cid.map(T)
        keep = (d.fid != 1) | (d.t >= Te - 7200) | ((d.t // 60) % 5 == 0)
        d[keep].to_parquet(f, compression='zstd')


if __name__ == '__main__':
    for s in sys.argv[1:]:
        thin(s)
