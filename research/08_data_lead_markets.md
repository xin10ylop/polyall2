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
