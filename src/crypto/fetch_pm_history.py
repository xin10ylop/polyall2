"""Fetch Polymarket CLOB price history (YES token, midpoint series) and taker trades per market.

prices-history: full life at fidelity=15min + last 26h before expiry at fidelity=1min.
trades: data-api v2 /trades?condition=... (taker rows only, cursor paginated).
Stored in shards of 200 markets: data/crypto/ph/<series>/ph_XXXX.parquet, tr_XXXX.parquet
Usage: python fetch_pm_history.py <series_slug> [--kinds above,range] [--since 2025-08-01] [--no-trades] [--sample N]
"""
import sys, argparse, concurrent.futures as cf
import numpy as np, pandas as pd
from common import DATA, CLOB, DAPI, get_json

CHUNK = 200


def price_history(tok, t_start, t_end, fine_fid=1, fine_hours=26):
    out = []
    # coarse whole life (API caps window length for fine fidelity -> chunk by 7 days)
    a = int(t_start) - 3600 if not FINE.get('only_fine') else int(t_end) + 1
    while a < t_end:
        b = min(a + 7 * 86400, int(t_end) + 3600)
        r = get_json(f'{CLOB}/prices-history', params={'market': tok, 'startTs': a, 'endTs': b, 'fidelity': 15})
        if r and r.get('history'):
            out += [(x['t'], x['p'], 15) for x in r['history']]
        a = b
    # fine last 26h
    if fine_hours > 0:
        a = int(t_end) - int(fine_hours * 3600)
        b = int(t_end) + 1800
        r = get_json(f'{CLOB}/prices-history', params={'market': tok, 'startTs': a, 'endTs': b, 'fidelity': fine_fid})
        if r and r.get('history'):
            out += [(x['t'], x['p'], 1) for x in r['history']]
    return out


def trades(cid, max_pages=200):
    rows, cur, pages = [], None, 0
    while True:
        p = {'condition': cid, 'limit': 1000} if not cur else {'condition': cid, 'cursor': cur}
        r = get_json(f'{DAPI}/v2/trades', params=p)
        if not r:
            break
        for x in r.get('data') or []:
            rows.append((x['timestamp'], x['token_id'], 1 if x['side'] == 'BUY' else -1, x['price'], x['size']))
        cur = (r.get('pagination') or {}).get('next_cursor')
        pages += 1
        if not cur or pages >= max_pages:
            break
    return rows


FINE = {'fid': 1, 'hours': 26}


def work(m, do_trades):
    t0 = m['m_start'].timestamp() if pd.notna(m['m_start']) else m['event_start'].timestamp()
    t1 = m['event_end'].timestamp()
    ph = price_history(m['tok_yes'], t0, t1, FINE['fid'], FINE['hours'])
    tr = trades(m['condition_id']) if do_trades else []
    return m['condition_id'], m['tok_yes'], ph, tr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('series')
    ap.add_argument('--kinds', default='above,range,touch_up,touch_down,updown')
    ap.add_argument('--since', default='2025-01-01')
    ap.add_argument('--until', default=None)
    ap.add_argument('--no-trades', action='store_true')
    ap.add_argument('--sample', type=int, default=0, help='sample N events (deterministic)')
    ap.add_argument('--slug-prefix', default=None)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--fine-fid', type=int, default=1)
    ap.add_argument('--fine-hours', type=float, default=26)
    ap.add_argument('--only-fine', action='store_true', help='skip the coarse whole-life history')
    a = ap.parse_args()
    FINE['fid'] = a.fine_fid; FINE['hours'] = a.fine_hours; FINE['only_fine'] = a.only_fine
    df = pd.read_parquet(DATA / f'markets_{a.series}.parquet')
    df = df[df.kind.isin(a.kinds.split(',')) & df.closed & df.res_yes.notna()]
    df = df[df.event_end >= pd.Timestamp(a.since, tz='UTC')]
    if a.until:
        df = df[df.event_end < pd.Timestamp(a.until, tz='UTC')]
    if a.slug_prefix:
        df = df[df.event_slug.str.startswith(a.slug_prefix)]
    if a.sample:
        ev = sorted(df.event_id.unique())
        rng = np.random.default_rng(0)
        keep = set(rng.choice(ev, size=min(a.sample, len(ev)), replace=False))
        df = df[df.event_id.isin(keep)]
    df = df.sort_values(['event_end', 'condition_id']).reset_index(drop=True)
    outdir = DATA / 'ph' / a.series
    outdir.mkdir(parents=True, exist_ok=True)
    tok_map = dict(zip(df.tok_yes, df.tok_no))
    print(a.series, 'markets to fetch', len(df), flush=True)
    for ci in range(0, len(df), CHUNK):
        fn = outdir / f'ph_{ci // CHUNK:04d}.parquet'
        if fn.exists():
            continue
        sub = df.iloc[ci:ci + CHUNK]
        ph_rows, tr_rows = [], []
        with cf.ThreadPoolExecutor(a.workers) as ex:
            for cid, tok, ph, tr in ex.map(lambda r: work(r, not a.no_trades), [r for _, r in sub.iterrows()]):
                ph_rows += [(cid, t, p, f) for t, p, f in ph]
                for (t, token, side, px, sz) in tr:
                    tr_rows.append((cid, t, 1 if token == tok else 0, side, px, sz))
        ph_df = pd.DataFrame(ph_rows, columns=['cid', 't', 'p', 'fid'])
        ph_df = ph_df.astype({'t': 'int64', 'p': 'float32', 'fid': 'int8'})
        tr_df = pd.DataFrame(tr_rows, columns=['cid', 't', 'is_yes', 'side', 'price', 'size'])
        tr_df = tr_df.astype({'t': 'int64', 'is_yes': 'int8', 'side': 'int8', 'price': 'float32', 'size': 'float32'})
        tr_df.to_parquet(outdir / f'tr_{ci // CHUNK:04d}.parquet', compression='zstd')
        ph_df.to_parquet(fn, compression='zstd')
        print(a.series, 'chunk', ci // CHUNK, len(sub), 'ph', len(ph_df), 'tr', len(tr_df), flush=True)


if __name__ == '__main__':
    main()
