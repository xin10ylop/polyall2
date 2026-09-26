"""Shared helpers for tweet-count market research."""
import numpy as np, pandas as pd
D = "/home/user/polyall2/data/tweets"
ACCTS = ["elonmusk", "realDonaldTrump", "WhiteHouse", "tedcruz", "ZelenskyyUa", "NYCMayor", "cz_binance",
         "khamenei_ir", "Cobratate"]

_posts = {}
def posts(h):
    if h not in _posts:
        p = pd.read_parquet(f"{D}/xt/posts_{h}.parquet")
        p = p.sort_values("createdAt").drop_duplicates("platformId").reset_index(drop=True)
        _posts[h] = p
    return _posts[h]

def events():
    E = pd.read_parquet(f"{D}/events.parquet"); B = pd.read_parquet(f"{D}/buckets.parquet")
    return E, B

def count_in(h, s, e, asof=None):
    """xtracker count of posts with createdAt in [s, e). If asof given, only posts imported by asof."""
    p = posts(h)
    ca = p.createdAt.values
    m = (ca >= np.datetime64(s.tz_convert(None) if s.tzinfo else s)) & (ca < np.datetime64(e.tz_convert(None) if e.tzinfo else e))
    if asof is not None:
        m &= p.importedAt.values <= np.datetime64(asof.tz_convert(None))
    return int(m.sum())

def bucket_of(n, lo, hi):
    for k, (a, b) in enumerate(zip(lo, hi)):
        if a <= n <= b: return k
    return -1

def taker_fee(price, rate):
    """fee per share for a taker buy at price p."""
    return rate * price * (1 - price)

GAP_H = 40  # hours without any post => tracker outage (only for accounts averaging >= 10 posts/day)
def gaps(h):
    """Detected tracker outages [(start_ts, end_ts)] in unix seconds (no look-ahead issue: used only to
    exclude calibration points / events from evaluation, never as a model input)."""
    p = posts(h); c = p.createdAt.values.astype("datetime64[s]").astype("int64")
    rate = len(c) / max((c[-1] - c[0]) / 86400, 1)
    if rate < 10: return []
    d = np.diff(c)
    idx = np.where(d > GAP_H * 3600)[0]
    return [(int(c[i]), int(c[i + 1])) for i in idx]

def overlaps_gap(h, s, e):
    return any(not (e <= g0 or s >= g1) for g0, g1 in gaps(h))
