"""Pull the full trade history (data-api /trades?user=, offset<=10000) for reference wallets and
summarise by event family / timing. Cache: data/datalead/wallets/<addr>.json
"""
import json, os, re, sys, time, collections
import requests

OUT = os.path.join(os.path.dirname(__file__), "../../data/datalead/wallets")
W = {"KimchiCapital": "0x9578af80708f271f705e27867dcf6ec653acf066",
     "Started-with-20-USD": "0x4388640a35b4ecebc33f8c73b58a2b988c615050",
     "Quarrelsome-Branch": "0x0cb10c40b0776e9ee8cef970af85724654dda76c"}
S = requests.Session()


def get(url, params, tries=6):
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 400:
                return None
        except Exception:
            pass
        time.sleep(1.5 * 2 ** i)
    return None


def pull(addr, kind="trades"):
    fn = os.path.join(OUT, f"{addr}_{kind}.json")
    if os.path.exists(fn):
        return json.load(open(fn))
    rows, off = [], 0
    while off <= 10000:
        p = {"user": addr, "limit": 500, "offset": off}
        if kind == "trades":
            p["takerOnly"] = "false"
        d = get(f"https://data-api.polymarket.com/{kind}", p)
        if not d:
            break
        rows += d
        if len(d) < 500:
            break
        off += 500
    os.makedirs(OUT, exist_ok=True)
    json.dump(rows, open(fn, "w"))
    return rows


def family(title):
    t = title.lower()
    for k, p in [("spotify", r"spotify|song this week|streams"), ("billboard", r"billboard|hot 100"),
                 ("album_sales", r"album sales|first week"), ("boxoffice", r"box office"),
                 ("mrbeast", r"mrbeast"), ("netflix", r"netflix"), ("ai_model", r"ai model|ai company"),
                 ("appstore", r"app store"), ("gpu", r"gpu"), ("f1", r"f1 |grand prix"),
                 ("trump_say", r"trump say|say .* this week"), ("mention", r"say|mention"),
                 ("outage", r"outage"), ("yield", r"yield|treasury"), ("valuation", r"valuation"),
                 ("weather", r"temperature|°"), ("crypto", r"bitcoin|ethereum|solana|xrp")]:
        if re.search(p, t):
            return k
    return "other"


if __name__ == "__main__":
    for name, a in W.items():
        tr = pull(a, "trades")
        c = collections.Counter(); v = collections.Counter()
        for t in tr:
            f = family(t["title"]); c[f] += 1; v[f] += t["size"] * t["price"]
        ts = [t["timestamp"] for t in tr]
        print(name, len(tr), time.strftime("%Y-%m-%d", time.gmtime(min(ts))) if ts else None,
              time.strftime("%Y-%m-%d", time.gmtime(max(ts))) if ts else None)
        for f, n in c.most_common(15):
            print(f"   {f:12s} n={n:5d} usd={v[f]:10.0f}")
