# 08 — Data-lead culture/data markets (box office, AI leaderboard, Spotify, Billboard)

*Research date: 2026-09-26. Venue: Polymarket only. Code: `src/datalead/`. Cache: `data/datalead/` (≈230 MB).*
*All backtests are taker-only. Prices are actual taker prints in the 3 h after the decision time (size-capped by
those prints); the fallback is the price-history value + 2c, and the tables report how often it was used. Fee is
`shares × rate × p × (1−p)` with each market's `feeSchedule.rate` (culture 0.05, tech 0.04).*

## 0. Executive summary

| Family | Closed events tested | Look-ahead-safe signal | Result | Size of edge | Capacity |
|---|---:|---|---|---|---|
| **Weekend box office brackets** | 254 (of 308) | BOM Sunday studio estimate (public Sun ~16–17 UTC) | **No edge from the official estimate.** When the model and the market disagree, the market is right (ROI −13…−25%). The only effect is a price-only one: the favourite is underpriced overnight Sat→Sun | Favourite bought Sun 00–10 UTC at an ask of 0.55–0.95: **+5…+8c/share (t≈2.5–3), ROI ≈ +9%**, shrinking (2024 +12.6c, 2025 +9.0c, 2026 +5.2c) | ~$60 deployable per weekend at a $50 cap; **≈$10–40/week** |
| **"Best AI model on <date>" (weekly, arena.ai)** | 23 | HF `lmarena-ai/leaderboard-dataset` version for date D (committed ~D+1 03:00 UTC), used at T−27 h | **Current leader wins 23/23 at 1–3 days out.** The market prices it at 0.90–0.94 when it is below 0.97 | **+9c/share at k = 2–3 days** (13–14 trades, 100% hit, se ≈2c). Too few events (and one regime: Anthropic leading) to call it proven | Printed ask liquidity is **~50–250 shares per event**, so ≈$90 per event, ≈$20–60/week |
| **Spotify weekly #1/#2 (global, US)** | 101 events exist; only 16 are testable with daily data | kworb daily streams (the per-track pages keep only the last ~31 days) | The #1 markets are already at 0.97–0.99 after 1 day of data. In the #2 markets the 1–2-day data leader is right only 44%, and the market does better. Data leader bought when its ask < 0.97: n=35, hit 63%, **−5c/share** | None measurable (tiny sample) | — |
| **Billboard 200 #1 / Hot 100 #1** | 30 + 30 | Billboard's Sunday/Monday top-10 announcements (schedule only: billboard.com's robots.txt disallows our agent) | The winner is at ≥0.95 before Saturday in ~80% of weeks and at 0.99 by the Sunday announcement. No post-announcement lag | None | — |
| MrBeast views, Netflix, outages, GPU index | — | No historical data reachable (Wayback blocked, YouTube API 403, FlixPatrol 403, Ornn dashboard needs a login), or fewer than 20 events | Not tested | — | — |

**Bottom line.** None of these families has a large, clearly proven data-lead edge. Two small effects hold up
out of sample, and both have tiny capacity:
1. Box office: buy the bracket the market already favours overnight Sat→Sun. It is decaying, and together they come to tens of dollars a week.
2. Weekly AI leaderboard: buy the current arena leader 2–3 days before the check.

The reference wallets are consistent with this. KimchiCapital's whole music book (Spotify, Billboard, album sales)
made about $6k on about $100k of notional over 9 months, which is 5–10% ROI at a few hundred dollars a week.

## 1. Family screen and data availability (what can be backtested without look-ahead)

Sandbox egress: `web.archive.org` and `archive.ph` are blocked (so no Wayback snapshots), the GitHub search API is blocked,
`flixpatrol.com` returns 403, and the YouTube Data API returns 403. billboard.com is reachable, but its robots.txt disallows
the `anthropic-ai` agent, so it was not scraped. Reachable: kworb.net, boxofficemojo.com, HuggingFace, the Spotify
public charts endpoint (current chart only), and the Polymarket APIs.

| Family | Closed events found | Resolution source | Historical, timestamp-safe data obtained | Verdict |
|---|---:|---|---|---|
| Weekend box office (opening / Nth weekend) | 308 events, 2024-02 → 2026-09 | The Numbers final 3-day actuals (Mon/Tue) | **Box Office Mojo `/weekend/<YYYY>W<ww>/estimates/`: Sunday studio estimate AND Monday actual for every film** (3,320 film-weekends) | **Backtested** |
| Best AI model (weekly; monthly by company) | 25 weekly + 16 monthly | arena.ai text leaderboard, style control off, 12:00 ET | **HF `lmarena-ai/leaderboard-dataset` `text/full`**: every leaderboard version with its publish date; the HF commit time gives the availability time (~D+1 03:00 UTC) | **Backtested** (weekly) |
| Spotify weekly #1 / #2 | 101 (41 global #1, 38 US #1, 11+11 #2), 2025-11 → 2026-09 | Spotify weekly chart (Fri–Thu), published Friday | kworb per-track pages have daily Global/US streams **only for the last ~31 days**, and weekly data for all history. No archive of daily charts was reachable | Price-profile for all 79 #1 events, data backtest for the last 4 weeks only |
| Billboard 200 / Hot 100 #1 | 33 + 34 weekly (2026) | Billboard chart (Tuesday) | Announcement schedule only | Price-profile |
| MrBeast views (day N / week 1) | ~45 × 5–7 brackets | YouTube view counter at 24/48/72 h | No per-video view history reachable | Not backtestable here |
| Netflix #1 views | ~8 | top10.netflix.com (Tuesday) | FlixPatrol blocked | Too few / no data |
| ChatGPT outage-day counts | 4 monthly | status.openai.com | — | Too few |
| GPU rental index (Ornn) | ~35 | dashboard.ornnai.com daily index | Dashboard needs a login (HTTP 307) | Not accessible |

**Reference-wallet forensics** (`wallet_forensics.py`; fills from data-api `/trades?user=`, with fees charged as if
every fill were a taker fill, an upper bound): KimchiCapital, Jan–Sep 2026:

| Family | Buys | Hit rate | Avg buy price | P&L | Notional |
|---|---:|---:|---:|---:|---:|
| Spotify | 371 | 76% | 0.695 | ≈ +$3.2k | $29k |
| Billboard | 187 | — | — | ≈ +$1.7k | $30k |
| First-week album sales | 492 | — | — | ≈ +$1.3k | $43k |

Most of the Spotify buys were placed **72–168 h before close (Fri–Tue of the chart week) at about 0.73, with about 80%
hit**, which is consistent with reading the first daily charts. Taken together the edge is real but small: 5–10% ROI,
about $6k in 9 months.

## 2. Weekend box office brackets (308 events, 2024-02 → 2026-09)

**Data.** `src/datalead/boxoffice.py` does four things:
- enumerates the events via gamma public-search;
- parses the brackets (the parser was checked: every event's brackets form a partition, with 4 exceptions);
- takes the weekend's Friday from the description;
- joins each event to BOM's weekend *estimates* page.

292 of 308 events matched. 19 multi-day (4/5-day holiday) events were excluded a priori, which leaves **254 usable
closed events with prices**. Polymarket data covers 1,377 markets: `clob prices-history` at 10-min fidelity plus
taker prints from `data-api /trades`.

**How accurate the Sunday estimate is** (all BOM films with an estimate ≥ $1M, n=1,225):
- log(actual/estimate) has a median of 0.0%, a 10–90% range of −3.5%…+3.8%, and a 5–95% range of −5%…+5%.
- There is no material bias by rounding (round-$1M estimates come in −0.6%), by weekend number, or by year.
- Brackets are 5–25% wide, so the bracket that contains the estimate wins only **88%** of the time.

**Backtest A — model vs market after the Sunday estimate** (`boxoffice_bt.py`).
- P(bracket) comes from the empirical estimate-error distribution, using only weekends before the event and capped to 0.01–0.99.
- Trade when P − price − fee ≥ θ.

| Decision time | θ | Trades | Hit | Avg px | Model edge | Realised ROI |
|---|---|---:|---:|---:|---:|---:|
| Sun 16 UTC | 0.03 | 216 | 14.8% | 0.195 | +0.17 | **−25%** |
| Sun 18 UTC | 0.03 | 235 | 16.2% | 0.187 | +0.18 | **−15%** |
| Sun 20 UTC | 0.03 | 240 | 15.4% | 0.174 | +0.19 | **−13%** |
| Mon 04 UTC | 0.08 | 192 | 14.1% | 0.143 | +0.29 | −3% |
| Mon 12 UTC | 0.03 | 258 | 10.1% | 0.114 | +0.22 | −13% |

When the official estimate and the market disagree, **the market is right**. Two examples:
- Superman, 2025-07: the WB estimate was $122M, the market had 70% on ">$124M", and the actual was $125.0M.
- The 2026-07-17 weekend: every Disney and Universal Sunday estimate was 5–8% high, and the market had already priced the lower bracket.

The market is pricing rival-studio and trade-press numbers, not just the official estimate.

**Backtest B — how fast the market absorbs the weekend's data.** Mean mid of the eventual winning bracket
(n=254), by time relative to Friday 00:00 UTC:

| Time | Thu | Fri 00 | Sat 00 | Sat 18 | **Sun 06** | Sun 18 | Mon 06 | Tue 00 |
|---|---|---|---|---|---|---|---|---|
| Winner mid | 0.44 | 0.50 | 0.59 | 0.74 | **0.84** | 0.90 | 0.93 | 0.99 |

- Buying the bracket that contains the Sunday estimate at Sun 18 UTC: n=254, hit 88.2%, avg ask 0.882. **Zero edge.**
- Buying the market favourite at Sun 18 UTC: hit 94.9% against an ask of 0.931. That is +1.6c/share with se 1.2c, not significant.

**The one effect found: the favourite is underpriced overnight Saturday→Sunday.** The rule is price-only: at the
decision time, buy YES of the favourite bracket if its executable ask is 0.55–0.95. It is a proxy for "the
Saturday-night weekend projection is public, but the US is asleep".

| Window | n | Avg ask | Hit | P&L/share | ROI | $10/trade | $50 (print-capped) | $200 (capped) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Sun 00–04 UTC | 157 | 0.787 | 87.3% | **+8.3c** (se 2.5c) | +10.5% | | | |
| **Sun 04–10 UTC** | 147 | 0.809 | 88.4% | **+7.3c** (se 2.5c) | +9.0% | +$135 | +$644 (71% filled) | +$2,505 |
| Sun 12 UTC | 118 | 0.819 | 88.1% | +6.0c (se 2.8c) | +7.4% | +$85 | +$361 | +$1,523 |
| Sun 18 UTC | 81 | 0.826 | 86.4% | +3.6c (se 3.5c) | +4.3% | +$30 | +$160 | +$393 |
| Sat 18 UTC (after Friday grosses) | 135 | 0.758 | 76.3% | +0.3c | +0.3% | −$10 | +$69 | −$187 |
| Sat 06 UTC | 130 | 0.737 | 74.6% | +0.6c | +0.8% | | | |

**Robustness** (Sun 04–10 UTC rule):
- Entry window of 1 h: +5.2c. Entry window of 6 h: +7.2c.
- Price band 0.5–0.9: +6.5c. Band 0.7–0.95: +6.5c. Band 0.55–0.98: +6.6c.
- By year: 2024 +12.6c (n=13), 2025 +9.0c (n=57), 2026 **+5.2c** (n=77). The effect is decaying.
- Since 2025-07: n=110, +5.8c (se 3.0c).

**Consistency:** 83 weekends, 83% of them profitable. The worst weekend lost $28 at a $10 stake. The worst single trades
are full-stake losses on favourites bought at 0.78–0.87 (Bad Guys 2, Karate Kid Legends, Mario Galaxy weekend 2).

**Capacity:** about 1.8 trades and about $60 deployable per weekend at a $50 cap. Printed asks thin out above ~$200 per event.

**Caveats:**
- It is a price-only rule, chosen after scanning ~10 time points, so the Bonferroni-adjusted p is about 0.05.
- It cannot be tied to a timestamped data release historically, because Deadline rewrites its weekend articles.
- A live version should parse the Saturday-night projection and buy only when the favourite agrees with it.

**Verdict:** there is no data-lead edge from the official numbers. There is a small, decaying overnight-repricing
effect worth **≈$10–40/week**.

## 3. "Best AI model on <date>" (weekly, arena.ai text, style control off)

**Data.** `lmarena-ai/leaderboard-dataset` (`text/full`, filtered to the `overall` category; the HF commit time for version D is ~D+1 03:00 UTC):
- The overall leader history: gemini-3-pro from 2025-11-16; claude-opus-4-6(-thinking) from 2026-02-06; claude-opus-5-high/max from 2026-07-26 (the two alternate); claude-fable-5.1-max from 2026-09-02; **claude-opus-5.5-high from 2026-09-25**.
- Model names are matched exactly to market outcomes. A leader that is not listed maps to "Other", because the rules say no models are added after creation.

**Rule** (`aimodel_bt.py`): at T = the resolution check (12:00 ET on the date) minus k days, take the leader of the
newest dataset version with publish date ≤ T − 27 h, and buy YES on its outcome if the ask is in [0.5, 0.97].

| k (days before check) | Events | Leader wins | Avg ask (all) | Trades (ask 0.5–0.97) | Hit | P&L/share | $10 | $50 capped | $200 capped |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 23 | **23/23** | 0.962 | 10 | 100% | +7.5c (se 1.3c) | +$8 | +$30 | +$100 |
| 2 | 23 | **23/23** | 0.940 | 13 | 100% | **+9.2c** (se 2.1c) | +$14 | +$56 | +$168 |
| 3 | 23 | **23/23** | 0.932 | 14 | 100% | +10.0c (se 1.8c) | +$17 | +$57 | +$108 |
| 7 (market favourite) | 19 | — | 0.837 | — | 79% | −5.3c | | | |

**Persistence and latency.** The market reprices within about an hour of a leaderboard update. For example, "Other"
(claude-opus-5.5-high) in the Sep-28 market went 0.29 → 0.93 at 2026-09-26 03:00 UTC, the same time as the HF
commit. So this is **not** a latency edge. It is a persistence premium: traders price a 6–10% risk of a leader flip
in the last 2–3 days, and in 23 weeks it never happened at k ≤ 3.

**Risks.** It is 23 events from one regime (Anthropic variants leading), and the Clopper–Pearson lower bound on
23/23 is 85%. Near-tied variants (opus-5-high vs max, ~1 Elo apart) flipped the weekly winner twice in August;
the rule survived because it re-reads the data at T. A frontier release in the last 72 h would cost the whole stake.

**Capacity:** printed ask volume within 3 h is median ~50 shares, mean ~250, so about **$90 per event** at a $200
cap. That is one event per week, plus the monthly company markets, which are efficient at ≥0.98 in the last 3 days.

## 4. Spotify weekly #1 / #2

**Price profile, all closed events** (mid of the eventual winner at 12:00 UTC on day d of the Fri–Thu chart week):

| Market | Day 1 | Day 2 | Day 3 | Day 4 | Day 5 | Day 6 | Day 7 |
|---|---|---|---|---|---|---|---|
| Global #1 (n≈38) | 0.63 | 0.73 | 0.82 | 0.87 | 0.94 | 0.97 | 0.98 |
| US #1 (n≈35) | 0.64 | 0.74 | 0.76 | 0.85 | 0.89 | 0.95 | 0.94 |

Buying the market favourite loses early in the week (global days 1–3: −8 to −4c/share). From day 5 onward it is
about fair (+1 to +3c, not significant).

**Data backtest (the last 4 chart weeks only)**, with daily chart D assumed usable from D+2 00:00 UTC. A poll of kworb
and the Spotify public endpoint on 2026-09-26 still showed 09-24 as the newest daily chart at 18:10 UTC; the
publication log is in `data/datalead/spotify_publish_times.log`.
- **#1 markets:** the data leader was already the market favourite at 0.97–0.99 from day 1, and won 48/48 observations. There is nothing to capture.
- **#2 markets:** the leader after 1–2 known days was right only 7/16 times (margins of 0.1–2%). The market favourite did better.
- Rule "buy the data leader when its ask < 0.97": n=35 (11 events), hit 63%, **−5c/share**.

**Why the wallet can still make money here.** It trades before and around new releases (album drops on Fridays)
and uses judgement about decay. That is not captured by a mechanical projection from 1–2 days of data. Spotify has no
backtestable data-lead edge with the data available here.

**Recommendation:** start a daily kworb archiver now (it is cheap) if this family is to be revisited. It needs 20+ weeks of self-recorded daily charts.

## 5. Billboard 200 #1 / Hot 100 #1

The markets close Monday evening UTC, after Billboard's Sunday (Billboard 200) and Monday (Hot 100) top-10 stories.

**Mean mid of the eventual winner**, by time relative to the Sunday of the announcement week (00:00 UTC):

| Market | −24 h | Sun 00 | Sun 20 | Mon |
|---|---|---|---|---|
| Billboard 200 | 0.94 | 0.96 | 0.99 | 0.99 |
| Hot 100 | 0.93 | 0.98 | 0.99 | 0.99 |

In 25/32 Billboard 200 weeks and 25/31 Hot 100 weeks, the winner was already ≥0.95 before Saturday 00:00 UTC (17 of each were already there by Friday 00:00 UTC).

Favourite calibration from Tuesday to Monday is flat. For example, Billboard 200 at Wed 00: 24 events, favourite
priced 0.87 with 92% hit. At Sat 12: 30 events, 0.95 with 93% hit. **No post-announcement lag and no measurable pre-announcement mispricing.**
The early edge, if any, lies in mid-week sales projections that are not archived.

## 6. Executability now (order books, 2026-09-26 ~18:10 UTC; `live_books.py`, snapshot saved in `data/datalead/live_books_*.json`)

- **AI, Sep-28 market:** "Other" (= claude-opus-5.5-high, the leader since the 09-25 dataset version) is at 0.98/0.99 with $376 within 3c. The Sep-28 market is already fully priced.
- **AI, Oct-5 market:** "Other" is 0.84/0.89 with $240 of depth. The k ≤ 3 d rule would act on Oct 2–4 if opus-5.5-high still leads.
- **Box office, weekend of Sep 25–27:** there are 5 open events. Spreads are 1–10c, and depth within 3c of the ask runs from $2 to $2,860 (Forgotten Island "<13m" 0.73/0.79 with $2,861; Primetime "19–22m" 0.61/0.64 with $39; Heart of the Beast 17–20m/20–23m at 0.52/0.62 and 0.39/0.43). The overnight rule would fire at Sun 00–10 UTC on 2026-09-27 for any favourite at 0.55–0.95.
- **Spotify, Oct-2 markets:** #1 is decided in practice (Patient Zero, 0.935–0.98 bid / 0.998 ask). The #2 books are thin ($1–46).
- **Billboard, Oct-10 markets:** a few dollars per level.

## 7. Methodology and look-ahead controls

- **Signal timestamps:**
  - BOM Sunday estimates are used only from Sunday 16:00 UTC or later.
  - LMArena versions are used only 27 h after their publish date. The HF commit is ~D+1 03:00 UTC.
  - Spotify daily chart D is used from D+2 00:00 UTC.
- **Model calibration** (box office): the estimate-error distribution uses only weekends strictly before the event.
- **Entries:** taker only, at the next same-direction prints (YES-buy = BUY YES or SELL NO mirrored), with size capped by those prints. The fallback is mid + 2c, and it is reported.
- **Survivorship:** every closed event returned by gamma public-search for each family was included. The only exclusions were a priori: 4/5-day holiday windows, unparseable brackets, and missing BOM rows. There were 11 BOM-vs-The-Numbers definition mismatches; the outcome used is always the market's own resolution.
- **Multiple testing:** the box office overnight rule came from a scan of ~10 decision times and 5 price bands. Treat it as a hypothesis with modest evidence (t≈2.9, decaying), not a proven edge.

## 8. Files

- `src/datalead/`:
  - discovery: `discover.py`, `wallets.py`, `wallet_forensics.py`
  - Polymarket data: `pm_fetch.py`, `fetch_pm_family.py`, `pmdata.py`
  - box office: `boxoffice.py`, `boxoffice_bt.py`
  - AI leaderboard: `aimodel_bt.py`
  - Spotify: `kworb.py`, `spotify_build.py`, `spotify_bt.py`, `watch_spotify_publish.sh`
  - Billboard: `billboard.py`
  - live order books: `live_books.py`
- `data/datalead/`:
  - event JSONs and `*_markets.json`
  - `bom/` (weekend estimate pages) and `bom_est_all.parquet`
  - `kworb/` and `kworb_all.parquet`
  - `lmarena/`
  - `pm/ph`, `pm/tr`
  - backtest outputs: `bt_boxoffice_*.csv`, `bt_aimodel.csv`, `bt_spotify_recent.csv`
