# 10 — Weather "dead bucket" harvesting (observation day): evidence (interim)

Definition: on the observation day, a daily-HIGH bucket whose upper bound is ≤ (running max − margin), or a daily-LOW
bucket whose lower bound is ≥ (running min + margin), can no longer win *if* the METAR record equals the resolution
source. Running extreme computed as-of time t from IEM ASOS obs with availability = obs time + 10 min.

Sample: 2,175 randomly sampled temperature markets (25/day, Jul–Sep 2026 ≈ 2.5% of the universe), real taker prints.

| | margin 1° | margin 2° |
|---|---:|---:|
| dead buckets with any taker NO-buy ≤ 0.99 after death | 31 | 10 |
| such prints / shares | 1,240 / 68,340 | 290 / 17,006 |
| minutes after death (p10 / p50 / p90) | 11 / 94 / 236 | 3.6 / 32 / 84 |
| NO price (p10 / p50 / p90) | 0.50 / 0.957 / 0.989 | 0.86 / 0.937 / 0.989 |
| buckets that nevertheless resolved YES | **1** (Shenzhen 29°C Jul-20: METAR max 30, Wunderground max 29) | 0 |
| P&L of taking every such print (fee incl.) | +$2,699 − $370 = **+$2,329** | **+$956** |

Observations:
* Deterministically dead buckets are usually repriced to NO ≥ 0.999 within minutes (live monitor 2026-09-26: 400+ dead
  buckets per cycle, none with NO ask < 0.999 during 14:44–15:08 and 17:45+ UTC).
* But sporadic, *persistent* mispricings occur (median 32–94 min after the killing METAR), concentrated in a few
  events (Beijing 27°C Sep-20: 10.7k shares at NO≈0.90, 54 min median after death; São Paulo 21°C Jul-6: 3.7k shares
  at 0.989). These are not latency races — a 1–2 minute polling bot sees them.
* The one loss shows the core risk: METAR ≠ resolution source (Wunderground rounding/record differences). Informed
  takers pile into exactly those buckets. A 2° margin removed the loss in this sample, but n is small.
* Economics are lumpy: most profit comes from 1–3 events per quarter in this 2.5% sample; scaling ×40 to the full
  universe suggests ~5 qualifying buckets/day, but capture share vs. the takers who actually traded is unknown.
Next: full-universe replication (weather agent) + live monitor (`src/nowcast/live_nowcast.py`, running).
