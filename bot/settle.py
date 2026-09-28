"""Mark paper (or live) ledger fills to resolution / current mid and print P&L.
Usage: BOT_STATE=... python bot/settle.py"""
import os, json, collections
import requests
STATE = os.environ.get("BOT_STATE", os.path.join(os.path.dirname(__file__), "..", "bot_state"))
led = os.path.join(STATE, "ledger.jsonl")
if not os.path.exists(led):
    print("no ledger yet"); raise SystemExit
fills = [json.loads(l) for l in open(led) if '"taker_buy"' in l]
cache = {}
def token_state(tok):
    if tok in cache: return cache[tok]
    # gamma hides closed markets unless closed=true is passed; try closed first, then open
    m = requests.get("https://gamma-api.polymarket.com/markets", params={"clob_token_ids": tok, "closed": "true"}, timeout=20).json() \
        or requests.get("https://gamma-api.polymarket.com/markets", params={"clob_token_ids": tok}, timeout=20).json()
    st = None
    if m:
        m = m[0]; toks = json.loads(m["clobTokenIds"]); i = toks.index(tok)
        op = [float(x) for x in json.loads(m["outcomePrices"])]
        st = {"closed": bool(m.get("closed")), "price": op[i], "q": m["question"]}
    cache[tok] = st; return st
tot = collections.Counter()
for f in fills:
    s = token_state(f["token"])
    if not s: continue
    val = f["shares"] * s["price"]
    pnl = val - f["usd"] - f.get("fee", 0)
    k = "resolved" if s["closed"] and s["price"] in (0.0, 1.0) else "open(marked)"
    tot[k + "_pnl"] += pnl; tot[k + "_cost"] += f["usd"]; tot[k + "_n"] += 1
    print(f"{k:13s} {s['q'][:60]:60s} {f['shares']:.1f}sh @{f['avg_px']:.3f} -> {s['price']:.3f} pnl {pnl:+.2f}")
print(dict(tot))
