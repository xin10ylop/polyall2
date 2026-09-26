"""Execution wrapper: live (polymarket-client) or paper (simulated against live books)."""
import os, json, time, math, logging
import requests
log = logging.getLogger("exec")
STATE = os.environ.get("BOT_STATE", os.path.join(os.path.dirname(__file__), "..", "bot_state"))
os.makedirs(STATE, exist_ok=True)
PAPER = os.environ.get("PAPER", "1") != "0"
CLOB = "https://clob.polymarket.com"

def taker_fee(rate, price, shares):
    return rate * price * (1 - price) * shares

def geoblocked():
    try:
        return bool(requests.get("https://polymarket.com/api/geoblock", timeout=15).json().get("blocked"))
    except Exception:
        return True

def book(token_id):
    r = requests.get(f"{CLOB}/book", params={"token_id": token_id}, timeout=15)
    r.raise_for_status()
    b = r.json()
    bids = sorted(((float(x["price"]), float(x["size"])) for x in b.get("bids", [])), key=lambda z: -z[0])
    asks = sorted(((float(x["price"]), float(x["size"])) for x in b.get("asks", [])), key=lambda z: z[0])
    return bids, asks, b

class Executor:
    def __init__(self):
        self.paper = PAPER
        self.client = None
        self.ledger = os.path.join(STATE, "ledger.jsonl")
        if not self.paper:
            if geoblocked():
                raise SystemExit("Polymarket reports this IP as geoblocked; refusing to trade live.")
            from polymarket import SecureClient
            self.client = SecureClient.create(private_key=os.environ["POLYMARKET_PRIVATE_KEY"],
                                              wallet=os.environ.get("POLYMARKET_WALLET_ADDRESS"))
            if self.client.get_closed_only_mode():
                raise SystemExit("Account is in closed-only mode; refusing to trade.")

    def _log(self, rec):
        rec["ts"] = time.time(); rec["paper"] = self.paper
        with open(self.ledger, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def buy_taker(self, token_id, max_price, usd, fee_rate, tag=""):
        """Marketable buy up to `usd` notional at prices <= max_price (FAK: never rests). Returns (shares, avg_px)."""
        bids, asks, _ = book(token_id)
        fill_sh = 0.0; cost = 0.0
        for p, s in asks:
            if p > max_price + 1e-9 or cost >= usd - 1e-6: break
            take = min(s, (usd - cost) / p); fill_sh += take; cost += take * p
        if fill_sh < 5:  # below min order size
            return 0.0, None
        avg = cost / fill_sh
        if self.paper:
            fee = taker_fee(fee_rate, avg, fill_sh)
            self._log({"type": "taker_buy", "token": token_id, "shares": fill_sh, "avg_px": avg, "usd": cost, "fee": fee, "tag": tag})
            return fill_sh, avg
        resp = self.client.place_market_order(token_id=token_id, side="BUY", max_spend=str(round(usd, 2)),
                                              max_price=str(max_price), order_type="FAK")
        self._log({"type": "taker_buy_live", "token": token_id, "resp": str(resp)[:500], "tag": tag})
        return fill_sh, avg

    def post_limit(self, token_id, side, price, size, expiration=None, tag=""):
        """Post-only limit (maker). Paper mode just records the intent; fills are simulated elsewhere."""
        if self.paper:
            oid = f"paper-{token_id[-6:]}-{side}-{price}-{time.time():.0f}"
            self._log({"type": "post", "token": token_id, "side": side, "price": price, "size": size, "oid": oid, "tag": tag})
            return oid
        resp = self.client.place_limit_order(token_id=token_id, side=side, price=str(price), size=str(size),
                                             post_only=True, expiration=expiration)
        self._log({"type": "post_live", "token": token_id, "side": side, "price": price, "size": size, "resp": str(resp)[:500], "tag": tag})
        return getattr(resp, "order_id", None) or getattr(resp, "orderId", None)

    def cancel_all(self):
        if self.paper:
            self._log({"type": "cancel_all"}); return
        self.client.cancel_all(); self._log({"type": "cancel_all_live"})
