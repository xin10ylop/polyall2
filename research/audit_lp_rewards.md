# Audit — liquidity-reward (LP) farming for a $100–$1,000 account

Independent, skeptical audit of the thesis "post small two-sided post-only quotes near the mid in low-competition
rewarded markets (esp. daily weather temperature buckets), earn Polymarket liquidity rewards, manage adverse selection".
Date: 2026-09-26 (Saturday). All data pulled live today; no orders placed. Scripts: `src/audit/`; cached data: `data/audit/`.

**One-paragraph answer.** The reward-share formula in `sim_lp.py` is implemented correctly. The ~$1,000/day on ~$700 headline
comes from **scenario** optimism, not an arithmetic bug. It rests on 22–50 minutes of Saturday-afternoon books, in-sample
top-30 selection, invented mids on one-sided books, markets whose observation day is already running, non-daily markets,
and, above all, minutes where our quote would be the *only* one within the max spread (inside a ~21¢-wide book). The
simulator also prices **zero** adverse selection. Structural corrections cut it to ≤ $350–400/day on ~$585 of quote
capital, and that figure is still an upper bound. Wallet ground truth is decisive. Across 158 LP-dominated wallets over
30 days, trading losses (the user-pnl-api *excludes* rewards, verified) eat a median **81 %** of rewards. For the 43 of
them under $1.5k, the median is **88 %**. Their median **net** is **+0.4 %/day of capital** (p10 −2.2 %, p90 +6.6 %), and
one third lose money. LP farming is real and some small wallets make money. As a *passive, uninformed* strategy it is
roughly zero-to-thin EV with fat left tails. The 30× gap between the simulator and reality is explained below. Section 4
describes a "safe version": a gated live experiment, not a scaled deployment.

**Update after the lead's follow-up evidence (section 5).**
- **`market_competitiveness` is on a different scale from Σ Q_min.** It is *not* a usable reward-share denominator. It sits
  below a hard lower bound on Σ Q_min in 96 % of testable markets (median 8 % of that bound). Using it inflates a 20-share
  quote's share from ~14 % to ~78 %.
- **The tradetosurvive1 and PPMT monthly reward figures are confirmed.** Both wallets keep only ~45–55 % (0x30fb41b5) and
  ~85 % (PPMT, but it has $30k of capital: 0.4 %/day) of rewards after trading P&L.
- **The local-time AS table is directionally right but ~1.2–2× too pessimistic in magnitude.** The cause is a fill-size
  bug. More importantly, it measures only *historical* flow.
- **Decisive new test.** LP wallets whose maker fills in *closed* temperature events are mostly (> 80 %) *before* the
  local observation day hand back **~90 % of rewards** (pooled 0.90, median 0.91), no better than undisciplined ones.
- **Final calibrated estimate** for a disciplined small LP that stops at local midnight before D:
  - gross rewards ≈ 4–5 %/day of capital;
  - net ≈ **+0.25 to +0.4 %/day median** (IQR ≈ −0.8 % to +0.9–2 %/day);
  - ~40 % chance a given month is negative;
  - upward-biased by survivorship.
  - On $1,000 that is ≈ **+$3/day median**, not $1,000/day.

---

## 1. Bugs and optimism biases in the simulators

### 1a. `src/live/sim_lp.py` + `src/live/lp_report.py` (reward share on recorded books)

Things that were checked and are **correct** (not the cause):

| Suspicion | Finding |
|---|---|
| Quadratic score / units | `S()` (L28) uses `v` and `s` in cents, `((v−s)/v)²`, as documented. OK. |
| YES vs NO books, double counting | `POST /books` for the YES and NO tokens returns exact mirrors (verified today on 4 markets: NO bids = 1 − YES asks, same sizes). So the YES book already contains NO-token orders, and `q1` = YES bids + NO asks = Q_one, `q2` = Q_two. No double count, nothing missing. |
| Competitor aggregation (L97–99) | Using `max(q1,q2)` for "all competitors" is a genuine **upper bound** on Σ competitors' Q_min: for mid∈[0.1,0.9], Q_min,n ≤ max(min, max/3) ≤ (Q1n+Q2n)/2, so Σ ≤ max(ΣQ1, ΣQ2). Conservative, as claimed. |
| Sub-min-size competitor orders | Counted as scoring, which is conservative for us. |
| `rate` units | `rate_per_day` is in $ (811/818 weather configs pay USDC.e, 7 pay pUSD); one config per market; Σ weather ≈ $20.6k/day. Magnitudes match observed payouts (e.g. $4.5k/day to one wallet). |
| Reward pool shared across token pairs | No. The pool is per condition, and Q_one/Q_two already merge both tokens. |

What **is** wrong or optimistic. The decomposition comes from `src/audit/sim_lp_audit.py` run on the recorder data at
14:07–14:56 UTC; the shares are of the reproduced top-30 reward:

| # | Issue (code) | Effect |
|---|---|---|
| B1 | **Invented mid on one-sided books.** L79–80 set `abb = aba − 2v` (or `aba = abb + 2v`) when a side has < min_size, then quote around that fictional mid. The real `/midpoint` for such a book is e.g. ask/2 (0.365 for a book with no bids and ask 0.73). Whether the reward engine scores these at all is unknown. | **35–39 %** of top-30 reward (all four "biggest earthquake Sept 26" markets are here, share 1.00, `bb=None`). |
| B2 | **Sole-scorer minutes.** L83–88 put our quote at m0 ± d *inside* the adjusted book. When the adjusted book is wide (median **21¢** in these markets vs 3¢ in contested ones), nobody else is within v of the new mid, so share = 1. The simulator treats this as free money. It is really an uninformed 2¢-wide market in a 2-day-ahead temperature bucket centred on the midpoint of a 12¢/33¢ book: exactly the stale quote that forecast-model traders pick off. Historical prints cannot show that flow, because those takers never traded at 12¢/33¢. | **63–71 %** of top-30 reward. Top-30 median share **0.97–0.99**; the sim claims **76–85 % of those 30 markets' entire pools**. 19/30 of the corrected top-30 had **zero** maker fills by any known farmer in the last 24 h, and the median market had **1** taker print/24 h. These are brand-new (~55 h before endDate) quiet markets. |
| B3 | **"≥12 h before endDate" ≠ "before the observation".** L72–73 / `lp_report.py` L8 use `endDate`. For temperature markets that is 12:00 UTC of date D. For UTC+8…+13 cities the local day D ends at or before endDate, so hte ≥ 12 h still includes the local observation day (Tokyo/Seoul daily **lows** are observed ~15 h before endDate; Wellington's day D was already 3 h old at 14:00 UTC). Earthquake/rain "on Sept 26" markets have endDate 09-27 18:00, so they pass hte ≥ 24 h while the event is in progress. | **42–43 %** of top-30 reward is from markets whose (local) observation period had already started. |
| B4 | **Non-daily markets mixed in.** The recorder (`recorder.py` L51–69) loads every rewarded `weather`-tag market: hurricanes ("Nolo peak at Cat 4"), river levels, West-Nile counts, monthly precipitation, earthquakes. These have different, often *more* toxic, information flow (NHC advisories, USGS feeds). | **41–43 %** of top-30 reward. |
| B5 | **In-sample top-30 selection** (`lp_report.py` L12–14): ranks ~700 markets by realised share and scores the winners on the same minutes. | Small on a 50-min window (split-sample: $420 → $354/day in the corrected universe). It cannot be tested properly until the recorder has days of data. |
| B6 | **Extrapolation** (`lp_report.py` L5, L10): `reward/span*24` with span = **0.37 h** (23 snapshots) when the claim was made, **0.82 h** now. One Saturday 14:07–14:56 UTC window is scaled ×30–65, ignoring time-of-day competition and model-release cycles. | Unquantified. Treat any per-day number from < 3 days of recording as anecdotal. |
| B7 | **No P&L at all.** Fills are collected (L106–115) but never priced. `lp_report.py` prints gross reward only. The docstring (L13) says "Inventory is tracked; fills are marked at the final outcome", but `outcomes`/`max_inv` are unused. | The headline is **gross** reward with zero adverse selection. |
| B8 | **Capital = quote collateral only** (L104, last sample). It ignores inventory from fills (the historical sim fills 30–130 shares/market-day even at 20-share quotes, capped at 60 net). Realistic capital is ~2–3× the reported $585–741. Conversely, at mid < 0.10 an ask can be backed by cheap YES tokens (capital ≈ 2·p·N, not N), because the score is **share**-denominated. That is why some tiny wallets post huge reward/capital ratios. | Reward/$ overstated ~2× for mid-priced buckets. |
| B9 | Minor: `last_ts` is only updated on quoted samples, so after skipped samples the next one is credited up to 5 min (L100–101). The recorder samples on a fixed ~60 s clock, not a random offset. Trades are polled at `limit=500` per 40 markets per 2 min (can truncate in busy periods). | Small. |

Progressive correction (d = 1¢; d = 2¢ in brackets). Rows 3 and 4 are still **upper bounds**:

| Universe / assumption | Top-30 reward/day | Quote capital |
|---|---:|---:|
| Reproduction (hte ≥ 12 h, in-sample) | $1,184 ($1,112) | $741 |
| − one-sided books | $923 ($854) | $742 |
| + daily temperature only, ≥ 12 h before **local** observation day | $645 ($631) | $586 |
| + when we would be sole scorer, a rival farmer matches us (share ≤ 0.5) | $405 ($370) | $586 |
| same, top-30 chosen on 1st half, evaluated on 2nd half | $354 ($341) | ~$586 |

For context, the entire ≥ 12 h-pre-observation daily-temperature pool is **$6.96k/day across 319 markets** (mean $17–26
per market vs $79 on the observation day). Only **$1.1k/day (16 %)** of it currently sits in markets with no competing
quote within v. The sim's per-market take for the corrected top-30 (~$12–14/market-day) is 5–10× what real small farmers
earn per market they are filled in (~$1–3/market-day, section 2).

### 1b. `src/live/hist_quote_as.py` (historical adverse selection)

| Suspicion | Finding |
|---|---|
| Is `prices-history` `p` a midpoint or last trade? | **Midpoint.** 1,200 minute-matches against the recorder's live books: 92.5 % equal to the book mid (MAE 0.0009) vs 4.9 % equal to last-trade price. Among spreads > 10¢, 84 % match the mid and 0 % match LTP. The preceding ph point matches better than the following one, so there is **no look-ahead**. Caveat: on one-sided books the "mid" is an artefact (ask/2-style), and quotes around it are fictional. |
| Side mapping / NO normalisation (L34–36) | Correct: taker BUY YES or SELL NO means our ask is hit; `p_yes = 1 − p_no`. Trades are taker-only (`fetch_trades.py` uses the default `takerOnly=true`). The 10k-row cap was hit by 0/2,175 markets. |
| Resolution P&L (L67) | Correct (`cash + inv·y`). The audit version also drops unresolved/50-50 markets. |
| **Fill size ignores print size** (L61, L65) | **Bug.** Every crossing print fills the full N = 20 shares, even a 1-share print, and the order is instantly replenished within the minute. With fills capped by print size and depleting per minute (`src/audit/hist_as_audit.py`), filled shares fall ~1.4–1.9× and $AS ~1.5–2× in pre-observation windows. |
| **Ask side gated on `bid > 0`** (L60) | **Bug.** Tails with p < d were never quoted on either side. Fixed in the analyst's `hist_quote_as2.py` and in the audit version. |
| Windows by `endDate` (L50–51) | Same B3 problem. The audit uses hours to the **local** observation-day start (`h_obs`, 53-city UTC-offset table). |
| **Counterfactual informed flow** (not in code) | Only takers who traded against the *historical* book are replayed. A 2¢ quote inside a 20¢ book attracts takers with a 3–10¢ model edge who never traded before. So the sim's AS is a **lower bound** on magnitude, and most so for exactly the sole-scorer markets the reward sim loves. |

Corrected historical AS (2,175 resolved weather markets Jul–Sep 2026, 20-share quotes, inventory cap ±60, hold to
resolution, "through" fills, size-capped). Per market-day, with per filled share in brackets:

| Window (local obs day) | d = 1¢ | d = 2¢ | Original script (hte-based, d = 1¢) |
|---|---:|---:|---:|
| ≥ 24 h before | −$1.25 (−1.4¢/sh, 91 sh/day) | −$0.85 (−1.6¢/sh) | ≥ 24 h: −$2.42 |
| 12–24 h before | −$0.60 (−0.8¢/sh) | −$0.27 (−1.0¢/sh) | 12–24 h: −$2.63 |
| 0–12 h before | −$0.53 (−0.5¢/sh) | −$0.51 (−1.3¢/sh) | 0–12 h: −$15.44 |
| observation day | −$7.22 (−2.3¢/sh, 320 sh/day) | −$5.08 (−2.6¢/sh) | −24–0 h: −$11.21 |

Spread capture is always positive (+$0.6 to +$1.5/market-day pre-obs) but markout is larger and negative. Cross-check on
**all actual maker fills** (`src/audit/maker_fill_pnl.py`, resolution P&L before rewards): observation day +0.03¢/share,
12–24 h pre −0.69¢, 24–48 h pre −0.29¢. Market-clustered ≥ 12 h pre is −0.32¢/share (t = −1.3). Makers as a *population*
roughly break even before rewards. Because informed weather makers inside that population earn money (e.g.
0x21ffd2b7 +$6.5k/day PnL in 30d), uninformed LPs must be on the losing side.

---

## 2. Calibrated reward income and net P&L — wallet ground truth

Method (`src/audit/wallet_ground_truth.py`):
1. Found **1,820** maker wallets in the 818 currently rewarded weather markets (data-api `/trades` `takerOnly=false` minus `takerOnly=true`).
2. Profiled the 331 with ≥ 20 maker fills in ≥ 5 markets: REWARD and MAKER_REBATE activity, `/value`, on-chain pUSD + USDC.e cash (Polygon publicnode RPC), and user-pnl-api.
3. Capital = cash + position value, snapshot today.

**Does user-pnl-api exclude rewards? Yes, verified three ways.**
1. For 0x30fb41b5, the 00:00-UTC hourly changes are +76, −621, +22, −211, +87, −242: no +$4.5k jump.
2. Across 40 wallets earning ≥ $30/day, regressing the excess 00:00-hour PnL change on the daily reward gives a slope of **0.04** (1 would mean included, −1 subtracted).
3. Per-market realised PnL from `/closed-positions` (which cannot contain rewards) tracks the user-pnl-api change, e.g. 0x1ef01de8: API −$6.8k/7d vs closed-positions −$8.8k/7d, against $8.7k of rewards.

So **net = rewards + ΔPnL**.

The five example wallets (7-day or 30-day, $/day):

| Wallet | Rewards | Trading PnL | Net | Capital (cash + pos) |
|---|---:|---:|---:|---:|
| 0x30fb41b5 | 4,470 | −3,378 (1w) / −1,822 (1m) | +1.1k to +2.6k | $118k |
| 0x758dac51 | ~200–290 | volatile | — | — |
| 0x510f4963 | ~140 | ~flat | ~+140 | — |
| 0x29a50829 | ~21 | — | — | $4.6k positions |
| 0x04586f5d | 21 (7d avg; 30–48 since 09-23) | −5.5 (1w) / **−41.7 (1m)** | 30d: **≈ −$1,040 net** on ~$727 | $727 |

The "small wallet earning $30–48/day since 09-23" is **deeply negative over the month** (−$1,234 PnL vs ~$194 of
rewards). Its last 4 days were positive.

30-day population (243 wallets with ≥ $1/day rewards):

| Group | n | Median rewards/capital | Median loss/reward | Net/capital p10 / p50 / p90 | Share net > 0 |
|---|---:|---:|---:|---:|---:|
| Capital < $500 | 26 | 6.0 %/day | 0.91 | −12.8 / +0.3 / +3.3 %/day | 58 % |
| $500–1.5k | 34 | 1.5 %/day | 0.81 | −1.7 / +0.5 / +6.6 %/day | 68 % |
| $1.5k–5k | 64 | 0.6 %/day | 0.72 | −4.3 / +0.7 / +9.7 %/day | 70 % |
| $20k+ | 46 | 0.2 %/day | 0.10 | −0.1 / +0.6 / +4.1 %/day | 83 % |
| **LP-dominated** (\|PnL\| ≤ 3× rewards) | 158 | 2.0 %/day | **0.81** (IQR 0.43–1.01) | −0.7 / +0.4 / +3.2 %/day | 73 % |
| **LP-dominated, capital < $1.5k** | 43 | 5.5 %/day | **0.88** (IQR 0.65–1.15) | −2.2 / **+0.4** / +6.6 %/day | 67 % |

Pooled over the LP-dominated wallets, rewards are $46.3k/day and trading PnL −$23.1k/day, so they keep **~50 %** of rewards.
The small ones keep **~21 %** ($3.0k rewards, −$2.4k PnL). These 243 wallets collect ~$48.5k/day, i.e. **~36 % of the
entire $135k/day program**.

**Per filled share** (40 LP-dominated wallets under $2k, 7 days, non-truncated): rewards **+3.25¢**, trading PnL
**−2.74¢**, which is −6 % of maker notional. 30 % of their $ volume is *taker* flow (inventory unwinds). Realistic
reward per market they are filled in is **$1–3/market-day**, versus the sim's $12–40.

**Calibrated estimate for a new small uninformed maker:**
- **Gross rewards:** ≈ 2–6 %/day of capital. The distribution is wide: p90 ≈ 30 %/day, and the single best small wallet (0x1ef01de8: ~$1.1k capital, $1.24k/day) roughly equals the sim's claim. That wallet recycles capital by merging YES+NO sets ($62k merged/7d) and still gives back 35–80 % in trading losses.
- **Net after adverse selection:** ≈ +0.3 to +0.5 %/day median. That is $0.3–0.5/day on $100 and $3–5/day on $1,000, with a ~1/3 chance of being negative over a month and a p10 of about −2 %/day.
- **Biases in this estimate:**
  - Survivorship (only currently active wallets) overstates it.
  - Selection on being filled understates it.
  - Rewards are wallet-wide across all categories.
  - Capital is a single snapshot.
- ~~A careful operator who never quotes the observation day could beat the median.~~ Tested in section 5.4: wallets
  whose weather maker fills are > 80 % pre-observation-day hand back ~90 % of rewards, the same as everyone else.
  "Discipline" in timing alone does not separate winners from losers. Only a forecast-informed quote centre remains an
  untested source of edge.

---

## 3. Failure modes

1. **Stale-quote pick-off (dominant).**
   - The reward is highest exactly where the book is wide and nobody else quotes. The book is wide because fair value is uncertain.
   - Every NWP cycle (GFS 00/06/12/18Z, ECMWF 00/12Z, hourly NBM/HRRR) moves 2-day-ahead bucket probabilities by several cents. METARs make the outcome observable in real time on the observation day (the METAR daily max matches the winning bucket in 99.6–99.8 % of events, `03_weather_markets.md`).
   - Without a model you are the counterparty of the model traders.
2. **Competition / crowding.**
   - Reward pools and books are public. The "unclaimed" $1.1k/day of pre-observation pools is visible to 257+ farmers, some with $100–300k capital.
   - Your share shrinks as soon as a farmer notices. The best small farmers already earn 20–100 %/day gross, and the median only 3 %.
3. **Program changes.**
   - Pools are discretionary and re-issued per market (713/818 weather configs started today).
   - `rewardsMinSize` moved 50 → 20 between May and Aug-2026.
   - The $1M Aug crypto-TWAP pools ended, and 2024-election pools were cut (the poly-maker author stopped).
   - Closed markets lose their `clobRewards`, so **reward income cannot be backtested historically**.
   - An undocumented `moas: 30` (possible 30 s minimum order age) and ≥ 3.5 s rest rule defeat "flicker" quoting.
4. **Capital lock-up.**
   - Fills create inventory (30–130 shares/market-day at 20-share quotes) that is locked until merge or resolution.
   - Resolution is ~10–12 h after endDate, and "clearly erroneous" data can delay it up to 7 days.
   - Balance is reserved by open orders (`maxOrderSize = balance − Σ open`), so capital cannot be re-used across markets.
5. **Resolution / rule risk.**
   - Station changes (Paris LFPG→LFPB, three Taipei station changes), boundary cases (0.2–0.4 %), and UMA disputes (~1 %).
   - Held-to-resolution inventory carries all of this.
6. **Ghost fills.**
   - Off-chain matches can fail on-chain (MATCHED → FAILED). Shen et al. (2026) document attacker-reverted fills used partly for reward manipulation on the V1 exchange; whether CLOB V2 closes this is **uncertain**.
   - Reconcile every fill against CONFIRMED status, and never hedge on MATCHED.
7. **Geoblock / legal (hard blocker).**
   - `polymarket.com/api/geoblock` returns **blocked (US-IL)** for this machine. The US is close-only for frontend *and* API.
   - A VPN violates the ToS. Polymarket US is a different venue, and whether it runs an equivalent LP program was not researched.
   - Without an eligible person in a permitted jurisdiction the strategy is **not executable** at all.
8. **Operations.**
   - Needs a 24/7 bot with heartbeats (open orders are auto-cancelled if heartbeats stop).
   - Must cancel around model releases and match-engine restarts (post-only for 2 min).
   - Payouts have a $1/day minimum. At $100 the infrastructure and time cost exceeds the expected ~$0.3–0.5/day.

---

## 4. Verdict and a safe version

**Verdict.**
- LP-reward farming is a *real* income stream: 243 identifiable wallets, many with < $1.5k, collect rewards daily.
- For an **uninformed, passive** small maker it is **not reliably positive-EV**. The best estimate is a thin positive median (≈ +0.4 %/day) with a heavy left tail, and one third of comparable wallets lose money over 30 days.
- Stopping at local midnight before the observation day does **not** change this in the wallet data (section 5.4): ~90 % of rewards are still handed back, and the net is ≈ +0.25 %/day median for < $1.5k.
- The simulator's ~$1,000/day on ~$700 is **~25× too high on gross** and **~300× too high on median net**. It is not "executable, same live as in test": it assumes being the only quote inside 21¢-wide books with no adverse selection.
- **Not executable from a US/IL location at all.**
- For $100: not worth it except as a measurement exercise. For $1,000: only as a gated experiment.

**Safe version (only if an eligible, non-geoblocked account exists):**
1. **Universe:** daily temperature buckets, **≥ 24 h before the *local* observation-day start** only. No earthquake, rain, hurricane, river or disease markets. No one-sided books.
2. **Price from a model, not the book.** Centre quotes on the project's forecast probability (ECMWF/NBM features in `src/weather/`). Quote only where |model − book mid| ≤ 2¢; otherwise that is a *taker* signal, not an LP opportunity. Do **not** be the sole 2¢ quote inside a 20¢ book unless the model agrees.
3. **Join, don't lead.** Quote at the best contested level (1–2¢ from the adjusted mid) at exactly `rewardsMinSize`.
4. **Pull quotes around information events:** ±10 min around NWP availability times; on any trade-through; at local midnight of the observation day (flatten or merge before then). Use heartbeats as a dead-man switch.
5. **Inventory:** net cap ≤ 2× min size per market and ≤ 25 % of capital across correlated buckets of one city-day (neg-risk event). Merge YES+NO immediately. Budget taker-exit cost (spread + 0.05·p(1−p) fee).
6. **Measure before scaling.** Start with $200–300 in 10 markets for 14 days.
   - Verify scoring via authenticated `/order-scoring` and `/rewards/user/percentages`.
   - Reconcile daily: REWARD activity vs user-pnl-api (which excludes rewards) vs fill markouts at 1 h / 6 h / resolution.
   - **Kill** if 14-day net < 0, if realised reward is < 50 % of the (corrected) simulator's prediction, or if loss/reward > 0.8.
   - Scale ×2 only after net > 0 with a market-day-clustered t > 2 over ≥ 30 market-days.
7. **Simulator fixes before trusting any number:**
   - Run `src/audit/sim_lp_audit.py` on ≥ 3 full days of recorder data (all hours).
   - Add a P&L leg to the reward sim (fills priced to resolution, as in `hist_as_audit.py`).
   - Report reward per **market-day** and per **filled share** so it is directly comparable to the wallet ground truth ($1–3/market-day, +3.3¢ reward vs −2.7¢ AS per filled share).

---

## 5. Verification of the lead's follow-up evidence, and the final calibrated estimate

### 5.1 `market_competitiveness` is NOT Σ Q_min, so do not use it as the share denominator

Test: `src/audit/competitiveness_check.py`, 687 two-sided rewarded weather markets, `market_competitiveness` and
`/books` fetched back-to-back, repeated 120 s apart.
- **It is computed from the live book.** It changed in 62 % of markets within 120 s, the same rate as the book score. Its
  rank correlation with my aggregate book Q_min is **0.68 (Spearman), 0.70 (log-Pearson)**. The lead's 0.93 is probably
  a raw-value Pearson driven by a few huge markets. So it is useful for **ranking** markets by competition.
- **It is on a different scale.** Median comp/Q_min = **0.039** (IQR 0.021–0.097). The ratio is price-dependent: 0.022 at
  mid 0.3–0.7, 0.16 at mid < 0.1, 0.33 at mid > 0.9. Neither a per-order min-size filter nor a raw vs adjusted mid
  explains it (all variants 0.013–0.11).
- **Hard lower-bound test.**
  - For mid ∈ [0.1, 0.9] each maker's Q_min ≥ max(Q_one, Q_two)/3. So Σ Q_min ≥ (score of any single order)/3.
  - Take the largest price level of ≥ 10× `rewardsMinSize` shares within v (an order that big is very unlikely to be all
    sub-minimum orders).
  - `market_competitiveness` is **below that bound in 96 % of 239 markets**, with a median of **8 %** of the bound.
  - Therefore it cannot be the Σ Q_min the reward engine divides by. It is some normalised or rescaled score.
- **Consequence.** A 20-share quote 1¢ from mid in a $10–20/day pool gets a median share of **0.78** with `comp` as the
  denominator (reproducing the lead's 80–90 %). The same quote gets **0.14** with the book's aggregate Q_min and **0.10**
  with sim_lp's conservative max(q1, q2). The 80–90 % figure is an artefact of the scale mismatch.
- **Cross-check against reality.** Real small farmers earn **$1–3 per filled market-day** (section 2). An 80 % share of
  $10–20 pools would be $8–16 per market-day for every min-size quoter, which is inconsistent with observed payouts.

### 5.2 Monthly reward totals: confirmed, and they show strong growth

| Wallet | Metric | Jun | Jul | Aug | Sep (1–26) |
|---|---|---:|---:|---:|---:|
| tradetosurvive1 0x30fb41b5 | REWARD | $3.8k | $52.2k | $108.0k | $107.4k |
| | Trading ΔPnL (user-pnl-api) | — | −$29.0k | −$50.5k | −$53.6k |
| | Net | — | +$23.2k | +$57.6k | +$53.9k |
| | Loss/reward | — | 0.56 | 0.47 | 0.50 |
| PPMT 0x510f4963 | REWARD | $1.2k | $1.9k | $5.1k | $3.8k |
| | ΔPnL | +$4.1k | +$1.4k | +$3.0k | −$0.6k |
| | Net | +$5.3k | +$3.3k | +$8.1k | +$3.2k |

Capital now: tradetosurvive1 ≈ $118k (1.7 %/day net in Sep); PPMT ≈ **$30.4k** (Sep ≈ 0.4 %/day net, not a small
wallet). The growth (tradetosurvive1 ×28 from Jun to Aug) means weather pools expanded very recently. That is good for
current yields but also shows how discretionary and transient these pools are (section 3, failure mode 3).

The lead's small example, 0x04586f5d, is now at $529 of capital (vs $727 this morning). Its September figures are:
rewards $160, ΔPnL −$834, **net −$675**.

### 5.3 Local-time adverse-selection table (`src/live/hist_quote_local.py`): direction right, magnitude ~1.2–2× high

`hist_quote_local.py` calls `hist_quote_as2.run_one`, which still fills the full N = 20 shares on **every** crossing print
(even 1-share prints) and replenishes instantly. `src/audit/hist_as_local_windows.py` re-runs the same windows with the
audited simulator. Results in $ per market-day, d = 1¢, "through" fills; the full grid is in `src/audit/hist_as_local_windows.csv`.

| Window (local) | Lead | Audit, no print-size cap | Audit, print-size capped |
|---|---:|---:|---:|
| before D-1 00:00 | −2.71 | −2.28 | −1.25 |
| D-1 00–12 | −2.38 | −0.65 | −0.60 |
| D-1 12–18 | −1.69 | −0.70 | −0.86 |
| D-1 18–24 | −0.27 | −0.13 | +0.11 |
| D 00–06 | −4.27 | −1.67 | −2.01 |
| D 06–10 | −4.05 | −1.33 | −1.60 |
| **D 10–14** | **−30.7** | −17.2 | −17.0 |
| D 14–end | −14.6 | −7.8 | −7.6 |

Market-day-weighted over the whole pre-D window, the audited cost is **$0.5–1.1 per market-day** at d = 1–2¢
(lead: ≈ $2). Both tables replay only *historical* takers. Neither captures the informed flow a tight quote attracts in a
wide book (section 1b). The wallet test below shows that missing flow is what dominates.

### 5.4 Decisive test: do LPs that avoid the observation day keep more of their rewards?

`src/audit/closed_event_fills.py` pulled **906k maker fills** from all 608 daily-temperature events with endDate
09-20…09-25, where the observation day is complete. 71 % of all maker shares were filled on the local observation day.
`src/audit/discipline_split2.py` joins each LP-dominated wallet's observation-day share of fills with its 30-day
rewards, trading P&L and capital:

| Wallet fills on local obs day | n | Pooled loss/reward | Median loss/reward | Net/capital p25 / p50 / p75 | Share net > 0 |
|---|---:|---:|---:|---:|---:|
| < 20 % ("disciplined") | 38 | **0.90** | **0.91** | −0.02 / +0.35 / +1.87 %/day | 71 % |
| 20–40 % | 28 | 0.50 | 0.78 | −0.15 / +0.24 / +0.62 %/day | 68 % |
| 40–60 % | 14 | −1.14 | 0.82 | +0.03 / +0.19 / +0.62 %/day | 86 % |
| ≥ 60 % | 16 | 0.54 | 0.43 | −0.00 / +0.54 / +1.72 %/day | 75 % |
| **capital < $1.5k and < 30 % obs-day fills** | 19 | **0.89** | **0.94** | **−0.78 / +0.25 / +0.85 %/day** | 58 % |
| capital < $5k and < 30 % obs-day fills | 34 | 0.76 | 0.81 | −0.14 / +0.39 / +2.05 %/day | 68 % |

Avoiding the observation day does **not** improve the retained share of rewards in practice. Before D the fills are
fewer but just as toxic per reward dollar. Forecast-model traders reprice 1–2-day-ahead buckets on every NWP cycle, and a
resting min-size quote is exactly their counterparty.

Caveats:
- Rewards and trading P&L are wallet-wide (they include non-weather markets).
- The "< 20 %" group has the highest gross rewards/capital (4.6 %/day median), consistent with pre-D quoting in thin,
  fresh markets.
- Survivorship bias is upward.

### 5.5 Final calibrated estimate: disciplined small LP (daily temperature, quotes stop at local midnight before D)

| Component | Bottom-up (simulators, audited) | Ground truth (small disciplined wallets) |
|---|---|---|
| Reward per quoted market-day (min-size quote, `src/audit/reward_bounds.py`, 14–17 UTC books) | JOIN best levels: $2.4–5.5; LEAD ±1¢ with rival matching: $4.4–8.8 (lead's lp_report3: $4.6–5.6) | $1–3 per filled market-day |
| Capital per quoted market | $29 quote collateral + ~$15–25 inventory (locked ~1–1.5 days past quoting until resolution) → $45–55 | cash + positions snapshot |
| Gross rewards / capital | 5–15 %/day | **≈ 4.5–4.8 %/day median** |
| Adverse selection / capital | historical only: ~1–2.5 %/day (≈ 10–25 % of rewards) | **≈ 90 % of rewards** (pooled 0.89, median 0.94) |
| **Net / capital** | 3–12 %/day (**not credible**: 10–40× above every real wallet) | **+0.25 %/day median (IQR −0.8 to +0.9 %/day); +0.4 %/day median for < $5k** |

**Best estimate for a new, uninformed, disciplined small LP:**
- **+0.2 to +0.4 %/day of capital median**, i.e. ≈ +$2–4/day on $1,000 and +$0.2–0.4/day on $100.
- **IQR roughly −0.8 % to +1–2 %/day.**
- **~35–40 % probability of a losing month.**
- Survivorship and the absence of dead wallets bias this **upward**. The recent expansion of weather pools (×2–28 since
  July) biases it upward too if pools revert.
- It is far below the lead's implied (≈ $4.6–5.6 reward − $1–2.7 AS) / $19.5 ≈ 10–20 %/day, and ~300× below the
  original $1,000/day on $700.
- The lead's bottom-up number fails for three reasons: (i) share denominators on the wrong scale (5.1); (ii) capital
  that excludes inventory; (iii) AS measured only on historical flow (5.3–5.4).
- The only credible path to materially better numbers is a **forecast-centred** quote (a model edge), which would then
  be a forecasting strategy that happens to collect rewards. It is not LP farming.

## Files

- `src/audit/sim_lp_audit.py`: bias decomposition and corrected reward estimate on recorder data.
- `src/audit/reward_bounds.py`: reward per quoted market-day for the disciplined universe (LEAD / LEAD+R / JOIN, with competitor bounds).
- `src/audit/competitiveness_check.py`: scale test of `market_competitiveness` (`... lb` runs the lower-bound test).
- `src/audit/hist_as_local_windows.py`: audited AS on the lead's local-time windows (`hist_as_local_windows.csv`).
- `src/audit/closed_event_fills.py`, `src/audit/discipline_split2.py`: maker fills in closed temperature events and the observation-day discipline split (`data/audit/closed_event_maker_fills.json`, `data/audit/discipline_rows.json`).
- `src/audit/discipline_split.py`: an earlier version of the split on currently rewarded markets. It is confounded because observation-day fills are under-sampled there; superseded by `discipline_split2.py`.
- `src/audit/hist_as_audit.py`: corrected historical AS (size-capped fills, ask-side fix, local observation windows, spread/markout split). Results in `src/audit/hist_as_audit_results.csv`.
- `src/audit/maker_fill_pnl.py`: resolution P&L of all actual maker fills by window and price.
- `src/audit/wallet_ground_truth.py`: maker-wallet discovery, profiling, 30-day reward vs PnL, per-fill economics (cache in `data/audit/`).
