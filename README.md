# polyall2 — Polymarket edge research + Jev/LLM tooling

Research into executable, small-capital Polymarket strategies (September 2026), with the code, findings and a
paper-trading bot. Summary report: `reports/edge_hunt.html` (published as a private artifact).

## Findings

Adopted (small, survived out-of-sample tests and independent re-checks — see `research/11_independent_checks.md`):

* **Sell daily BTC barrier longshots.** Market: "What price will Bitcoin hit on <day>?". Strikes have YES at 0.5–3¢ with ≤12 h left. Result: +0.74%/trade and 4 losses in 1,468 trades. That comes to ≈$25/day at $1k clips.
* **Tweet-count markets for small X accounts.** Result: +18.6% OOS, but lumpy. Books absorb only ≈$54/day, so ≈$10/day.

Rejected after testing (details in `research/`):

* Weather forecast models: the market is more accurate.
* Weather dead buckets: a 60–120 s data race, and public feeds lag 4–20 min.
* LP-reward farming: median net ≈+0.25%/day, losing month in 1 of 3.
* Mentions longshot fade: in-sample gains, zero out of sample.
* Maker quoting of any kind: adverse selection.
* Crypto vol models, box office, Spotify/Billboard and structural arbitrage.

Pending forward tests:

* **LLM research + Jev judge.** 26 pre-registered forecasts in `research/forward_test/`.
* **Hong Kong Observatory live dead-bucket test.** Script: `src/nowcast/hk_monitor.py`.

**Hard constraint:** Polymarket geoblocks the US (this research machine is blocked). Run live trading only from an
allowed jurisdiction with your own account.

## Layout
| Path | What |
|---|---|
| `research/01…11` | Written findings per strategy family, audits, forensics |
| `src/common/jev.py` | Jev (TypeSafe System One) client via OpenRouter Decisions API |
| `src/jev_tests/` | Jev experiments (leakage, forecasting, toxicity, rules guard, forward-test scoring) |
| `src/llm_pipeline/research.py` | Automated LLM (web search) research + Jev judge forecaster |
| `src/data/`, `src/calib/` | Market enumeration, trade/price fetchers, calibration & maker/taker backtests |
| `src/weather/`, `src/nowcast/` | Weather data, forecast/nowcast models, dead-bucket analysis, live monitors |
| `src/crypto/`, `src/tweets/`, `src/datalead/` | Family-specific backtests |
| `src/live/`, `src/audit/` | Live order-book recorder, LP reward simulator and its audit |
| `bot/` | Execution layer (`polymarket-client`), Jev pre-trade guard, strategies, settlement |

## Setup
```bash
pip install polymarket-client requests pandas numpy scipy scikit-learn timezonefinder pyarrow
echo "OPENROUTER_API_KEY=sk-or-..." > .env        # never commit this file (.gitignore covers it)
PAPER=1 python3 bot/strategies/btc_barrier_no.py  # paper trading against live books
python3 bot/settle.py                             # P&L of paper fills
```
Live mode (`PAPER=0`) needs `POLYMARKET_PRIVATE_KEY` and `POLYMARKET_WALLET_ADDRESS`, refuses to start when
`https://polymarket.com/api/geoblock` reports the IP as blocked, and stops when `bot_state/KILL` exists.
