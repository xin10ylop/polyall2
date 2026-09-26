# 02 — Polymarket Leaderboard Forensics: how consistent, small-capital traders make money

*Status: IN PROGRESS (written incrementally). Data pulled 2026-09-26.*

## 0. Data sources and API notes (verified by probing)

| Endpoint | What it gives | Limits discovered |
|---|---|---|
| `data-api.polymarket.com/v1/leaderboard?timePeriod=DAY\|WEEK\|MONTH\|ALL&orderBy=PNL\|VOL&category=<c>&limit&offset&user=` | ranked wallets with `pnl`, `vol` | `limit` max 50; `offset` works to at least 1000; categories: `overall, politics, sports, crypto, culture, mentions, weather, economics, tech, finance, esports`; `user=` returns a single wallet's PnL in that category/window (used for category split) |
| `lb-api.polymarket.com/profit?window=1d\|7d\|30d\|all` | legacy profit board | returns max 50 rows; same ranking as v1 |
| `user-pnl-api.polymarket.com/user-pnl?user_address=&interval=all&fidelity=1d` | daily **cumulative** PnL series (realized + mark-to-market) | 1 call per wallet; basis for all consistency metrics |
| `data-api.polymarket.com/activity?user=&limit=500&offset&end=` | TRADE / REDEEM / MERGE / SPLIT / REWARD / CONVERSION events with `usdcSize` | limit max 500, **offset max 5000**; page further back with `end=<ts>` |
| `data-api.polymarket.com/trades?user=&takerOnly=true\|false&limit=` | fills; **`takerOnly` defaults to true** | `takerOnly=true` vs `false` difference = maker fills → maker/taker split |
| `data-api.polymarket.com/closed-positions?user=&limit=50&offset&sortBy=REALIZEDPNL\|TIMESTAMP` | per-outcome-token realized PnL, avgPrice, totalBought | limit 50/page; includes resolved losers (curPrice 0) |
| `data-api.polymarket.com/positions?user=&sizeThreshold=0` | open positions, `cashPnl`, `redeemable` | limit 500 |
| `data-api.polymarket.com/traded?user=` | count of distinct markets traded | |
| `gamma-api.polymarket.com/markets?condition_ids=..` | market metadata incl. `endDate`, `closedTime`, `gameStartTime`, `eventDate`, series, `feesEnabled` | multiple `condition_ids` per call |

Notable: many 2026 markets have `feesEnabled: true` (taker fees), and wallets receive `REWARD` activity (liquidity rewards / maker rebates) — both materially change the economics of high-frequency and near-certain ("0.99") strategies.

## 1. Universe and screening funnel

**Pull (2026-09-26):** overall PnL leaderboard top-1000 for each of DAY / WEEK / MONTH / ALL, top-200 of each of 10 category boards for WEEK / MONTH / ALL, and top-200 volume boards → **10,600 rows, 5,192 unique wallets** (`data/leaderboard/leaderboard_raw.csv`, legacy board in `lbapi_profit.csv`).

**Cheap screen (all 5,192 wallets):** daily cumulative PnL series (`user-pnl-api`) + distinct-markets count (`/traded`) → `pnl_series_daily.jsonl`, `screen_metrics.csv`. Metrics: all-time PnL, 30d/90d PnL, share of *active* weeks (|ΔPnL|>$1) that were profitable, best-day share of total PnL, top-3-day share, max drawdown / PnL, R² of cumulative PnL vs. time, annualised daily Sharpe.

### Survivorship / "leaderboard is a lottery ticket" evidence

| Board (top-1000) | share with **negative all-time PnL** | median share of profitable weeks | share whose single best day > 50% of all-time PnL |
|---|---|---|---|
| DAY | **38.4%** | 0.55 | 22.5% |
| WEEK | 22.6% | 0.64 | 25.1% |
| MONTH | 13.7% | 0.67 | 27.0% |
| ALL | 0% (by construction) | 0.67 | 27.0% |

- More than a third of today's top-1000 winners are lifetime losers; a daily/weekly board is mostly noise. Example: `stupid22` (0x8afa…6adb6) is #1 on the MONTH *weather* board (+$68k) but is **−$101k all-time** (−$117k in politics). Category/window boards must never be taken at face value.
- ~1 in 4 all-time-top wallets made more than half of their lifetime PnL on one day → "lucky whale / single event" profile.
- Survivorship bias: we only see wallets that are *currently* on a board. Wallets running the same strategies that blew up or stopped are invisible, so any strategy's apparent hit-rate is an upper bound.

**Consistency filter** (PnL > $3k, ≥ 8 active weeks, ≥ 30 markets, ≥ 70% profitable active weeks, best day ≤ 20% of PnL, max drawdown ≤ 50% of PnL, still active in last 30d) → **532 wallets** (`screen_consistent_candidates.csv`). Ranked by a composite (rank-average of profitable-week share, last-26-week share, daily Sharpe, R², longevity, 1 − best-day share). The extreme-Sharpe end (daily Sharpe 20–45, 100k+ markets, e.g. crypto boards) is dominated by bots — flagged later.

**Deep-fetch set:** top-110 composite + top-6 per best category + 30 smaller-PnL consistent wallets (< $60k) + 24 whales for contrast (ALL rank ≤ 15 or MONTH rank ≤ 10) → **146 wallets**. Per wallet: last ≤ 4,000 activity events, taker-only trades (to flag maker vs taker fills), up to 3,000 most-recent closed positions + top/bottom-50 by realized PnL (full history), open positions, all-time PnL by category (leaderboard `user=` filter), profile (`data/leaderboard/wallets/<addr>.json.gz`).

