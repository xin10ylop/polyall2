"""Enumerate all events (closed + open) for the crypto series of interest via gamma-api.
Saves raw event JSON (incl. markets) to data/crypto/events/<series_slug>.json.gz
"""
import sys
from common import GAMMA, DATA, get_json, save_json_gz, load_json_gz

SERIES = {
    # family a: "X above K on date" (daily noon ET) and hourly/4h variants
    45: 'btc-multi-strikes-weekly', 42: 'ethereum-multi-strikes-weekly',
    10022: 'solana-multi-strikes-weekly', 10024: 'xrp-multi-strikes-weekly',
    11372: 'bitcoin-multi-strikes-hourly', 11373: 'ethereum-multi-strikes-hourly',
    10202: 'bitcoin-multi-strikes-4h', 10231: 'ethereum-multi-strikes-4h',
    # family b: touch / hit price
    10016: 'bitcoin-hit-price-monthly', 10017: 'ethereum-hit-price-monthly',
    10032: 'solana-hit-price-monthly', 10039: 'xrp-hit-price-monthly',
    10151: 'bitcoin-hit-price-weekly', 10152: 'ethereum-hit-price-weekly',
    10170: 'solana-hit-price-weekly', 10239: 'xrp-hit-price-weekly',
    10200: 'bitcoin-hit-price-daily', 11297: 'ethereum-hit-price-daily',
    # family c: range buckets (neg risk)
    10041: 'bitcoin-neg-risk-weekly', 10065: 'ethereum-neg-risk-weekly',
    10107: 'solana-neg-risk-weekly', 10247: 'xrp-neg-risk-weekly',
    # family d: up/down
    41: 'btc-up-or-down-daily', 10114: 'btc-up-or-down-hourly', 10331: 'btc-up-or-down-4h',
    40: 'eth-up-or-down-daily', 10117: 'eth-up-or-down-hourly',
    10192: 'btc-up-or-down-15m', 10684: 'btc-up-or-down-5m',
}


def fetch_series(sid, max_events=200000):
    """Keyset (cursor) pagination; offset pagination is capped at 2000 by gamma."""
    out = {}
    for closed in ('true', 'false'):
        cur = None
        n = 0
        while True:
            p = {'series_id': sid, 'limit': 100, 'closed': closed, 'order': 'endDate', 'ascending': 'false'}
            if cur:
                p['after_cursor'] = cur
            r = get_json(f'{GAMMA}/events/keyset', params=p)
            if not r or not r.get('events'):
                break
            for e in r['events']:
                out[e['id']] = e
            n += len(r['events'])
            cur = r.get('next_cursor')
            if not cur or n >= max_events:
                break
    return list(out.values())


if __name__ == '__main__':
    ids = [int(x) for x in sys.argv[1:]] or list(SERIES)
    for sid in ids:
        path = DATA / 'events' / f'{SERIES[sid]}.json.gz'
        if path.exists() and '--force' not in sys.argv:
            print('skip', path); continue
        # 5m/15m series are enormous; cap to recent history
        cap = 20000 if sid in (10192, 10684) else 200000
        ev = fetch_series(sid, cap)
        save_json_gz(ev, path)
        ends = sorted(e.get('endDate') or '' for e in ev)
        print(sid, SERIES[sid], len(ev), ends[0] if ends else None, ends[-1] if ends else None, flush=True)
