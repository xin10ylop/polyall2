"""Helpers: executable YES/NO taker prices from cached PM prints / price history."""
import bisect, csv, json, os

D = os.path.join(os.path.dirname(__file__), "../../data/datalead/pm")
_tr, _ph = {}, {}


def trades(cid):
    """list of (ts, yes_equiv_price, shares, kind) where kind='Y' if the print was a YES-buy-equivalent
    (taker BUY YES @p, or taker SELL NO @q -> YES price 1-q) and 'N' if NO-buy-equivalent."""
    if cid in _tr:
        return _tr[cid]
    fn = os.path.join(D, "tr", f"{cid}.csv")
    out = []
    if os.path.exists(fn):
        with open(fn) as f:
            r = csv.reader(f); next(r)
            for ts, side, oi, p, sz in r:
                ts, oi, p, sz = int(ts), int(oi), float(p), float(sz)
                yes_buy = (side == "B" and oi == 0) or (side == "S" and oi == 1)
                yp = p if oi == 0 else 1 - p
                out.append((ts, yp, sz, "Y" if yes_buy else "N"))
    out.sort()
    _tr[cid] = out
    return out


def ph(cid):
    if cid in _ph:
        return _ph[cid]
    fn = os.path.join(D, "ph", f"{cid}.json")
    d = json.load(open(fn)) if os.path.exists(fn) else {"t": [], "p": []}
    _ph[cid] = d
    return d


def mid_at(cid, t):
    d = ph(cid)
    i = bisect.bisect_right(d["t"], t) - 1
    if i < 0:
        return None
    if t - d["t"][i] > 6 * 3600:   # stale
        return None
    return d["p"][i]


def fill(cid, t, side, window=3 * 3600, max_shares=None):
    """Taker fill at/after t using actual prints of the same direction in [t, t+window].
    side 'Y' (buy YES) or 'N' (buy NO). Returns (avg_price_of_the_bought_token, shares_available, first_ts) or None.
    Prices are the token's own price (NO price = 1 - yes_equiv)."""
    tr = trades(cid)
    i = bisect.bisect_left(tr, (t,))
    sh, cost, first = 0.0, 0.0, None
    while i < len(tr) and tr[i][0] <= t + window:
        ts, yp, sz, kind = tr[i]
        if kind == side:
            p = yp if side == "Y" else 1 - yp
            take = sz if max_shares is None else min(sz, max_shares - sh)
            if take > 0:
                sh += take; cost += take * p
                first = first or ts
            if max_shares is not None and sh >= max_shares:
                break
        i += 1
    if sh <= 0:
        return None
    return cost / sh, sh, first


def volume_between(cid, t0, t1):
    tr = trades(cid)
    i = bisect.bisect_left(tr, (t0,))
    v = 0.0
    while i < len(tr) and tr[i][0] <= t1:
        v += tr[i][2] * (tr[i][1] if tr[i][3] == "Y" else 1 - tr[i][1]); i += 1
    return v
