#!/usr/bin/env python3
"""Out-of-time forward replay of the frozen daily-barrier longshot sale (research/04 §8, rules frozen 2026-09-26).

Replays the rule on daily "What price will <Bitcoin|Ethereum|Solana|XRP> hit on <date>?" events whose window has
ended and resolved, using only public data fetched after the fact. The rule is the one barrier_study.py applies
to the panels built by analyze_touch.make_panel. This file ports make_panel's per-market loop, with the decision
grid as a parameter, and reuses window_start / fit_models / Features / scale / yes_equiv / parse_event /
fetch_pm_history.price_history+trades / barrier_study.select+add_pnl+calibrate_cost:
  * strike not yet touched: no Binance 1m high >= H (up) / low <= H (down) in [W0, t)
  * 0 < W1 - t <= 12 h, t < W1 - 30 min, YES mid = last prices-history point <= t, at most 1 h stale
  * 0.005 <= mid < 0.03 on the float32 mid, exactly as the study stored it. In effect a mid of exactly 3.0c
    counts and one of exactly 0.5c does not (--mid-rule doc applies the band to float64 mids instead)
  * buy NO; fills 'mid' = 1 - mid + 0.3c; 'real' = first taker NO-buy/YES-sell print in (t+60 s, t+15 min],
    falling back to 'mid' when there is none. The taker fee 0.07 p (1-p) per share is always charged.
    Also 'real_cal' = the §8.1 convention (real print, else the H1-calibrated cost).
  * one entry per strike = its first qualifying decision (the study's "one trade per strike"). The pre-registered
    filter x >= 4.25 comes AFTER that dedupe: a strike whose first eligible decision has x < 4.25 is skipped and
    never re-entered. That ordering reproduces §8.2's 4,403-trade figure.
  * x = |ln(H/S_t)| / s, where s is the walk-forward Student-t scale (combo spec for BTC/ETH, rv for SOL/XRP, as in
    barrier_panels.py). The t-model parameters are frozen at the 2026-09 fit (training windows ending before
    2026-09-01), which is the model the rule was frozen with. The features (RV EWMAs, DVOL, seasonality) are
    computed at t from Binance/Deribit data as usual.

Decision grids: 'study' = W1 - {12,6,3,1} h (the backtest panel grid; mid from the 5-min prices-history series,
as fetched for the study). 'bot10m' = every 10 min from W1-12h to W1-40min (the bot's cycle; mid from the
1-min series). The bot10m grid contains the study grid.

Cache, under data/crypto/forward/ (fetched once, after each window has ended; reruns only fetch what is new):
  events/<series>.json.gz   gamma events (closed=true)
  pm/<cid>.json.gz          YES prices-history (fidelity 1 and 5) over [W1-13h, W1+30min] + all data-api taker trades
  spot/<SYM>_1m.parquet     Binance 1m klines after the end of data/crypto/spot/<SYM>_1m.parquet
  spot/DVOL_<CUR>.parquet   Deribit DVOL hourly after the end of data/crypto/spot/DVOL_<CUR>.parquet
  model_params.json         frozen t-model parameters
  rows/<grid>/<event>.parquet  decision rows per fully resolved event (reused on later runs; --rebuild recomputes)
Outputs: forward_<grid>.csv (default window) or replay_<grid>_<since>_<until>.csv, plus a printed summary.

Usage:
  python3 src/crypto/forward_replay.py                          # windows ending 2026-09-26 00:00 UTC -> now
  python3 src/crypto/forward_replay.py --since 2026-09-11 --until 2026-09-16 --validate   # ET days 09-10..09-14 vs backtest
"""
import sys, json, time, argparse, concurrent.futures as cf
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from common import DATA, GAMMA, get_json, save_json_gz, load_json_gz, to_unix
import volmodel
from volmodel import Features, SYMS, scale
from analyze_touch import window_start, fit_models, H_TOUCH, extreme_train
from panel import yes_equiv
from parse_markets import parse_event
from fetch_events import SERIES as SERIES_SLUG
from barrier_signals import SERIES as SIG_SERIES, BINANCE
import fetch_pm_history as fph
import barrier_study as bs

FWD = DATA / 'forward'
FREEZE = pd.Timestamp('2026-09-26', tz='UTC')                    # study sample = windows ending before this
FREEZE_COMMIT = pd.Timestamp('2026-09-26T18:25:37', tz='UTC')    # commit 6550f98 (rule + x filter frozen)
MIN_X = 4.25
MODEL_MONTH = '2026-09'
SPEC = {'BTC': 'combo', 'ETH': 'combo', 'SOL': 'rv', 'XRP': 'rv'}   # barrier_panels.py
DAILY = {sid: a for sid, (a, fam) in SIG_SERIES.items() if fam == 'daily'}   # 10200 BTC, 11297 ETH, 11298 SOL, 11299 XRP
GRIDS = {'study': ([W * 3600 for W in (12, 6, 3, 1)], 5),       # (seconds before W1, prices-history fidelity)
         'bot10m': ([k * 600 for k in range(72, 2, -1)], 1)}
PH_HOURS = 13
TRAIN_EXTREME = [DATA, Path('/tmp/claude-0/-home-user-polyall2/23837d40-49ff-5c90-86c9-24d18e8ba96d/scratchpad')]  # make_panel's locations
fph.FINE['only_fine'] = True   # price_history(): skip the coarse whole-life pass


def ts(s):
    t = pd.Timestamp(s)
    return int((t.tz_localize('UTC') if t.tzinfo is None else t).timestamp())


# ------------------------------------------------------------------ fetching (cached, idempotent)
def list_events(sid, since):
    """Closed events of a series, newest first, until endDate < since. Merged into the cache."""
    path = FWD / 'events' / f'{SERIES_SLUG[sid]}.json.gz'
    cache = {e['id']: e for e in load_json_gz(path)} if path.exists() else {}
    cur = None
    while True:
        p = {'series_id': sid, 'limit': 100, 'closed': 'true', 'order': 'endDate', 'ascending': 'false'}
        if cur:
            p['after_cursor'] = cur
        r = get_json(f'{GAMMA}/events/keyset', params=p) or {}
        evs = r.get('events') or []
        for e in evs:
            cache[e['id']] = e
        cur = r.get('next_cursor')
        if not evs or not cur or min(ts(e['endDate']) for e in evs if e.get('endDate')) < since:
            break
    save_json_gz(list(cache.values()), path)
    return list(cache.values())


def market_table(since, until):
    out = []
    for sid, asset in DAILY.items():
        slug = SERIES_SLUG[sid]
        for e in list_events(sid, since):
            if e.get('endDate') and since <= ts(e['endDate']) < until:
                out += parse_event(e, slug)
    mk = pd.DataFrame(out)
    for c in ['event_start', 'event_end', 'm_start', 'm_end', 'm_created', 'closed_time']:
        mk[c] = pd.to_datetime(mk[c], utc=True, errors='coerce', format='mixed')
    mk = mk[mk.kind.isin(['touch_up', 'touch_down'])].reset_index(drop=True)
    return mk


def pm_path(cid):
    return FWD / 'pm' / f'{cid}.json.gz'


def fetch_market(m):
    """YES prices-history (fid 1 and 5) over [W1-13h, W1+30min] + all taker trades. Fetched once after W1+30min."""
    path = pm_path(m['condition_id'])
    if path.exists():
        return 'cached'
    W1 = int(m['event_end'].timestamp())
    if time.time() < W1 + 1800:
        return 'not-ended'
    try:
        # empty history is a real answer (strike touched and closed before W1-13h); transport failures raise
        ph1 = fph.price_history(m['tok_yes'], W1, W1, fine_fid=1, fine_hours=PH_HOURS)
        ph5 = fph.price_history(m['tok_yes'], W1, W1, fine_fid=5, fine_hours=PH_HOURS)
        tr = fph.trades(m['condition_id'])
    except Exception as exn:  # connection drops beyond get_json's retries -> not cached, retried next run
        return f'error {exn!r}'[:120]
    save_json_gz({'cid': m['condition_id'], 'tok_yes': m['tok_yes'], 'W1': W1, 'fetched_at': int(time.time()),
                  'ph1': [[t, p] for t, p, _ in ph1], 'ph5': [[t, p] for t, p, _ in ph5], 'trades': tr}, path)
    return 'fetched'


def fetch_spot_tail(asset):
    """Binance 1m klines after the end of the study's spot file (closed candles only), appended to the cache."""
    sym = SYMS[asset]
    main_end = int(pd.read_parquet(DATA / 'spot' / f'{sym}_1m.parquet', columns=['ts']).ts.max())
    path = FWD / 'spot' / f'{sym}_1m.parquet'
    old = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=['ts', 'h', 'l', 'c'])
    last = max(main_end, int(old.ts.max()) if len(old) else 0)
    now = int(time.time())
    rows = []
    while last + 120 <= now:
        r = get_json(BINANCE, params={'symbol': sym, 'interval': '1m', 'startTime': (last + 60) * 1000, 'limit': 1000})
        if not r:
            break
        new = [(x[0] // 1000, float(x[2]), float(x[3]), float(x[4])) for x in r if x[0] // 1000 + 60 <= now]
        if not new:
            break
        rows += new
        last = new[-1][0]
        if len(r) < 1000:
            break
    if rows:
        df = pd.concat([old, pd.DataFrame(rows, columns=['ts', 'h', 'l', 'c'])], ignore_index=True)
        df = df.drop_duplicates('ts').sort_values('ts').astype({'ts': 'int64', 'h': 'float64', 'l': 'float64', 'c': 'float64'})
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, compression='zstd')
    return main_end


def fetch_dvol_tail(cur):
    main = pd.read_parquet(DATA / 'spot' / f'DVOL_{cur}.parquet')
    path = FWD / 'spot' / f'DVOL_{cur}.parquet'
    old = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=['ts', 'o', 'h', 'l', 'c'])
    last = max(int(main.ts.max()), int(old.ts.max()) if len(old) else 0)
    if time.time() - last < 7200:
        return
    rows, end = [], int(time.time() * 1000)
    while True:
        r = get_json('https://www.deribit.com/api/v2/public/get_volatility_index_data',
                     params={'currency': cur, 'start_timestamp': (last + 3600) * 1000, 'end_timestamp': end, 'resolution': 3600})
        res = (r or {}).get('result') or {}
        data = res.get('data') or []
        rows += data
        cont = res.get('continuation')
        if not data or not cont or cont <= (last + 3600) * 1000:
            break
        end = cont
    if rows:
        new = pd.DataFrame(rows, columns=['ts', 'o', 'h', 'l', 'c'])
        new['ts'] = new.ts // 1000
        df = pd.concat([old, new], ignore_index=True).drop_duplicates('ts').sort_values('ts').reset_index(drop=True)
        df['ts'] = df.ts.astype('int64')
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)


def install_market_data(asset, extend):
    """Put the (optionally extended) Binance 1m series and DVOL into volmodel's cache, same format as load_spot/load_dvol.
    extend=False keeps exactly the study's inputs (needed to reproduce its x, since rv_series clips at a percentile
    of the whole monthly slice)."""
    sym = SYMS[asset]
    df = pd.read_parquet(DATA / 'spot' / f'{sym}_1m.parquet')
    fp = FWD / 'spot' / f'{sym}_1m.parquet'
    if extend and fp.exists():
        tail = pd.read_parquet(fp)
        df = pd.concat([df, tail[tail.ts > df.ts.max()]], ignore_index=True)
    grid = np.arange(df.ts.min(), df.ts.max() + 60, 60)
    df = df.set_index('ts').reindex(grid)
    df['c'] = df['c'].ffill()
    for col in ['h', 'l']:
        df[col] = df[col].fillna(df['c'])
    volmodel._cache[('spot', asset)] = df
    for cur in ('BTC', 'ETH'):
        d = pd.read_parquet(DATA / 'spot' / f'DVOL_{cur}.parquet')
        fp = FWD / 'spot' / f'DVOL_{cur}.parquet'
        if extend and fp.exists():
            tail = pd.read_parquet(fp)
            d = pd.concat([d, tail[tail.ts > d.ts.max()]], ignore_index=True)
        volmodel._cache[('dvol', cur)] = d.set_index('ts')['c']
    return df


# ------------------------------------------------------------------ frozen t-model
def model_params():
    path = FWD / 'model_params.json'
    P = json.load(open(path)) if path.exists() else {}
    need = sorted({int(h) for h in H_TOUCH if h <= 12})
    changed = False
    for a in SPEC:
        if a in P:
            continue
        src = next((d / f'train_extreme_{a}.parquet' for d in TRAIN_EXTREME if (d / f'train_extreme_{a}.parquet').exists()), None)
        if src is not None:
            tr = pd.read_parquet(src)
        else:   # rebuild from the study's spot file (training rows are cut at the month start anyway)
            install_market_data(a, extend=False)
            tr = extreme_train(a, Features(a), hs=need)
        fm = fit_models(tr[tr.h.isin(need)], [MODEL_MONTH], SPEC[a])
        P[a] = {str(h): {'spec': prm['spec'], 'beta': [float(b) for b in prm['beta']], 'nu': float(prm['nu']), 'n': int(prm['n'])}
                for (m, h), (prm, z) in fm.items()}
        changed = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        json.dump(P, open(path, 'w'), indent=1)
    return {a: {int(h): {**v, 'beta': np.array(v['beta'])} for h, v in d.items()} for a, d in P.items()}


# ------------------------------------------------------------------ panel rows (port of analyze_touch.make_panel's loop)
def build_rows(mk, asset, grid, F, params):
    offsets, fid = GRIDS[grid]
    spot = F.spot
    mk = mk.copy()
    mk['W0'] = [window_start(r) for _, r in mk.iterrows()]
    mk['W0'] = to_unix(pd.to_datetime(mk.W0, utc=True))
    mk['W1'] = to_unix(mk.event_end)
    mk['t_open'] = to_unix(mk.m_start.fillna(mk.m_created))
    rows = []
    for m in mk.itertuples():
        pm = load_json_gz(pm_path(m.condition_id))
        g = pd.DataFrame(pm[f'ph{fid}'], columns=['t', 'p'])
        if not len(g):
            continue
        g['p64'] = g.p.astype('float64')
        g = g.astype({'t': 'int64', 'p': 'float32'}).sort_values('t')
        tr = pd.DataFrame([(m.condition_id, t, 1 if tok == m.tok_yes else 0, side, px, sz) for t, tok, side, px, sz in pm['trades']],
                          columns=['cid', 't', 'is_yes', 'side', 'price', 'size'])
        tr = tr.astype({'t': 'int64', 'is_yes': 'int8', 'side': 'int8', 'price': 'float32', 'size': 'float32'})
        trg = yes_equiv(tr).sort_values('t') if len(tr) else None
        H = m.k1
        up = m.kind == 'touch_up'
        W0, W1 = int(m.W0) // 60 * 60, int(m.W1)
        seg = spot.loc[W0: W1 - 60]
        if len(seg) == 0:
            continue
        y_bin = float((seg.h.max() >= H) if up else (seg.l.min() <= H))
        hit_idx = np.where(seg.h.values >= H)[0] if up else np.where(seg.l.values <= H)[0]
        t_hit = int(seg.index.values[hit_idx[0]]) if len(hit_idx) else None
        for t in sorted({W1 - s for s in offsets}):
            if t <= max(W0, m.t_open) + 1800 or t >= W1 - 1800:
                continue
            if t_hit is not None and t_hit < t:
                continue
            i = np.searchsorted(g.t.values, t, side='right') - 1
            if i < 0 or t - g.t.values[i] > 3600:
                continue
            row = dict(cid=m.condition_id, series=m.series, asset=asset, event_slug=m.event_slug, slug=m.slug, kind=m.kind, H=H,
                       W0=W0, W1=W1, t=t, tau_h=(W1 - t) / 3600, mid=float(g.p.values[i]), mid64=float(g.p64.values[i]),
                       stale=t - int(g.t.values[i]), y=m.res_yes, y_bin=y_bin, bid_slow=np.nan)
            if trg is not None and len(trg):
                tt = trg.t.values
                a2 = np.searchsorted(tt, t + 60, side='right'); b2 = np.searchsorted(tt, t + 900, side='right')
                w2 = trg.iloc[a2:b2]
                sy2 = w2[w2.dir == -1]
                row['bid_slow'] = float(sy2.px.iloc[0]) if len(sy2) else np.nan
            rows.append(row)
    pn = pd.DataFrame(rows)
    if not len(pn):
        return pn
    ft = F.build(pn.t.values, pn.W1.values - 60)
    for c in ['S_t', 'tau_min', 'seas', 'rv6h', 'rv24h', 'rv168h', 'dvol']:
        pn[c] = ft[c].values
    hs = np.array(H_TOUCH)
    pn['h_fit'] = hs[np.argmin(np.abs(np.log(hs)[None, :] - np.log(pn.tau_h.values)[:, None]), axis=1)]
    pn['x'] = np.nan
    for h, idx in pn.groupby('h_fit').groups.items():
        sub = pn.loc[idx]
        pn.loc[idx, 'x'] = np.abs(np.log(sub.H.values / sub.S_t.values)) / scale(params[asset][int(h)], sub)
    return pn


def event_rows(mk, grid, params, spot_end, rebuild=False):
    """Rows for every fully fetched + resolved event, cached per event."""
    out, pending, todo = [], [], []
    for ev, g in mk.groupby('event_slug'):
        p = FWD / 'rows' / grid / f'{ev}.parquet'
        if p.exists() and not rebuild:
            out.append(pd.read_parquet(p)); continue
        if g.res_yes.isna().any():
            pending.append((ev, f'{int(g.res_yes.isna().sum())} unresolved strikes')); continue
        if not all(pm_path(c).exists() for c in g.condition_id):
            pending.append((ev, 'price/trade data missing')); continue
        todo.append(ev)
    if todo:
        sub = mk[mk.event_slug.isin(todo)]
        W1max = int(sub.event_end.max().timestamp())
        for asset, ga in sub.groupby('asset'):
            extend = W1max - 60 > spot_end[asset]
            spot = install_market_data(asset, extend)
            if int(spot.index.max()) < W1max - 60:
                pending += [(ev, 'spot data does not cover window') for ev in ga.event_slug.unique()]; continue
            pn = build_rows(ga, asset, grid, Features(asset), params)
            for ev in ga.event_slug.unique():
                e = pn[pn.event_slug == ev] if len(pn) else pn
                p = FWD / 'rows' / grid / f'{ev}.parquet'
                p.parent.mkdir(parents=True, exist_ok=True)
                e.to_parquet(p)
                out.append(e)
    out = [d for d in out if len(d)]
    return (pd.concat(out, ignore_index=True) if out else pd.DataFrame()), pending


# ------------------------------------------------------------------ rule, fills, PnL (barrier_study)
_CAL = {}


def add_cal(d):
    """'real_cal' = the §8.1 convention: real print, else barrier_study's H1-calibrated cost (calibrate_cost)."""
    if not _CAL:
        _CAL.update(bs.calibrate_cost(bs.load()))
    bs.COST.clear(); bs.COST.update(_CAL)
    try:
        c = bs.add_pnl(d[['mid', 'asset', 'fam', 'bid_slow', 'y']], 'A')
    finally:
        bs.COST.clear()   # back to the default 0.3c mid cost
    d = d.copy()
    d['px_real_cal'], d['pnl_real_cal'], d['roi_real_cal'] = c.px_real.values, c.pnl_real.values, c.roi_real.values
    return d


def select_rows(pn, mid_rule='study'):
    """barrier_study.load() filters + select(pn, 'A') (0 < tau <= 12 h, 0.005 <= mid < 0.03). Returns (all rows, first per strike)."""
    if not len(pn):
        return pn, pn
    bad = pn.event_slug.str.contains('before-|hit-in-20\\d\\d$', regex=True)
    pn = pn[~bad & (pn.stale <= 3600) & (pn.H > 0)].copy()
    pn['fam'] = 'daily'
    if mid_rule == 'doc':
        pn['mid'] = pn['mid64']
    bs.COST.clear()
    d = add_cal(bs.select(pn, 'A'))   # 'mid' = 1 - mid + 0.3c, 'real' = print else 'mid'; fee 0.07 p(1-p)
    first = d.sort_values('t').groupby('cid').head(1).copy()
    first['x_pass'] = first.x >= MIN_X
    return d, first


OUTCOLS = ['asset', 'event_day', 'event_slug', 'slug', 'strike', 'side', 'decision_utc', 'hours_left', 'yes_mid', 'stale_s',
           'spot', 'x', 'x_pass', 'px_mid', 'px_real', 'has_real', 'real_print_no_px', 'outcome_yes', 'binance_touch',
           'roi_mid', 'roi_real', 'roi_real_cal', 'pnl_mid_per_share', 'pnl_real_per_share', 'pre_freeze', 'cid']


def to_output(first):
    o = pd.DataFrame({
        'asset': first.asset.values,
        'event_day': [(pd.Timestamp(w, unit='s', tz='UTC').tz_convert('America/New_York') - pd.Timedelta(days=1)).strftime('%Y-%m-%d') for w in first.W1],
        'event_slug': first.event_slug.values, 'slug': first.slug.values, 'strike': first.H.values,
        'side': np.where(first.kind == 'touch_up', 'up', 'down'),
        'decision_utc': pd.to_datetime(first.t, unit='s', utc=True).dt.strftime('%Y-%m-%d %H:%M').values,
        'hours_left': first.tau_h.round(3).values, 'yes_mid': first.mid.round(6).values, 'stale_s': first.stale.values,
        'spot': first.S_t.values, 'x': first.x.round(3).values, 'x_pass': first.x_pass.values,
        'px_mid': first.px_mid.round(6).values, 'px_real': first.px_real.round(6).values, 'has_real': first.has_real.values,
        'real_print_no_px': (1 - first.bid_slow).round(6).values, 'outcome_yes': first.y.values, 'binance_touch': first.y_bin.values,
        'roi_mid': first.roi_mid.values, 'roi_real': first.roi_real.values, 'roi_real_cal': first.roi_real_cal.values,
        'pnl_mid_per_share': first.pnl_mid.values, 'pnl_real_per_share': first.pnl_real.values,
        'pre_freeze': first.t.values < FREEZE_COMMIT.timestamp(), 'cid': first.cid.values})
    return o.sort_values(['event_day', 'asset', 'decision_utc', 'strike']).reset_index(drop=True)


def summary(o):
    lines = []
    for flt, d in (('none', o), (f'x>={MIN_X}', o[o.x_pass])):
        for a, g in list(d.groupby('asset')) + [('ALL', d)]:
            lines.append(dict(filter=flt, asset=a, trades=len(g), wins=int((g.outcome_yes == 0).sum()), losses=int((g.outcome_yes == 1).sum()),
                              real_share=round(g.has_real.mean(), 3) if len(g) else np.nan,
                              mean_pnl_mid_pct=round(100 * g.roi_mid.mean(), 3) if len(g) else np.nan,
                              mean_pnl_real_pct=round(100 * g.roi_real.mean(), 3) if len(g) else np.nan,
                              mean_pnl_real_cal_pct=round(100 * g.roi_real_cal.mean(), 3) if len(g) else np.nan,
                              sum_pnl_real_per_1usd=round(g.roi_real.sum(), 4)))
    return pd.DataFrame(lines)


# ------------------------------------------------------------------ validation vs the backtest
def validate(d_all, first, slugs):
    pn = bs.load()
    bs.COST.clear()
    ref = add_cal(bs.select(pn[pn.event_slug.isin(slugs)], 'A'))
    ref_first = ref.sort_values('t').groupby('cid').head(1).copy()
    ref_first['x_pass'] = ref_first.x >= MIN_X
    fields = ['mid', 'x', 'bid_slow', 'y', 'px_mid', 'px_real', 'roi_mid', 'roi_real', 'roi_real_cal']
    tol = {'x': 1e-6}
    print('\n== VALIDATION vs barrier_study (events:', len(slugs), ')')
    for lab, a, b, key in (('eligible rows', ref, d_all, ['cid', 't']), ('first per strike', ref_first, first, ['cid'])):
        m = a.merge(b, on=key, how='outer', suffixes=('_bt', '_fw'), indicator=True)
        both = m[m._merge == 'both']
        print(f'{lab}: backtest {len(a)}, replay {len(b)}, matched keys {len(both)}, backtest-only {int((m._merge == "left_only").sum())}, '
              f'replay-only {int((m._merge == "right_only").sum())}')
        bad_any = np.zeros(len(both), bool)
        for f in fields:
            x1, x2 = both[f'{f}_bt'].values.astype(float), both[f'{f}_fw'].values.astype(float)
            ok = (np.isnan(x1) & np.isnan(x2)) | (np.abs(x1 - x2) <= tol.get(f, 1e-9))
            bad_any |= ~ok
            if (~ok).any():
                print(f'   field {f}: {int((~ok).sum())} mismatches, max |diff| {np.nanmax(np.abs(x1 - x2)[~ok]):.3g}')
        if key == ['cid']:
            both = both.assign(t_diff=both.t_bt != both.t_fw)
            print(f'   decision time differs: {int(both.t_diff.sum())}')
            bad_any |= both.t_diff.values
        print(f'   exact match (all fields): {int((~bad_any).sum())}/{len(m)} = {100 * (~bad_any).sum() / max(len(m), 1):.1f}%')
        for _, r in m[m._merge != 'both'].head(15).iterrows():
            src = '_bt' if r._merge == 'left_only' else '_fw'
            print(f'   {r._merge}: {r.get("slug" + src, r.get("slug"))} t={pd.Timestamp(r.t if "t" in r else r["t" + src], unit="s")} '
                  f'mid={r["mid" + src]:.4f} x={r["x" + src]:.2f} y={r["y" + src]}')
    for lab, g in (('backtest', ref_first), ('replay', first)):
        f = g[g.x_pass]
        print(f'   {lab}: strikes {len(g)} losses {int(g.y.sum())} mean ROI mid {100 * g.roi_mid.mean():+.3f}% real {100 * g.roi_real.mean():+.3f}% '
              f'| x>={MIN_X}: {len(f)} strikes, {int(f.y.sum())} losses, real {100 * f.roi_real.mean():+.3f}%')
    return ref, ref_first


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default=str(FREEZE.date()), help='include windows ending at/after this UTC time')
    ap.add_argument('--until', default=None, help='... and before this UTC time (default: now)')
    ap.add_argument('--grids', default='study,bot10m')
    ap.add_argument('--mid-rule', default='study', choices=['study', 'doc'])
    ap.add_argument('--validate', action='store_true', help='compare the study grid with barrier_study on the same events')
    ap.add_argument('--rebuild', action='store_true', help='recompute cached decision rows')
    ap.add_argument('--workers', type=int, default=6)
    a = ap.parse_args()
    since = ts(a.since)
    until = ts(a.until) if a.until else int(time.time())
    default_window = a.until is None and a.since == str(FREEZE.date())
    pd.set_option('display.width', 250); pd.set_option('display.max_columns', 40)

    mk = market_table(since, until)
    print(f'events {mk.event_slug.nunique()} ({mk.groupby("asset").event_slug.nunique().to_dict()}), strikes {len(mk)}, '
          f'unresolved strikes {int(mk.res_yes.isna().sum())}', flush=True)
    todo = [r for _, r in mk.iterrows() if not pm_path(r.condition_id).exists()]
    if todo:
        with cf.ThreadPoolExecutor(a.workers) as ex:
            res = list(ex.map(fetch_market, todo))
        print('market data:', pd.Series(res).str.split(' ').str[0].value_counts().to_dict(), flush=True)
        for r, s in zip(todo, res):
            if s.startswith(('error', 'empty')):
                print('  ', r.slug, s)
    spot_end = {}
    for asset in SPEC:
        spot_end[asset] = fetch_spot_tail(asset)
    for cur in ('BTC', 'ETH'):
        fetch_dvol_tail(cur)
    params = model_params()

    for grid in a.grids.split(','):
        pn, pending = event_rows(mk, grid, params, spot_end, rebuild=a.rebuild)
        for ev, why in sorted(set(pending)):
            print(f'  [{grid}] skipped {ev}: {why}')
        d_all, first = select_rows(pn, a.mid_rule)
        if not len(first):
            print(f'[{grid}] no qualifying trades'); continue
        o = to_output(first)
        name = f'forward_{grid}.csv' if default_window else f'replay_{grid}_{a.since[:10]}_{(a.until or "now")[:10]}.csv'
        if a.mid_rule != 'study':
            name = name.replace('.csv', f'_{a.mid_rule}.csv')
        o.to_csv(FWD / name, index=False)
        mis = int((o.outcome_yes != o.binance_touch).sum())
        print(f'\n==== grid={grid} (prices-history fidelity {GRIDS[grid][1]} min), mid rule={a.mid_rule}, '
              f'ET days {o.event_day.min()}..{o.event_day.max()}, {pn.event_slug.nunique()} events -> {FWD / name}')
        print(f'decision rows {len(pn)}, eligible rows {len(d_all)}, strikes traded {len(o)}; '
              f'Polymarket outcome vs Binance touch mismatches: {mis}; entries before freeze commit: {int(o.pre_freeze.sum())}')
        print(summary(o).to_string(index=False))
        by_day = o.groupby('event_day').agg(trades=('roi_real', 'size'), losses=('outcome_yes', 'sum'),
                                            mean_pnl_real_pct=('roi_real', lambda v: round(100 * v.mean(), 3)))
        print(by_day.to_string())
        losers = o[o.outcome_yes == 1]
        print(f'losing trades: {len(losers)}')
        if len(losers):
            print(losers[['asset', 'event_day', 'slug', 'side', 'strike', 'decision_utc', 'hours_left', 'yes_mid', 'x', 'x_pass',
                          'px_mid', 'px_real', 'has_real', 'roi_real']].to_string(index=False))
        if a.validate and grid == 'study':
            validate(d_all, first, sorted(set(mk.event_slug) - {ev for ev, _ in pending}))


if __name__ == '__main__':
    main()
