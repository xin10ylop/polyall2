"""Automated 'LLM research + Jev judge' forecaster for low-attention Polymarket markets.

1. select open markets (non-sports, non-crypto-updown, non-weather), resolving in 18h–7d, mid 0.08–0.92,
   spread <= 6c, 24h volume >= $500, one per event
2. research each with an LLM that can search the web (OpenRouter, default anthropic/claude-opus-5.5 + web plugin),
   returning JSON {p_yes, evidence}; the LLM is told NOT to use Polymarket prices
3. Jev (typesafe/jev-1.13) judges P(YES) from rules + evidence (calibrated, cheap)
4. log everything to data/llm_pipeline/forecasts.jsonl for forward evaluation; emit signals where
   p_combined - ask > MIN_EDGE (buy YES) or (1-p_combined) - (1-bid) > MIN_EDGE (buy NO)
Costs (OpenRouter list prices): Opus 5.5 $4/M in, $20/M out, web search $0.01/result-set; Jev ~$0.00003/call.
"""
import os, sys, json, time, datetime as dt, random, re
import requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.jev import decide, _key
ROOT = os.path.join(os.path.dirname(__file__), "../..")
OUT = f"{ROOT}/data/llm_pipeline"; os.makedirs(OUT, exist_ok=True)
MODEL = os.environ.get("LLM_MODEL", "anthropic/claude-opus-5.5")
MIN_EDGE = float(os.environ.get("MIN_EDGE", 0.06))

def select_markets(n=20, hmin=18, hmax=168):
    now = dt.datetime.now(dt.timezone.utc); rows = []; cur = None
    while True:
        p = {"closed": "false", "limit": 500, "end_date_min": (now + dt.timedelta(hours=hmin)).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "end_date_max": (now + dt.timedelta(hours=hmax)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        if cur: p["after_cursor"] = cur
        d = requests.get("https://gamma-api.polymarket.com/markets/keyset", params=p, timeout=30).json()
        ms = d.get("markets", []); rows += ms; cur = d.get("next_cursor")
        if not cur or not ms: break
    out, seen = [], set()
    for m in sorted(rows, key=lambda m: -(m.get("volume24hr") or 0)):
        ft = m.get("feeType") or "none"
        if ft.startswith(("sports", "crypto")) or ft in ("weather_fees", "zero_fees") or not m.get("acceptingOrders"): continue
        bb, ba = m.get("bestBid"), m.get("bestAsk")
        if bb is None or ba is None or ba - bb > 0.06 or not (0.08 <= (bb + ba) / 2 <= 0.92) or (m.get("volume24hr") or 0) < 500: continue
        ev = (m.get("events") or [{}])[0].get("id")
        if ev in seen: continue
        seen.add(ev)
        out.append({"cid": m["conditionId"], "q": m["question"], "desc": (m.get("description") or "")[:2000], "end": m["endDate"],
                    "bid": bb, "ask": ba, "rate": (m.get("feeSchedule") or {}).get("rate", 0.05) if m.get("feesEnabled") else 0.0,
                    "tokens": json.loads(m["clobTokenIds"])})
    return out[:n]

PROMPT = """You are a careful, calibrated forecaster. Research this prediction market using web search.
Do NOT look up or use Polymarket / Kalshi / betting prices or comments; form an independent view from primary data.
Current UTC time: {now}. Market resolves at: {end}.
Question: {q}
Resolution rules: {desc}
Return ONLY a JSON object: {{"p_yes": <0..1>, "confidence": "low|medium|high", "evidence": "<= 900 chars of dated facts with sources that bear on the outcome"}}"""

def llm_research(m):
    body = {"model": MODEL, "plugins": [{"id": "web", "max_results": 5}], "max_tokens": 1500, "temperature": 0.2,
            "messages": [{"role": "user", "content": PROMPT.format(now=dt.datetime.utcnow().isoformat(timespec="minutes"), end=m["end"], q=m["q"], desc=m["desc"])}]}
    r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"},
                      data=json.dumps(body), timeout=180)
    r.raise_for_status()
    d = r.json(); txt = d["choices"][0]["message"]["content"]
    j = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
    return j, (d.get("usage") or {})

def jev_judge(m, evidence):
    st = {"market_question": m["q"], "resolution_rules": m["desc"], "evidence": evidence, "as_of_utc": dt.datetime.utcnow().isoformat(timespec="minutes")}
    a = decide(st, {"yes": {"type": "noul", "instructions": "Given the rules and the evidence, what is the probability that this market resolves YES?",
                            "criteria": {"true": "Resolves YES under its rules.", "false": "Resolves NO under its rules."}}})
    return a["yes"]["noul"]

def run(n=20, dry=False):
    ms = select_markets(n)
    for m in ms:
        try:
            j, usage = ({"p_yes": None, "evidence": ""}, {}) if dry else llm_research(m)
            pj = jev_judge(m, j["evidence"]) if j.get("evidence") else None
            pc = None if j["p_yes"] is None else (0.5 * j["p_yes"] + 0.5 * pj if pj is not None else j["p_yes"])
            sig = None
            if pc is not None:
                if pc - m["ask"] - m["rate"] * m["ask"] * (1 - m["ask"]) > MIN_EDGE: sig = ("BUY_YES", m["ask"])
                elif (1 - pc) - (1 - m["bid"]) - m["rate"] * m["bid"] * (1 - m["bid"]) > MIN_EDGE: sig = ("BUY_NO", round(1 - m["bid"], 4))
            rec = {"ts": time.time(), **{k: m[k] for k in ("cid", "q", "end", "bid", "ask")}, "p_llm": j.get("p_yes"), "p_jev": pj,
                   "p_comb": pc, "confidence": j.get("confidence"), "evidence": j.get("evidence"), "signal": sig, "usage": usage, "model": MODEL}
            with open(f"{OUT}/forecasts.jsonl", "a") as f: f.write(json.dumps(rec) + "\n")
            print(f"{m['q'][:70]:70s} bid/ask {m['bid']:.2f}/{m['ask']:.2f} llm {j.get('p_yes')} jev {pj} -> {sig}")
        except Exception as e:
            print("ERR", m["q"][:60], repr(e)[:200])

if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 20, dry=("--dry" in sys.argv))
