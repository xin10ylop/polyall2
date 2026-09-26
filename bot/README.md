# polyall2 bot — execution layer

Strategy-agnostic execution for Polymarket (CLOB V2, pUSD collateral) using the official `polymarket-client` SDK.

* `PAPER=1` (default): no orders are sent; fills are simulated against the live order book (taker = walk the
  displayed book; maker = only trade-through fills from live prints), everything is logged to `bot_state/`.
* `PAPER=0`: real orders. Requires `POLYMARKET_PRIVATE_KEY`, `POLYMARKET_WALLET_ADDRESS` in the environment and
  must be run from a jurisdiction where Polymarket permits trading (check `https://polymarket.com/api/geoblock`;
  the bot refuses to start live if it reports `blocked: true`). Do not use VPNs to evade geoblocks (ToS).
* Every new market passes a Jev rules check (`guard.py`) before the bot trades it (validated: 300/300 correct on
  station/unit checks, see `research/07_jev_experiments.md`).

Hard risk limits (env): `MAX_POS_USD` per market, `MAX_DAY_LOSS_USD`, `MAX_OPEN_USD`, kill-switch file `bot_state/KILL`.
