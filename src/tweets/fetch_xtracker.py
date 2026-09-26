"""Fetch xtracker users, trackings and full post lists (with importedAt) for all tracked handles.
Saves raw JSON + a compact parquet per handle under data/tweets/xt/.
Run repeatedly: each run also saves a timestamped snapshot of tracking postCounts (for later
as-of checks of deletions/late imports)."""
import json, os, time, datetime as dt
import requests, pandas as pd

OUT = "/home/user/polyall2/data/tweets/xt"
BASE = "https://xtracker.polymarket.com/api"
S = requests.Session()

def get(path, **params):
    for i in range(5):
        try:
            r = S.get(f"{BASE}/{path}", params=params, timeout=120)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print("retry", path, e); time.sleep(2 + 3 * i)
    raise RuntimeError(path)

def main():
    os.makedirs(OUT, exist_ok=True)
    now = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    users = get("users")["data"]
    json.dump(users, open(f"{OUT}/users_{now}.json", "w"))
    trk = get("trackings")["data"]
    json.dump(trk, open(f"{OUT}/trackings_{now}.json", "w"))
    for u in users:
        h = u["handle"]
        if u["_count"]["posts"] == 0:
            continue
        # per-user trackings (may include inactive/historical)
        ut = get(f"users/{h}/trackings")["data"]
        json.dump(ut, open(f"{OUT}/trackings_{h}.json", "w"))
        posts = get(f"users/{h}/posts")["data"]
        df = pd.DataFrame(posts)
        keep = [c for c in ["id", "platformId", "createdAt", "importedAt", "content"] if c in df]
        df = df[keep].copy()
        df["createdAt"] = pd.to_datetime(df["createdAt"], utc=True)
        df["importedAt"] = pd.to_datetime(df["importedAt"], utc=True)
        df["content"] = df["content"].astype(str).str.slice(0, 200)
        df.to_parquet(f"{OUT}/posts_{h}.parquet")
        print(h, len(df), df.createdAt.min(), df.createdAt.max(), "trackings", len(ut))

if __name__ == "__main__":
    main()
