"""Flatten raw gamma events into compact market tables (one row per binary market).
Output: data/crypto/markets_<series_slug>.parquet
"""
import json, re, sys
import pandas as pd
from common import DATA, load_json_gz

ASSET_MAP = {'btc': 'BTC', 'bitcoin': 'BTC', 'eth': 'ETH', 'ethereum': 'ETH', 'solana': 'SOL', 'sol': 'SOL',
             'xrp': 'XRP'}


def num(s):
    s = s.replace(',', '').replace('$', '').strip()
    mult = 1
    if s.lower().endswith('k'):
        mult, s = 1000, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def parse_event(e, series_slug):
    rows = []
    asset = ASSET_MAP.get(series_slug.split('-')[0])
    for m in e.get('markets', []):
        try:
            toks = json.loads(m.get('clobTokenIds') or '[]')
            outs = json.loads(m.get('outcomes') or '[]')
            px = json.loads(m.get('outcomePrices') or '[]')
        except Exception:
            continue
        if len(toks) != 2:
            continue
        git = (m.get('groupItemTitle') or '').strip().replace('–', '-').replace('—', '-')
        q = m.get('question') or ''
        ql = q.lower()
        kind, k1, k2 = None, None, None
        mq = re.search(r'\$([\d,\.]+k?)', q, re.I)
        if git.startswith('↑') or git.startswith('↓'):
            pass
        elif (' reach ' in ql or ' hit ' in ql) and mq and 'above' not in ql:
            git = '↑' + mq.group(1)
        elif (' dip ' in ql or ' fall ' in ql or ' drop ' in ql) and mq:
            git = '↓' + mq.group(1)
        if git.startswith('↑'):
            kind, k1 = 'touch_up', num(git[1:])
        elif git.startswith('↓'):
            kind, k1 = 'touch_down', num(git[1:])
        elif git.startswith('<'):
            kind, k2 = 'range', num(git[1:])
        elif git.startswith('>'):
            kind, k1 = 'range', num(git[1:])
        elif re.match(r'^\$?[\d,\.]+k?\s*-\s*\$?[\d,\.]+k?$', git, re.I):
            a, b = git.split('-')
            if b.strip().lower().endswith('k') and not a.strip().lower().endswith('k'):
                a = a + 'k'
            kind, k1, k2 = 'range', num(a), num(b)
        elif re.match(r'^[\d,\.]+k?$', git.replace('$', '')):
            kind, k1 = 'above', num(git)
        elif 'up or down' in q.lower():
            kind = 'updown'
        else:
            mm = re.search(r'above \$?([\d,\.]+k?)', q)
            if mm:
                kind, k1 = 'above', num(mm.group(1))
        if asset == 'BTC':
            k1 = k1 * 1000 if (k1 is not None and k1 < 1000) else k1
            k2 = k2 * 1000 if (k2 is not None and k2 < 1000) else k2
        res = None
        if len(px) == 2 and m.get('closed'):
            try:
                p0 = float(px[0])
                res = 1.0 if p0 > 0.99 else (0.0 if p0 < 0.01 else None)
            except ValueError:
                pass
        rows.append(dict(
            series=series_slug, asset=asset, event_id=e['id'], event_slug=e['slug'], event_title=e.get('title'),
            event_start=e.get('startDate'), event_end=e.get('endDate'), neg_risk=bool(e.get('negRisk')),
            market_id=m['id'], question=q, slug=m.get('slug'), condition_id=m.get('conditionId'),
            tok_yes=toks[0], tok_no=toks[1], out0=outs[0] if outs else None, out1=outs[1] if len(outs) > 1 else None,
            git=git, kind=kind, k1=k1, k2=k2, m_start=m.get('startDate'), m_end=m.get('endDate'),
            m_created=m.get('createdAt'), closed_time=m.get('closedTime'), closed=bool(m.get('closed')),
            res_yes=res, volume=float(m.get('volume') or 0), fees_enabled=bool(m.get('feesEnabled')),
            fee_rate=(m.get('feeSchedule') or {}).get('rate'), tick=m.get('orderPriceMinTickSize'),
            uma_status=m.get('umaResolutionStatus'),
            desc=(m.get('description') or '')[:700],
        ))
    return rows


def run(series_slug):
    ev = load_json_gz(DATA / 'events' / f'{series_slug}.json.gz')
    rows = []
    for e in ev:
        rows += parse_event(e, series_slug)
    df = pd.DataFrame(rows)
    for c in ['event_start', 'event_end', 'm_start', 'm_end', 'm_created', 'closed_time']:
        df[c] = pd.to_datetime(df[c], utc=True, errors='coerce', format='mixed')
    df.to_parquet(DATA / f'markets_{series_slug}.parquet', compression='zstd')
    print(series_slug, len(ev), 'events', len(df), 'markets', df.kind.value_counts().to_dict(), flush=True)
    return df


if __name__ == '__main__':
    import glob, os
    names = sys.argv[1:] or [os.path.basename(p).replace('.json.gz', '') for p in glob.glob(str(DATA / 'events' / '*.json.gz'))]
    for n in names:
        run(n)
