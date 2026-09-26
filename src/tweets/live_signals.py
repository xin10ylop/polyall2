"""Live check: model bucket probabilities for currently open count events vs the REAL order book
(best ask / best bid and depth) from the latest books snapshot. Uses xtracker as-of now."""
import json, glob, sys, os, time, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from common import D
from model import Acct, bucket_probs, hbin
from build_events import parse_window

W = json.load(open(f"{D}/wf_params.json"))
def main(book_file=None, now=None):
    bf = book_file or sorted(glob.glob(f"{D}/books/books_*.parquet"))[-1]
    bk = pd.read_parquet(bf)
    now = now or int(pd.Timestamp(bk.ts.iloc[0]).tz_localize("UTC").timestamp())
    evs = {e["slug"]: e for e in (json.loads(l) for l in open(f"{D}/gamma/events_open.jsonl"))}
    out = []
    for slug, g in bk.groupby("slug"):
        e = evs[slug]; acct = g.acct.iloc[0]
        desc = next((m.get("description") for m in e["markets"] if m.get("description")), e.get("description"))
        S, E = parse_window(desc, e.get("endDate"))
        S = int(S.timestamp()); E = int(E.timestamp())
        a = Acct(acct)
        ts_ = max(now, S); H = (E - ts_) / 3600
        p = W["2026-09"].get(acct, {}); hb = int(hbin(np.array([H]))[0])
        pr = p.get(str(hb)) or p[str(min((int(k) for k in p), key=lambda k: abs(k - hb)))]
        C = a.count(S, now) if now > S else 0
        R, prof = a.state(now, pr["hl"]); mu = a.expected(ts_, E, R, prof)
        # all buckets of the event (closed buckets have q=0 anyway)
        g = g.sort_values("lo")
        q = bucket_probs(C, mu, pr["alpha"], g.lo.values, g.hi.values)
        g = g.assign(q=q, C=C, mu=mu, H=H)
        out.append(g)
    X = pd.concat(out)
    r = X.fee_rate.fillna(0.05)
    X["cost_y"] = X.best_ask + r * X.best_ask * (1 - X.best_ask)
    X["no_ask"] = 1 - X.best_bid
    X["cost_n"] = X.no_ask + r * X.no_ask * (1 - X.no_ask)
    X["edge_y"] = X.q - X.cost_y
    X["edge_n"] = (1 - X.q) - X.cost_n
    return X

if __name__ == "__main__":
    X = main()
    pd.set_option("display.width", 250)
    cols = ["acct", "event", "label", "C", "mu", "H", "q", "best_bid", "best_ask", "edge_y", "edge_n", "ask_usd_2c", "bid_usd_2c"]
    X["event"] = X.event.str.slice(0, 40)
    print(X[(X.edge_y > 0.03) | (X.edge_n > 0.03)][cols].round(3).to_string(index=False))
    X.to_parquet(f"{D}/books/live_signals_{int(time.time())}.parquet")
