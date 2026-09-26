# 09 — Liquidity-reward (LP) farming in weather markets: evidence so far (interim)

## Ground truth (on-chain / data-api, 2026-09-26)
* Rewards are real and paid daily (`/activity?type=REWARD`). Profile/leaderboard PnL EXCLUDES them (no jump at the
  00:00 UTC payout hour even with zero trades) → true economics = board PnL + REWARD + MAKER_REBATE.
* Largest weather LP `0x30fb41…` (tradetosurvive1): 30d rewards $121.5k, trading −$54k → **net ≈ +$67k/30d** on
  ≈$60–120k equity. It takes **0% of its weather fills after local noon on the observation day** (pulls quotes).
* Small weather LP `0x04586f…` (I---I, ≈$728 equity incl. $284 pUSD): $30–48/day rewards since 09-23, but it keeps
  quoting on the observation day (80% of fills) and was −$1,046 net over 30 days → the discipline matters.
* 206 "clean" LPs: 79% net positive after rewards; small ones (<$5k) hand back ~85% of rewards via adverse selection.
  Profitable ones quote two-sided and pull before information windows (research/02 §6).

## Adverse selection of naive 2-sided quoting (historical, 1,698 weather temperature markets Jul–Sep 2026)
Quotes at 1-min price ± d, 20 shares/side, ±60 inventory cap, fills only on real taker prints through our level,
held to resolution (`src/live/hist_quote_local.py`). $ per market-day, by station-LOCAL time vs target day D:

| window (local) | d=1¢ | d=2¢ | d=3¢ |
|---|---:|---:|---:|
| before D-1 00:00 | −2.71 | −1.44 | −0.87 |
| D-1 00–12 | −2.38 | −1.63 | −1.07 |
| D-1 12–18 | −1.69 | −1.13 | −0.05 |
| D-1 18–24 | −0.27 | +0.08 | −0.02 |
| D 00–06 | −4.27 | −2.22 | −1.82 |
| D 06–10 | −4.05 | −2.31 | −1.68 |
| **D 10–14** | **−30.7** | **−21.8** | **−14.4** |
| D 14–end | −14.6 | −11.4 | −9.5 |

→ Never quote on the observation day; before it, the cost is ≈ $1–2.7 per market-day per 20-share quote.

## Reward side (live paper estimate, still accumulating)
Live books recorded every minute (`src/live/recorder.py`), our hypothetical 2-sided min-size quote scored with the
official formula vs aggregated competitor liquidity (`src/live/sim_lp.py`, `lp_report3.py`), temperature markets,
quoting only until station-local midnight of D: **≈ $4.6–5.6 per quoted market-day** (≈$19.5 capital per market).
This looks too good relative to real wallets; an independent audit of the simulator is in progress
(`research/audit_lp_rewards.md`). Treat as an UPPER bound until audited and until ≥24 h of books are recorded.
