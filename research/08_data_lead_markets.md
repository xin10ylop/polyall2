# 08 — Data-lead culture/data markets (Spotify weekly #1, weekend box office, …)

*Research date: 2026-09-26. Venue: Polymarket only. Code: `src/datalead/`. Cache: `data/datalead/` (<100 MB).*
*Status: IN PROGRESS — sections are filled incrementally.*

## 0. Question

Do recurring low-attention markets that resolve on a public data series (observable hours/days before
resolution) stay mispriced long enough for an automated reader of that data to take (taker-only) the implied
outcome profitably after fees? Reference wallets: KimchiCapital (Spotify / Billboard / album sales),
Started-with-20-USD (GPU price index, NG/WTI hit, IPO caps, F1), Quarrelsome-Branch (mention/outage/app-store).

## 1. Family screen and data availability (what can be backtested without look-ahead)

Sandbox egress: `web.archive.org` / `archive.ph` are **blocked** (no Wayback snapshots), GitHub search API
blocked, `flixpatrol.com` 403, YouTube Data API 403. Reachable: kworb.net, boxofficemojo.com, the-numbers.com,
HuggingFace, Spotify public charts endpoint (current chart only), deadline.com, billboard.com.

| Family | Closed events found | Resolution source | Historical, timestamp-safe data I could get | Verdict |
|---|---:|---|---|---|
| Spotify weekly #1 / #2 (global, US) | 101 events (41 global #1, 38 US #1, 11+11 #2), Nov-2025 → Sep-2026 | Spotify weekly chart (Fri–Thu), published Fri | **kworb.net per-track pages: full DAILY Global/US position + streams history** (+ weekly table as ground truth). Day D is published D+1 evening–D+2 (verified live: at 2026-09-26 14:45 UTC latest daily chart = 09-24) | **Backtest** |
| Weekend box office brackets (opening / Nth weekend) | 308 events, Feb-2024 → Sep-2026 | The Numbers final 3-day actuals (Mon/Tue) | **Box Office Mojo `/weekend/<YYYY>W<ww>/estimates/`: Sunday studio estimate AND Monday actual per film** (estimate is public Sun ~9–11am PT) | **Backtest** |
| MrBeast views day-N / week-1 | ~45 events × 5–7 brackets | YouTube view counter at 24/48/72 h | No per-video historical view trajectory reachable (no Wayback, no YouTube API) | Not backtestable here |
| Best AI model (weekly, arena.ai text, style-control off) | ~50 | arena.ai leaderboard at 12:00 ET on date | HF `lmarena-ai/leaderboard-dataset` exists but its publish lag vs. the site is unknown | Screen only |
| Netflix #1 views brackets | ~8 closed | top10.netflix.com Tuesday | FlixPatrol blocked; weekly-only ranks | Too few / no data |
| ChatGPT outage-day counts | 4 monthly events | status.openai.com | status page history is public but only 4 events | Too few |

Reference-wallet forensics (`src/datalead/wallet_forensics.py`, fills from data-api `/trades?user=`, fees
charged as if taker = upper bound): KimchiCapital's music trades Jan–Sep 2026 — Spotify 371 buys, hit 76%,
avg buy 0.695, ≈ +$3.2k on $29k notional; Billboard 187 buys, ≈ +$1.7k on $30k; first-week album sales 492 buys,
≈ +$1.3k on $43k. Most Spotify buys are placed **72–168 h before close (i.e. Fri–Tue of the chart week)**
at ~0.73 with ~80% hit — consistent with reading the first 1–3 daily charts. Total edge ≈ 5–10% of notional,
≈ $6k over 9 months: real but small.

## 2. Weekend box office brackets (308 events, 2024-02 → 2026-09)

**Data.** `src/datalead/boxoffice.py` enumerates the events (gamma public-search), parses brackets, and joins
each event to Box Office Mojo's weekend *estimates* page (`/weekend/<YYYY>W<ww>/estimates/`), which lists the
**Sunday studio estimate and the Monday actual** for every film (3,320 film-weekends, 117 weekends). 292/308
events matched; 19 multi-day (4/5-day holiday) events excluded a priori; 254 usable closed events with prices.
PM data: `clob prices-history` (10-min) + taker prints (`data-api /trades`), 1,377 markets.

**Estimate accuracy (all BOM films, est ≥ $1M, n=1,225):** log(actual/estimate) median 0.0%, 10–90% range
−3.5%…+3.8%, 5–95% −5%…+5%; no material bias by rounding (round $1M estimates −0.6%), weekend number, or year.
Brackets are 5–25% wide, so the estimate bracket is right only **88%** of the time (244/288 raw).

**Backtest A — model vs market after the Sunday estimate (`boxoffice_bt.py`).** At T (Sun 16/18/20/23 UTC,
Mon 04/12/16 UTC) P(bracket) = empirical estimate-error distribution (only weekends before the event; capped
0.01–0.99); taker entry at the next 3 h of same-direction prints (fallback mid+2c), fee `rate·p(1−p)`, trade
when P − price − fee ≥ θ.

| Decision time | θ | trades | hit | avg px | model edge | realised ROI |
|---|---|---:|---:|---:|---:|---:|
| Sun 16 UTC | 0.03 | 216 | 14.8% | 0.195 | +0.17 | **−25%** |
| Sun 18 UTC | 0.03 | 235 | 16.2% | 0.187 | +0.18 | **−15%** |
| Sun 20 UTC | 0.03 | 240 | 15.4% | 0.174 | +0.19 | **−13%** |
| Mon 04 UTC | 0.08 | 192 | 14.1% | 0.143 | +0.29 | −3% |
| Mon 12 UTC | 0.03 | 258 | 10.1% | 0.114 | +0.22 | −13% |

Every disagreement with the market loses: when the official estimate and the market disagree, **the market is
right** (e.g. Superman 2025-07: WB estimate $122M, market 70% on ">$124M", actual $125.0M; 2026-07-17 weekend:
all Disney/Universal Sunday estimates were 5–8% high and the market already priced the lower bracket). The
market is pricing competitive (rival-studio / Deadline) numbers, not the official estimate alone.

**Backtest B — how fast does the market absorb the weekend's data?** Mean mid of the eventual winning bracket
(254 events), hours after Friday 00:00 UTC: Thu 0.44 → Fri 00 0.50 → Sat 00 0.59 → Sat 18 0.74 → **Sun 06 0.84**
→ Sun 18 0.90 → Mon 06 0.93 → Tue 00 0.99. Buying the bracket that contains the Sunday estimate at Sun 18 UTC:
n=254, hit 88.2%, avg ask 0.882 → **zero edge**. Market favourite at Sun 18: hit 94.9% vs ask 0.931 (+1.6c/sh,
se 1.2c, n.s.).

**The only effect found — overnight Saturday→Sunday favourite underpricing.** Rule (price-only proxy for "the
Saturday-night weekend projection is public but the US is asleep"): at Sun 04–10 UTC buy YES of the favourite
bracket when its executable ask is 0.55–0.95.

| Window | n | avg ask | hit | pnl/share | ROI | $10/trade | $50 (print-capped) | $200 (capped) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Sun 04–10 UTC | 147 | 0.809 | 88.4% | **+7.3c (se 2.5c)** | +9.0% | +$135 | +$644 (71% filled) | +$2,505 |
| Sun 12 UTC | 118 | 0.819 | 88.1% | +6.0c (se 2.8c) | +7.4% | +$85 | +$361 | +$1,523 |
| Sun 18 UTC | 81 | 0.826 | 86.4% | +3.6c (se 3.5c) | +4.3% | +$30 | +$160 | +$393 |
| Sat 18 UTC (after Friday grosses) | 135 | 0.758 | 76.3% | +0.3c | +0.3% | −$10 | +$69 | −$187 |

By year (Sun 04–10): 2024 +12.6c (n=13), 2025 +9.0c (n=57), 2026 **+5.2c** (n=77) — decaying. Worst trades are
full-stake losses at 0.78–0.87 (Bad Guys 2, Karate Kid Legends, Mario Galaxy wk2). Caveats: price-only rule
chosen after scanning ~10 time points (Bonferroni-adjusted p ≈ 0.05); it cannot be tied to a specific
timestamped data release historically (Deadline articles are overwritten). Capacity ≈ $50–200 per event,
~2 events/week → **≈ $10–40/week expected**. Verdict: *no data-lead edge from official numbers; a small,
decaying overnight-repricing effect of a few % at $50–$200 size.*
