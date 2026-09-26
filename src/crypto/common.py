"""Shared helpers: HTTP session with retries, paths, caching, fee formula."""
import os, json, time, gzip
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path('/home/user/polyall2')
DATA = ROOT / 'data' / 'crypto'
DATA.mkdir(parents=True, exist_ok=True)

GAMMA = 'https://gamma-api.polymarket.com'
CLOB = 'https://clob.polymarket.com'
DAPI = 'https://data-api.polymarket.com'

_session = None


def session():
    global _session
    if _session is None:
        s = requests.Session()
        retry = Retry(total=8, backoff_factor=0.7, status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods=['GET'])
        s.mount('https://', HTTPAdapter(max_retries=retry, pool_maxsize=32))
        _session = s
    return _session


def get_json(url, params=None, timeout=30):
    for attempt in range(6):
        try:
            r = session().get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 404):
                return None
            time.sleep(1 + attempt * 2)
        except requests.RequestException:
            time.sleep(1 + attempt * 2)
    raise RuntimeError(f'failed {url} {params}')


def save_json_gz(obj, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with gzip.open(tmp, 'wt') as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def load_json_gz(path):
    with gzip.open(path, 'rt') as f:
        return json.load(f)


# Polymarket crypto taker fee (docs.polymarket.com/trading/fees, crypto_fees_v2):
#   fee_usdc = shares * rate * p * (1-p), rate = 0.07, taker only; makers pay 0.
FEE_RATE_CRYPTO = 0.07


def taker_fee_per_share(p, rate=FEE_RATE_CRYPTO):
    return rate * p * (1.0 - p)


def to_unix(s):
    """tz-aware datetime Series -> int64 unix seconds (robust to ns/us resolution in pandas 3)."""
    import pandas as pd
    return ((s - pd.Timestamp('1970-01-01', tz='UTC')) // pd.Timedelta('1s')).astype('int64')
