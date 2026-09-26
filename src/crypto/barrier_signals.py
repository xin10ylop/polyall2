#!/usr/bin/env python3
"""Live (read-only) signal scanner for the daily-barrier longshot sale.

Rule (research/04_crypto_threshold_markets.md §8): in "What price will <X> hit on <day>/<week>/<month>?"
markets, for strikes not yet touched with <= MAX_HOURS to the end of the window and YES mid in
[0.5c, 3c), buy NO at the ask (taker fee 0.07*p*(1-p) per share). Also lists 3-6c strikes ("watch").
Optional risk filter (pre-registered on H1, see §8.3): skip when the strike is closer than MIN_X
standard deviations (sigma*sqrt(tau), sigma = realised vol of the last 24h of Binance 1m returns),
or when realised 1h vol is above its trailing-30d 90th percentile.

NO ORDERS ARE PLACED. Usage:
  python barrier_signals.py [--max-hours 12] [--min-x 0] [--rv-filter] [--all] [--json out.json]
"""
import argparse, json, math, sys, time, concurrent.futures as cf
from datetime import datetime, timezone
import numpy as np
import requests

GAMMA = 'https://gamma-api.polymarket.com'
CLOB = 'https://clob.polymarket.com'
BINANCE = 'https://data-api.binance.vision/api/v3/klines'
SERIES = {  # series_id: (asset, family)
    10200: ('BTC', 'daily'), 11297: ('ETH', 'daily'), 11298: ('SOL', 'daily'), 11299: ('XRP', 'daily'),
    10151: ('BTC', 'weekly'), 10152: ('ETH', 'weekly'), 10170: ('SOL', 'weekly'), 10239: ('XRP', 'weekly'),
    10016: ('BTC', 'monthly'), 10017: ('ETH', 'monthly'), 10032: ('SOL', 'monthly'), 10039: ('XRP', 'monthly'),
}
SYM = {'BTC': 'BTCUSDT', 'ETH': 'ETHUSDT', 'SOL': 'SOLUSDT', 'XRP': 'XRPUSDT'}
FEE_RATE = 0.07
S = requests.Session()


def get(url, params=None):
    for i in range(5):
        try:
            r = S.get(url, params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(1 + i)
    return None


def fee(p):
    return FEE_RATE * p * (1 - p)


def open_events(sid):
    out, cur = [], None
    while True:
        p = {'series_id': sid, 'limit': 100, 'closed': 'false', 'order': 'endDate', 'ascending': 'true'}
        if cur:
            p['after_cursor'] = cur
        r = get(f'{GAMMA}/events/keyset', p)
        if not r or not r.get('events'):
            break
        out += r['events']
        cur = r.get('next_cursor')
        if not cur or len(out) >= 200:
            break
    return out


def spot_stats(asset):
    """last price, realised vol (annualised) over last 24h and last 1h, 90th pct of hourly rv1h over 30d."""
    kl = []
    end = None
    for _ in range(44):  # 44k minutes ~ 30.5 days
        p = {'symbol': SYM[asset], 'interval': '1m', 'limit': 1000}
        if end:
            p['endTime'] = end
        r = get(BINANCE, p)
        if not r:
            break
        kl = r + kl
        end = r[0][0] - 1
    c = np.array([float(x[4]) for x in kl])
    hi = np.array([float(x[2]) for x in kl]); lo = np.array([float(x[3]) for x in kl])
    ts = np.array([x[0] // 1000 for x in kl])
    r = np.diff(np.log(c))
    rv24 = math.sqrt(np.sum(r[-1440:] ** 2) * 365)
    rv1h = math.sqrt(np.sum(r[-60:] ** 2) * 365 * 24)
    hourly = [math.sqrt(np.sum(r[i - 60:i] ** 2) * 365 * 24) for i in range(60, len(r), 60)]
    return {'S': c[-1], 'rv24': rv24, 'rv1h': rv1h, 'rv1h_p90': float(np.percentile(hourly, 90)) if hourly else np.nan,
            'ts': ts, 'hi': hi, 'lo': lo}


def book(tok):
    b = get(f'{CLOB}/book', {'token_id': tok}) or {}
    bids = sorted([(float(x['price']), float(x['size'])) for x in b.get('bids', [])], reverse=True)
    asks = sorted([(float(x['price']), float(x['size'])) for x in b.get('asks', [])])
    return bids, asks


def scan(a):
    now = time.time()
    rows = []
    stats = {}
    for sid, (asset, fam) in SERIES.items():
        for e in open_events(sid):
            end = datetime.fromisoformat(e['endDate'].replace('Z', '+00:00')).timestamp()
            hl = (end - now) / 3600
            if hl <= 0 or (hl > a.max_hours and not a.all):
                continue
            for m in e.get('markets', []):
                if m.get('closed') or not m.get('acceptingOrders', True):
                    continue
                git = (m.get('groupItemTitle') or '')
                if not (git.startswith('↑') or git.startswith('↓')):
                    continue
                try:
                    H = float(git[1:].replace(',', '').replace('$', '').strip())
                except ValueError:
                    continue
                toks = json.loads(m.get('clobTokenIds') or '[]')
                if len(toks) != 2:
                    continue
                rows.append(dict(asset=asset, family=fam, event=e['slug'], market=m.get('slug'), dir='up' if git.startswith('↑') else 'down',
                                 H=H, hours_left=hl, tok_yes=toks[0], tok_no=toks[1]))
    if not rows:
        return []
    for asset in {r['asset'] for r in rows}:
        stats[asset] = spot_stats(asset)
    with cf.ThreadPoolExecutor(8) as ex:
        books = list(ex.map(lambda r: (book(r['tok_yes']), book(r['tok_no'])), rows))
    out = []
    for r, ((yb, ya), (nb, na)) in zip(rows, books):
        if not yb and not ya:
            continue
        ybid = yb[0][0] if yb else 0.0
        yask = ya[0][0] if ya else 1.0
        mid = (ybid + yask) / 2
        st = stats[r['asset']]
        S_ = st['S']
        dist = math.log(r['H'] / S_)
        if (r['dir'] == 'up' and dist <= 0) or (r['dir'] == 'down' and dist >= 0):
            continue  # spot already beyond strike -> touched / resolving
        sig = st['rv24'] * math.sqrt(r['hours_left'] / (365 * 24))
        x = abs(dist) / sig if sig > 0 else np.nan
        bucket = 'ELIGIBLE' if 0.005 <= mid < 0.03 else ('watch 3-6c' if 0.03 <= mid < 0.06 else None)
        if bucket is None:
            continue
        no_ask = na[0][0] if na else (1 - ybid if ybid else None)
        if no_ask is None or no_ask >= 1:
            continue
        d03 = sum(s for p, s in na if p <= no_ask + 0.003 + 1e-9)
        d10 = sum(s for p, s in na if p <= no_ask + 0.010 + 1e-9)
        f = fee(no_ask)
        roi_if_safe = (1 - no_ask - f) / (no_ask + f)
        flag = []
        if a.min_x and x < a.min_x:
            flag.append(f'x<{a.min_x}')
        if a.rv_filter and st['rv1h'] > st['rv1h_p90']:
            flag.append('rv1h>p90')
        out.append(dict(asset=r['asset'], family=r['family'], market=r['market'], dir=r['dir'], strike=r['H'], spot=S_,
                        hours_left=round(r['hours_left'], 2), yes_mid=round(mid, 4), no_ask=no_ask, fee=round(f, 5),
                        no_depth_0p3c=round(d03, 1), no_depth_1c=round(d10, 1), usd_0p3c=round(d03 * no_ask, 1),
                        roi_if_no_touch=round(roi_if_safe, 4), breakeven_touch_prob=round(1 - no_ask - f, 4),
                        x_sigma=round(x, 2), rv24=round(st['rv24'], 3), rv1h=round(st['rv1h'], 3),
                        bucket=bucket, skip=','.join(flag)))
    out.sort(key=lambda d: (d['bucket'] != 'ELIGIBLE', bool(d['skip']), d['hours_left'], -d['roi_if_no_touch']))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-hours', type=float, default=12)
    ap.add_argument('--min-x', type=float, default=0.0)
    ap.add_argument('--rv-filter', action='store_true')
    ap.add_argument('--all', action='store_true', help='ignore max-hours (show every open barrier strike in range)')
    ap.add_argument('--json', default=None)
    a = ap.parse_args()
    res = scan(a)
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    print(f'# barrier longshot scan {now}  (read-only; {len(res)} strikes)')
    cols = ['bucket', 'skip', 'asset', 'family', 'dir', 'strike', 'spot', 'hours_left', 'yes_mid', 'no_ask', 'no_depth_0p3c',
            'usd_0p3c', 'roi_if_no_touch', 'breakeven_touch_prob', 'x_sigma', 'market']
    print('\t'.join(cols))
    for d in res:
        print('\t'.join(str(d[c]) for c in cols))
    if a.json:
        json.dump(res, open(a.json, 'w'), indent=1)


if __name__ == '__main__':
    main()
