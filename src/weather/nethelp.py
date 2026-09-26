"""Polite cached HTTP helper with exponential backoff (429/5xx)."""
import hashlib
import json
import os
import time
import random

import requests

CACHE_ROOT = "/home/user/polyall2/data/weather/cache"
_session = requests.Session()
_session.headers.update({"User-Agent": "research-weather-backtest/0.1 (academic)"})


def _key(url, params):
    s = url + "?" + json.dumps(params or {}, sort_keys=True)
    return hashlib.sha1(s.encode()).hexdigest()


def get_json(url, params=None, ns="misc", ttl=None, max_tries=8, timeout=60, cache=True):
    """GET JSON with disk cache under CACHE_ROOT/ns. ttl=None -> cache forever."""
    d = os.path.join(CACHE_ROOT, ns)
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, _key(url, params) + ".json")
    if cache and os.path.exists(fp):
        if ttl is None or (time.time() - os.path.getmtime(fp)) < ttl:
            with open(fp) as f:
                return json.load(f)
    delay = 1.0
    last = None
    for i in range(max_tries):
        try:
            r = _session.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            last = e
            time.sleep(delay + random.random())
            delay = min(delay * 2, 60)
            continue
        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                data = {"__text__": r.text}
            if cache:
                with open(fp, "w") as f:
                    json.dump(data, f)
            return data
        if r.status_code in (429, 500, 502, 503, 504, 520, 522, 524):
            ra = r.headers.get("Retry-After")
            wait = float(ra) if ra and ra.replace(".", "").isdigit() else delay
            time.sleep(wait + random.random())
            delay = min(delay * 2, 90)
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            continue
        # non-retryable
        return {"__error__": r.status_code, "__text__": r.text[:500]}
    raise RuntimeError(f"failed {url} {params}: {last}")


def get_text(url, params=None, ns="misc_text", max_tries=8, timeout=90, cache=True):
    d = os.path.join(CACHE_ROOT, ns)
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, _key(url, params) + ".txt")
    if cache and os.path.exists(fp):
        with open(fp) as f:
            return f.read()
    delay = 1.0
    last = None
    for i in range(max_tries):
        try:
            r = _session.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            last = e
            time.sleep(delay + random.random())
            delay = min(delay * 2, 60)
            continue
        if r.status_code == 200:
            if cache:
                with open(fp, "w") as f:
                    f.write(r.text)
            return r.text
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(delay + random.random())
            delay = min(delay * 2, 90)
            last = f"HTTP {r.status_code}"
            continue
        return None
    raise RuntimeError(f"failed {url}: {last}")
