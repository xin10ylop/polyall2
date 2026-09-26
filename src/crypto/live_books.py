"""Snapshot live CLOB order books for currently open crypto threshold markets.
Summarises best bid/ask, spread, and depth (USDC) within 1c/3c/5c of the touch, per strike.
Saves data/crypto/live_books_<timestamp>.parquet"""
import sys, time, json, concurrent.futures as cf
import numpy as np, pandas as pd
from common import DATA, CLOB, GAMMA, get_json

SLUG_PREFIXES = {
    'above_daily': ['bitcoin-above-on-', 'ethereum-above-on-', 'solana-above-on-', 'xrp-above-on-'],
    'range': ['bitcoin-price-on-', 'ethereum-price-on-'],
    'touch': ['what-price-will-bitcoin-hit-', 'what-price-will-ethereum-hit-'],
    'updown': ['bitcoin-up-or-down-', 'btc-updown-15m-'],
}


def open_events(series_ids):
    evs = []
    for sid in series_ids:
        cur = None
        while True:
            p = {'series_id': sid, 'limit': 100, 'closed': 'false', 'order': 'endDate', 'ascending': 'true'}
            if cur:
                p['after_cursor'] = cur
            r = get_json(f'{GAMMA}/events/keyset', params=p)
            if not r or not r.get('events'):
                break
            evs += r['events']
            cur = r.get('next_cursor')
            if not cur or len(evs) > 400:
                break
    return evs


def book_summary(tok):
    b = get_json(f'{CLOB}/book', params={'token_id': tok})
    if not b:
        return None
    bids = sorted([(float(x['price']), float(x['size'])) for x in b.get('bids', [])], reverse=True)
    asks = sorted([(float(x['price']), float(x['size'])) for x in b.get('asks', [])])
    out = {'best_bid': bids[0][0] if bids else np.nan, 'best_ask': asks[0][0] if asks else np.nan,
           'bid_sz0': bids[0][1] if bids else 0, 'ask_sz0': asks[0][1] if asks else 0,
           'tick': float(b.get('tick_size') or 0.01)}
    for w in (0.01, 0.03, 0.05):
        out[f'ask_usd_{int(w*100)}c'] = sum(p * s for p, s in asks if asks and p <= asks[0][0] + w + 1e-9)
        out[f'bid_usd_{int(w*100)}c'] = sum(p * s for p, s in bids if bids and p >= bids[0][0] - w - 1e-9)
    return out


def main():
    sids = {'above_daily': [45, 42, 10022, 10024], 'range': [10041, 10065], 'touch': [10016, 10151, 10200],
            'updown': [10114, 10192], 'above_hourly': [11372]}
    now = pd.Timestamp.now(tz='UTC')
    rows = []
    for fam, ids in sids.items():
        evs = open_events(ids)
        evs = [e for e in evs if pd.Timestamp(e['endDate']) > now]
        if fam in ('updown', 'above_hourly'):
            evs = sorted(evs, key=lambda e: e['endDate'])[:6]
        for e in evs:
            for m in e.get('markets', []):
                if m.get('closed') or not m.get('acceptingOrders', True):
                    continue
                toks = json.loads(m.get('clobTokenIds') or '[]')
                if len(toks) != 2:
                    continue
                rows.append(dict(family=fam, event_slug=e['slug'], end=e['endDate'], question=m['question'],
                                 git=m.get('groupItemTitle'), tok_yes=toks[0], tok_no=toks[1],
                                 volume24=float(m.get('volume24hr') or 0)))
    df = pd.DataFrame(rows)
    print('markets', len(df), df.family.value_counts().to_dict(), flush=True)
    with cf.ThreadPoolExecutor(8) as ex:
        res = list(ex.map(book_summary, df.tok_yes))
    bs = pd.DataFrame([r or {} for r in res])
    df = pd.concat([df.reset_index(drop=True), bs], axis=1)
    df['mid'] = (df.best_bid + df.best_ask) / 2
    df['spread'] = df.best_ask - df.best_bid
    df['snap'] = now
    fn = DATA / f'live_books_{now:%Y%m%dT%H%M}.parquet'
    df.to_parquet(fn)
    print(fn)
    return df


if __name__ == '__main__':
    main()
