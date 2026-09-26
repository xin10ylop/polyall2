"""Minimal Jev (TypeSafe System One) client via OpenRouter Decisions API.

Jev returns calibrated probabilities for typed questions (noul / choice / score)
about a `state`. It does not generate text. Cost is per input token (~$0.00001-0.00005/call).
"""
import json, os, time, threading
import requests

API = "https://openrouter.ai/api/alpha/decisions"
MODEL = os.environ.get("JEV_MODEL", "typesafe/jev-1.13")
_lock = threading.Lock()
_cost = {"usd": 0.0, "calls": 0}


def _key():
    k = os.environ.get("OPENROUTER_API_KEY")
    if not k:
        env = os.path.join(os.path.dirname(__file__), "../../.env")
        if os.path.exists(env):
            for line in open(env):
                if line.startswith("OPENROUTER_API_KEY="):
                    k = line.strip().split("=", 1)[1]
    if not k:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    return k


def decide(state, questions, model=MODEL, tries=5, timeout=60):
    """state: str|dict|list; questions: {name: {type, instructions, criteria}}"""
    body = {"model": model, "state": state, "questions": questions}
    last = None
    for i in range(tries):
        try:
            r = requests.post(API, headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json",
                                            "X-Title": "polyall2-research"}, data=json.dumps(body), timeout=timeout)
            if r.status_code == 200:
                d = r.json()
                with _lock:
                    _cost["usd"] += (d.get("usage") or {}).get("cost", 0) or 0
                    _cost["calls"] += 1
                return d["answers"]
            last = f"{r.status_code} {r.text[:300]}"
            if r.status_code in (400, 401, 402, 403):
                break
        except Exception as e:  # network
            last = repr(e)
        time.sleep(1.5 * (2 ** i))
    raise RuntimeError(f"jev failed: {last}")


def noul(state, instructions, true_desc, false_desc, **kw):
    a = decide(state, {"q": {"type": "noul", "instructions": instructions,
                             "criteria": {"true": true_desc, "false": false_desc}}}, **kw)
    return a["q"]["noul"]


def cost():
    return dict(_cost)
