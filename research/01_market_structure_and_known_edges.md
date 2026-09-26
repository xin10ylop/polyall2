# 01 — Polymarket Market Structure (2026) and Publicly Documented Edges

*Research date: 2026-09-26. Venue scope: Polymarket only (external data OK for signals).*
*Method: official docs (docs.polymarket.com, fetched as raw `.md`), live API probes run from this sandbox on 2026-09-26 (~13:40–15:00 UTC), and external web research. Every claim carries a URL. Items I could not verify are flagged **[UNCERTAIN]**.*

> **Status:** complete (sections 1–6). Scratch analysis scripts were run in the session scratchpad; all API requests needed to reproduce the numbers are quoted inline.

---

## 0. Executive summary

1. **Fees (verified in docs + on 210,836 live market objects):** taker-only, `fee = C × rate × p × (1−p)`; rate 0.07 crypto, 0.05 sports/economics/culture/weather/other, 0.04 politics/finance/tech/mentions, 0 geopolitics (and currently 0 on ~24k NFL/CFB prop/spread markets, `feeType: zero_fees`, unexplained). Makers pay nothing and get 15–25% of taker fees back as daily rebates. No deposit/withdrawal/winnings fees. Read `feeSchedule` per market — old markets keep old rates (e.g. `sports_fees_v2` 0.03). Fee as % of stake = `rate×(1−p)` → 3.5% at 50¢ in crypto; as % of upside = `rate×p`.
2. **Liquidity rewards are large and under-competed in niches:** $134.8k/day across 16,400 markets (median pool $3/day). Snapshot competition model: joining the touch with ~$95 per market would earn a median ~$71/day per $1k deployed in weather markets 0.5–3 days from expiry, $28–45 in finance/culture, ~$5–7 in politics/tech/crypto, ~0 in sports — **before adverse-selection losses** (unmeasured). Holding rewards pay 3.25% APY on YES+NO value in 308 long-dated markets — apparently even for a hedged split position (verify small).
3. **Mechanics:** min order 5 shares; ticks 0.01/0.001 (0.0025 World Cup); GTC/GTD/FOK/FAK + post-only + heartbeat kill-switch; 150 ms taker delay on crypto up/down; 1 s+ delay on live sports; pUSD collateral since CLOB V2 (2026-04-28); gasless relayer for split/merge/redeem; neg-risk NO→YES conversion. UMA resolution with 2 h default liveness but 10–30 min custom liveness common; crypto up/down resolve natively ~1 min after close.
4. **Access:** this sandbox's IP geolocates to the US and `polymarket.com/api/geoblock` returns `blocked: true` — live orders must be placed from an eligible jurisdiction by an eligible person. International platform: no KYC; US persons: Polymarket US (KYC, separate book, own fees).
5. **Data:** legacy `clob.polymarket.com/prices-history` still returns **1-minute history for resolved markets up to ≥2 years old** (≤15-day windows, or `startTs` only); the new data-api v2 keeps only 3 h/12 h long-term. Goldsky public subgraphs are dead (deprecated after V2). Trades: data-api v2 keyset cursor (3-yr window); full V1 on-chain archive (1.2B trades, 2022-11 → 2026-04-28) on HuggingFace. Order-book history: none official; free hourly Parquet archive at archive.pendulumflow.com (Feb-2026 →, ~1.2 GB/hour).
6. **Edges:** taker arbitrage and 15-min crypto latency bots are fee-killed (I measured 1–3% neg-risk overrounds that are all negative after fees). Best-evidenced small-capital directions: (a) reward/rebate-aware passive market making in low-competition rewarded markets, (b) weather markets with external forecast/observation data (category top-50 made $586k in the last 30 days), (c) selective near-resolution favourites/"bonds" (≥90¢ buys earn +0.3–0.8% pre-fee on average; fees ≈ rate×p of upside). See §6.

## 1. Fee schedule (as of 2026-09-26)

### 1.1 Official formula and rates

Source: https://docs.polymarket.com/trading/fees (raw: https://docs.polymarket.com/trading/fees.md)

```
fee (pUSD) = C × feeRate × p × (1 − p)        C = shares, p = trade price
```

- **Takers only.** "Makers are never charged fees. Only takers pay fees." Fees are set by the protocol **at match time**; since CLOB V2 (2026-04-28) orders no longer carry `feeRateBps` (https://docs.polymarket.com/changelog/predictions.md, entry "Apr 17, 2026").
- Fees are rounded to 5 decimals; minimum charged fee 0.00001 → tiny trades near 0/1 can be fee-free.
- **No Polymarket fee on deposits/withdrawals** (intermediaries such as Coinbase/MoonPay/bridges may charge). **No fee on winnings / redemption** is documented anywhere in the docs (redeem = burn winning tokens for $1 pUSD each: https://docs.polymarket.com/concepts/resolution.md).

| Category (docs) | feeRate | Max fee per 100 sh (p=0.50) | Fee as % of notional = rate×(1−p) | Maker rebate share of taker fees |
|---|---|---|---|---|
| Crypto | 0.07 | $1.75 | 3.5% @50¢, 0.35% @95¢ | 20% |
| Sports | 0.05 (was 0.03 until 2026-07-10) | $1.25 | 2.5% @50¢, 0.25% @95¢ | 15% (was 25%) |
| Finance / Politics / Mentions / Tech | 0.04 | $1.00 | 2.0% @50¢, 0.2% @95¢ | 25% |
| Economics / Culture / Weather / Other | 0.05 | $1.25 | 2.5% @50¢, 0.25% @95¢ | 25% |
| **Geopolitics / world events** | **0** | $0 | 0 | — (fee-free) |

Key arithmetic for strategy design: **fee as a fraction of the cash you spend is `rate × (1 − p)`** — it falls to near zero for buys of heavy favourites (e.g. buying politics YES at 0.97 costs 0.04×0.03 = 0.12% of notional, i.e. 0.00116/share against a max 0.03/share payoff ≈ 3.9% of the gross edge), but it is brutal at mid prices (crypto at 50¢: 3.5% of notional per side). Round-tripping a 50¢ crypto contract as a taker costs ~7% of notional before spread.

### 1.2 How fees evolved (changelog)

All from https://docs.polymarket.com/changelog/predictions.md:

| Date | Change |
|---|---|
| 2026-01-05 | Taker fees first enabled on **15-min crypto** markets, "peak at 1.56% at 50%" (old curve: rate 0.25, exponent 2 → fee = C·0.25·(p(1−p))²; still visible on a stale market as `feeType: crypto_15_min`, `{"exponent":2,"rate":0.25}`). Maker rebates introduced. |
| 2026-02-12 | 5-min crypto markets launched with fees. |
| 2026-02-18 | Fees on NCAAB and Serie A; rebates now computed **per market**. |
| 2026-03-06 | Fees extended to all *new* crypto markets (1H, 4H, daily, weekly). |
| 2026-03-30 | **Fee Structure V2**: fees on Crypto, Sports, Finance, Politics, Economics, Culture, Weather, Tech, Mentions, Other. Geopolitics stays free. |
| 2026-03-31 | "Fees should now be calculated using the `feeSchedule` object within a market." |
| 2026-04-28 | **CLOB V2** live: new exchange contracts, **pUSD** collateral replaces USDC.e, `feeRateBps`/`nonce`/`taker` removed from orders, all resting orders wiped. |
| 2026-05-28 | **Taker Rebate Program** goes live (https://docs.polymarket.com/programs/taker-rebates.md). |
| 2026-07-10 | Sports feeRate 0.03 → **0.05**; sports maker rebate 25% → **15%**. |
| 2026-08-07/14 | Crypto up/down markets resolve on **Chainlink TWAP** (5-min: 60-s TWAP since 08-14; 15-min & 4-h: 60-s TWAP). |
| 2026-08-17 / 09-04 | Crypto **taker delay** 250 ms → 50 ms (08-17) → **150 ms** (09-04). |

Note: "Only markets deployed after fee activation are subject to charges" (Help Center, https://help.polymarket.com/en/articles/13364471-maker-rebates-program) — old markets keep their original fee config, so **always read the per-market `feeSchedule`** rather than assuming by category.

### 1.3 Verified via API — what the market objects actually say (probed 2026-09-26)

I paginated **all 210,836 markets** returned by `GET https://gamma-api.polymarket.com/markets/keyset?active=true&closed=false&limit=100&after_cursor=<next_cursor>` (note: the cursor param is `after_cursor`; `limit` is capped at 100 since 2026-05-14; offset pagination on `/markets` fails beyond offset ~2,000 with `"offset too large, use /markets/keyset"`). Many of these are stale/zombie markets (e.g. Dec-2025 5-min crypto markets still flagged active), so counts are of *listed* markets, not of liquid ones.

Distribution of `feeType` / `feeSchedule` / `feesEnabled`:

| count | `feeType` | `feeSchedule` | notes |
|---:|---|---|---|
| 151,784 | `sports_fees_v3` | `{rate:0.05, exponent:1, takerOnly:true, rebateRate:0.15}` | current sports |
| 24,300 | `zero_fees` | `{rate:0, rebateRate:0}` | **mostly NFL (8,886) and college football (15,410) props/spreads/totals/player props** — e.g. "Ravens vs. Cowboys" 2026-09-27. Why these are zero-fee is not documented **[UNCERTAIN — possibly a promo or a specific sports-data-provider product line]** |
| 12,175 | `politics_fees` | `{rate:0.04, rebateRate:0.25}` | |
| 5,909 | `crypto_fees_v2` | `{rate:0.07, rebateRate:0.2}` | incl. all live 5m/15m/4h up/down |
| 3,701 | `weather_fees` | `{rate:0.05, rebateRate:0.25}` | |
| 3,346 | `sports_fees_v2` | `{rate:0.03, rebateRate:0.25}` | pre-Jul-10 sports markets keep old rate |
| 2,741 | `finance_prices_fees` | `{rate:0.04, rebateRate:0.25}` | |
| 2,595 | `culture_fees` | `{rate:0.05, rebateRate:0.25}` | |
| 2,077 | `tech_fees` | `{rate:0.04, rebateRate:0.25}` | |
| 1,017 | `null` | `null`, `feesEnabled:false` | geopolitics & pre-fee legacy (e.g. "Putin out…2026?", "China invade Taiwan by end of 2026?") |
| 801 | `economics_fees` | `{rate:0.05, rebateRate:0.25}` | |
| 289 | `mentions_fees` | `{rate:0.04, rebateRate:0.25}` | |
| 100 | `general_fees` | `{rate:0.05, rebateRate:0.25}` | |
| 1 | `crypto_15_min` | `{rate:0.25, exponent:2, rebateRate:0.2}` | legacy Jan-2026 curve |

Other fields observed on every market:
- `makerBaseFee: 1000`, `takerBaseFee: 1000` (and CLOB `maker_base_fee`/`taker_base_fee`, `/fee-rate?token_id=…` → `{"base_fee":1000}`) — these are **legacy V1 fields and are NOT the fee actually charged**; the changelog says to use `feeSchedule` (2026-03-31 entry). Don't compute fees from them.
- CLOB compact endpoint `GET https://clob.polymarket.com/clob-markets/{condition_id}` returns `fd: {r, e, to}` (= rate, exponent, takerOnly), `mos` (min order size), `mts` (tick), `itode` (taker-delay enabled), `oas` (min order age), `r: {mi, ma, moas}` (rewards min size, max spread, and an undocumented `moas` = 30 — probably "min order age (s) for reward scoring" **[UNCERTAIN]**), `rfqe`, `ibce` (Blockaid check). Schema: https://docs.polymarket.com/api-spec/clob-openapi.yaml (`ClobMarketDetails`, `FeeDetails`).

Example live probes (2026-09-26):
```
# Sports (UEFA Nations League, England v Spain)
GET https://clob.polymarket.com/clob-markets/0xf006c03ebca5e5657b8f7df03c40681e3d88234cea587435fc2359e729dcf173
→ {"gst":"2026-09-26T18:45:00Z","r":{"mi":50,"ma":4.5,"moas":30},"sd":1,"mos":5,"mts":0.01,"mbf":1000,"tbf":1000,
   "nr":true,"fd":{"r":0.05,"e":1,"to":true}, ...}           # sd = seconds_delay 1s on in-play sports

# Live BTC 15-min up/down (btc-updown-15m-1790430300)
GET https://clob.polymarket.com/clob-markets/0xab2daa7edff794eb09995b90da19a61bc14979e1f2f82a95a4289a80bec2e103
→ {"r":{"mi":50,"ma":4.5,"moas":30},"mos":5,"mts":0.01,"itode":true,"fd":{"r":0.07,"e":1,"to":true}, ...}
```
So live crypto up/down (5m, 15m, 4h) = **rate 0.07, exponent 1, taker delay on**, resolution source **Chainlink BTC/USD TWAP 60-s stream** (market description; https://data.chain.link/streams/btc-usd-twap-60s-streams).

### 1.4 Taker Rebate Program (since 2026-05-28)

Source: https://docs.polymarket.com/programs/taker-rebates.md

- Weighted volume `wV = TradeSize($) × (1 − EntryPrice) × CategoryWeight × Bonuses`, trailing 30 days, taker trades only.
- Weights: Sports 1.0; Politics/Finance/Mentions/Tech 1.3; Economics/Culture/Weather/Other 1.7; Crypto 2.3; Geopolitics 0.
- Tiers (30-day wV → rebate of fees): <$2k 0%; $2k Bronze 3%; $20k Silver 8%; $200k Gold 18%; $1M Platinum 32%; $4M Diamond 44%; $10M+ Obsidian 50%. One-time level-up bonuses $10/$50/$250/$1.5k/$7.5k/$25k. Paid daily at 00:00 UTC in pUSD, $1 minimum. Omnibus-wallet integrations excluded.
- For small capital this is nearly irrelevant: reaching Gold ($200k wV) at ~50¢ prices needs ~$400k of 30-day taker notional in Sports.

### 1.5 Maker Rebates Program

Source: https://docs.polymarket.com/programs/maker-rebates.md

- Pool per market = category rebate % × taker fees collected in that market (Crypto 20%, Sports 15%, others 25%).
- Your share: `rebate = your_fee_equivalent / total_fee_equivalent × pool`, where `fee_equivalent = C × feeRate × p × (1−p)` summed over **your filled maker volume**. Computed **per market**, paid daily in pUSD, $1 minimum.
- Public lookup by maker address (no auth): `GET https://clob.polymarket.com/rebates/current?date=YYYY-MM-DD&maker_address=0x…` (clob-openapi.yaml `/rebates/current`).
- Discrepancy: the Help Center article still says "Crypto and Sports: 20%" (https://help.polymarket.com/en/articles/13364471-maker-rebates-program) while the dev docs and the live `feeSchedule.rebateRate` say Sports 0.15. The API value (0.15 on `sports_fees_v3`) is authoritative.
- Economic meaning: a maker filled at 50¢ in a crypto market earns back ≈ 0.20 × 0.0175 = $0.0035/share ≈ 0.7% of notional **if** its share of fee-equivalent equals its share of fills. It is a subsidy to adverse selection, not free money.

### 1.6 Polymarket US (separate CFTC-regulated DCM) — different fee schedule

Source: https://docs.polymarket.us/fees
- `Fee = Θ × C × p × (1−p)` with taker Θ = 0.0695 (max $1.74/100 contracts) and **maker rebate Θ = −0.0125 applied at the point of trade** (i.e. makers are *paid* per fill). Monthly taker volume rebates 10%/25%/50% at $250k/$1M/$10M. Combo taker fee `C·p·[0.0695(1−p)+0.04(1−p)^4]`. Fees rounded to nearest $0.01 (banker's rounding) — which makes very small orders relatively expensive or free depending on rounding.
- Polymarket US is a different venue/order book with KYC (see §3.5).

---
## 2. Incentive programs: liquidity rewards, maker rebates, holding rewards

### 2.1 Liquidity Rewards (the "LP rewards" program) — methodology

Source: https://docs.polymarket.com/programs/liquidity-rewards.md and https://docs.polymarket.com/market-data/market-details.md#liquidity-reward-settings

- Paid daily at 00:00 UTC to maker addresses; **$1 minimum payout**.
- Each rewarded market has `rewardsMinSize` (shares), `rewardsMaxSpread` (`v`, in **cents** from the *size-cutoff-adjusted midpoint*) and a daily pool (`rewardsDailyRate`).
- Order score: `S(v,s) = ((v − s)/v)² · b` (quadratic in distance `s` from adjusted mid; `b` = in-game multiplier for live sports).
- `Q_one` = Σ S·size over bids on YES + asks on NO; `Q_two` = Σ S·size over asks on YES + bids on NO.
- If mid ∈ [0.10, 0.90]: `Q_min = max(min(Q_one,Q_two), max(Q_one,Q_two)/c)` with **c = 3.0** → one-sided quotes still score at 1/3. If mid < 0.10 or > 0.90: `Q_min = min(Q_one,Q_two)` → **must be two-sided** to score at all.
- Book sampled **once per minute at a random offset** (≤1,440 samples/UTC day); your daily share = Σ_samples (your Q_min / Σ all Q_min), renormalized across makers; × the market's daily pool.
- The March-Madness changelog notes orders must rest **≥3.5 s** to be eligible (https://docs.polymarket.com/changelog/predictions.md, 2026-03-17). The CLOB market record also carries `r.moas: 30` on every market I probed — plausibly a 30-s minimum order age for reward scoring **[UNCERTAIN, undocumented]**. There is an authenticated endpoint to check whether a specific order is scoring: `GET /order-scoring?order_id=…` and `POST /orders-scoring` (clob-openapi.yaml).
- Past special pools: $1M "Crypto TWAP rewards" in Aug-2026 for 5m/15m/4h crypto (ended); $2M+ March-Madness pools (e.g. $60k/day on a live full-game moneyline). These show that **pools are episodic and large on marquee events** — where competition is also heaviest.

### 2.2 How to query rewards via API (all tested 2026-09-26, no auth)

```bash
# All markets with an active reward config (cursor-paginated, 500/page, last page cursor "LTE=")
curl "https://clob.polymarket.com/rewards/markets/current?next_cursor=<cursor>"
#  -> {"data":[{"condition_id":"0x…","rewards_config":[{"asset_address":"0xC011a7E1…(pUSD)","start_date":"2026-09-25",
#       "end_date":"2500-12-31","rate_per_day":1,"total_rewards":0,"id":0}],"rewards_max_spread":4.5,"rewards_min_size":20,
#       "native_daily_rate":1,"total_daily_rate":1}, …], "next_cursor": "…"}

# Per market (returns [] if none)
curl "https://clob.polymarket.com/rewards/markets/<condition_id>"

# Searchable/sortable list incl. market_competitiveness, spread, volume_24hr
curl "https://clob.polymarket.com/rewards/markets/multi?order_by=competitiveness&tag_slug=weather"

# Compact per-market CLOB params: r = {mi: min size, ma: max spread, moas: ?}
curl "https://clob.polymarket.com/clob-markets/<condition_id>"

# Gamma fields on each market: rewardsMinSize, rewardsMaxSpread, clobRewards[], holdingRewardsEnabled
curl "https://gamma-api.polymarket.com/markets/keyset?active=true&closed=false&limit=100"

# Authenticated (L2 API key): /rewards/user, /rewards/user/total, /rewards/user/percentages, /rewards/user/markets
```
(Endpoints listed in https://docs.polymarket.com/api-spec/clob-openapi.yaml.)

### 2.3 Size of the current reward pools (measured 2026-09-26)

Full pagination of `/rewards/markets/current` (33 pages):

- **16,400 markets** have an active reward config; **Σ total_daily_rate ≈ $134,830/day** (≈ $4.0M/month annualizing today's snapshot; consistent in magnitude with third-party claims of "$5M+ monthly", https://polymarkets.co.il/en/guide/liquidity-rewards/ — that source is a marketing site, treat as indicative only). All pools pay in pUSD (`asset_address 0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`).
- Very long tail: median pool **$3/day**; 5,917 markets ≤$1/day; 7,034 at $1–5; 2,013 at $5–20; 1,330 at $20–100; 102 at $100–500; 4 at $500–2,000 (max ≈ $1,003/day).
- Dollars by bucket: $20–100/day markets hold the largest share (~$55.8k/day), then $1–5 ($26.0k), $5–20 ($24.0k), $100–500 ($19.6k).
- By fee category (joined to gamma `feeType`): politics $30.0k/day (4,480 mkts), **weather $20.3k/day (814 mkts)**, sports v3 $18.4k (5,302), culture $14.2k (984), tech $11.2k (689), geopolitics/no-fee $10.1k (573), NFL/CFB zero-fee $7.3k, finance $6.2k, economics $5.7k, crypto $5.4k, mentions $3.1k.
- Parameters: `rewards_min_size` mostly 20 shares (12,417 mkts) or 50 (2,036); `rewards_max_spread` mostly 4.5¢ (12,380), 6.5¢, 5.5¢.

### 2.4 Can small capital earn meaningful rewards? — snapshot competition estimate

I sampled 2,430 rewarded markets (all 1,436 with ≥$20/day plus 400 random from $5–20 and 400 from ≤$5), pulled their order books (`POST https://clob.polymarket.com/books`, YES token only — **YES and NO books are exact mirrors**, verified), and computed the aggregate reward score `Q` of resting liquidity within `v` of the size-cutoff-adjusted mid (levels ≥ min size), then the share a new maker would get by **joining the best bid and best ask with max(min_size,100) shares each side** (capital ≈ $90–100). Script: scratchpad `rew_est.py`. Results (snapshot, *upper-bound-ish*):

| Pool tier ($/day) | n | median share of pool | median $/day | median $/day per $1k deployed | p90 per $1k |
|---|---:|---:|---:|---:|---:|
| ≥ 100 | 154 | 2.0% | $3.69 | $22 | $463 |
| 20–100 | 1,515 | 3.1% | $1.05 | $7 | $137 |
| 5–20 | 382 | 11.4% | $1.00 | $10 | $45 |
| ≤ 5 | 379 | 15.1% | $0.27 | $2.8 | $12 |

- By category, median $/day per $1k: **weather ≈ $71**, economics ≈ $16, finance ≈ $12, culture ≈ $10, politics ≈ $6.6, crypto ≈ $5.7, tech ≈ $5.1, **sports ≈ $0** (sports pools are crowded by pro MMs with huge size near mid).
- Split by time-to-`endDate` (same sample): **weather markets ending in 0.5–3 days: median $71/day per $1k (n=288, p75 $128)**; same-day/ended weather median $198 (n=63); culture 3–30 d median $45 (n=106); finance 3–30 d $28 (n=71); mentions 0.5–3 d $38 (n=16); politics >30 d $6.6 (n=454); tech >30 d $4.8; crypto >30 d $4.8; sports ≈ $0. Per market the dollars are small (a ~$95 two-sided quote earning a few $/day), so scaling means quoting many markets simultaneously.
- The highest estimated yields (hundreds of $/day per $1k) are almost all **same-day weather buckets** (NYC/Atlanta/London/Madrid/Denver highs & lows), MrBeast-views, VMA award, Netflix-ranking and tweet-count markets. These are exactly the markets where **informed flow arrives intraday** (live station observations, view counters), i.e. passive quotes get picked off. The reward is compensation for adverse selection; the net is unknown without a live test.

**Caveats (important):** (1) snapshot, not the 1,440-sample daily average — competitors often quote only during calm periods; (2) aggregated price levels hide individual order sizes (min-size filter approximate); (3) the "size-cutoff-adjusted midpoint" is approximated; (4) ignores fills/inventory P&L — in a market that moves, a two-sided quote at the touch will be filled on the wrong side; (5) many rewarded markets have `endDate` already passed but still quote (same-day weather) — the reward window closes at resolution.

**Bottom line:** the arithmetic says a $1–5k maker *can* capture double-digit dollars/day of rewards in niche categories (weather, culture, economics, finance, mentions/tweet counts) where pools are $20–200/day and few makers compete — **this is the single most "structural" small-capital income source on Polymarket in 2026**, but it is not riskless: you must manage adverse selection (pull quotes around information events) and it requires an always-on bot with fast cancels. Sports and top politics pools are dominated by professional MMs.

Independent evidence on LP-reward profitability is thin and mostly anecdotal:
- Polymarket's own blog on automated market making: https://news.polymarket.com/p/automated-market-making-on-polymarket
- Open-source bot `warproxxx/poly-maker` (the author's README warns it is a reference implementation and "can lose money"): https://github.com/warproxxx/poly-maker ; a user's write-up of running it: https://tezlee.substack.com/p/i-cloned-a-polymarket-market-making
- Claims like "$50k capital → $200–800/day" (https://polymarkets.co.il/en/guide/liquidity-rewards/) are from affiliate/marketing sites and **unverified**.
- An academic paper documents **"ghost fills"** (off-chain matches reverted on-chain by attackers via nonce bumps/balance drains) used partly for **liquidity-reward manipulation**; ≥$1.49M attacker profit, up to 24.3% of fills reverted at peak hours (Shen et al., 2026, https://arxiv.org/abs/2606.16852). It analysed the V1 exchange; whether CLOB V2 (2026-04-28) closes the hole is **[UNCERTAIN]**. For a maker this means "fills" can be un-done — reconcile against on-chain settlement.

### 2.5 Maker rebates (fee-funded, separate from LP rewards)

See §1.5. Paid only on **filled** maker volume, per market, pro-rata to fee-equivalent. Public per-address lookup: `GET https://clob.polymarket.com/rebates/current?date=2026-09-25&maker_address=0x…`. For a small maker this is a modest add-on (≈0.2–0.9% of filled notional near 50¢, less near extremes), not a strategy by itself.

### 2.6 Holding Rewards (APY on positions in selected long-dated markets)

Source: Help Center, https://help.polymarket.com/en/articles/13364459-holding-rewards ; launch coverage (4% at launch): https://www.cryptopolitan.com/polymarket-starts-paying-out-4-rewards/ , https://www.blocmates.com/news-posts/polymarket-introduces-4-annualized-yield-for-long-term-market-positions

- Current rate stated as **3.25% annualized** (was 4.00% at launch), variable, funded by Polymarket treasury, can be capped/changed at will.
- Position value sampled **randomly once per hour** using mid prices; paid daily. **Both YES and NO holdings count** (help-center example: `(30000 × 0.53) + (10000 × 0.45)`).
- API: `holdingRewardsEnabled: true` on **308 markets / 33 events** (2026-09-26): 2028 presidential/nominee markets (148), "What price will BTC/ETH/SOL/XRP/HYPE hit before 2027" (108), 2026 midterm balance-of-power/Senate/House/state-senate, Putin/Xi/Netanyahu/Zelenskyy/Erdoğan out, China-invades-Taiwan, Trump impeachment, "X announces bankruptcy by…" (OpenAI, Anthropic, CoreWeave, NuScale, Payward).
- **Implication:** because YES and NO both count at mid, a **fully hedged split position (1 pUSD → 1 YES + 1 NO, value ≈ $1) appears to earn ~3.25% APY with no directional risk**, and can be merged back to pUSD at any time. That makes it a candidate "cash sweep" for idle strategy capital. I found no explicit anti-hedging clause, but Polymarket reserves the right to limit payouts — **[UNCERTAIN: verify with a small position before relying on it]**. Third-party tracker claims $2.03M paid to 314k holders: https://polyscalping.org/leaderboard/yield (unofficial).

---
## 3. Order mechanics, settlement, resolution, access

### 3.1 Orders

Sources: https://docs.polymarket.com/concepts/order-lifecycle.md , https://docs.polymarket.com/trading/place-orders.md , https://docs.polymarket.com/v2-migration.md

- **Everything is a limit order**; "market orders" are limit orders priced to cross. Orders are EIP-712 signed messages; matching is off-chain by the operator, settlement on-chain (Polygon) and atomic.
- **Order types:** `GTC`, `GTD` (expires 1 min before the stated expiration; expiration must be ≥ 3 min in the future → minimum effective life ≈ 2 min; use `now + 60 + N`), `FOK` (all-or-nothing), `FAK` (fill what's available, cancel rest; since 2025-05-28). **Post-only** flag for GTC/GTD (since 2026-01-06) — rejected instead of crossing. Market orders must use `expiration = "0"`.
- **Batch:** `POST /orders` 1–15 orders per call; `DELETE /orders` up to 1,000 IDs (since 2026-06-15).
- **Heartbeats:** `POST /heartbeats` — if heartbeats stop, **all open orders are auto-cancelled** (dead-man switch for bots; since 2026-01-06).
- **Minimum size:** `orderMinSize` = **5 shares** on essentially all markets (210,807/210,836 active markets); error text `Size (x) lower than the minimum: 5` (https://docs.polymarket.com/resources/error-codes.md). So the minimum order is $0.05–$4.95 depending on price. (Reward-eligible size is separate: `rewardsMinSize` usually 20–50 shares.)
- **Tick sizes** (`orderPriceMinTickSize`): 0.01 on 181,739 markets, 0.001 on 29,096 (typically when price is near 0/1 — tick changes dynamically, `tick_size_change` WS event), 0.0025 for World Cup markets (since 2026-07-02). Supported ticks per docs: 0.1, 0.01, 0.005, 0.0025, 0.001, 0.0001.
- **Taker delays / speed bumps:**
  - Crypto (and some finance) up/down markets: `itode: true` → marketable orders held **150 ms** since 2026-09-04 per the changelog (was 250 → 50 → 150 ms; note the Order-Lifecycle page and the OpenAPI `itode` description still say 250 ms — docs lag), then re-validated; cannot be cancelled during the hold. This explicitly blunts latency arbitrage against resting makers.
  - Live sports: `seconds_delay` (e.g. `sd: 1` = 1 s on the England–Spain match probed) — marketable orders return status `delayed`, then match or rest.
- **Matching-engine restarts:** announced ~2 days ahead; after a restart the engine is **post-only for 2 minutes** (https://docs.polymarket.com/trading/matching-engine.md).
- **Rate limits:** Cloudflare IP limits (e.g. `POST /order` 5,000/10 s burst, 120,000/10 min sustained; `/book` 1,500/10 s; `/prices-history` 1,000/10 s; gamma `/markets` 300/10 s; data-api v2 800/10 s, `/v2/trades` 300/10 s) — https://docs.polymarket.com/api-reference/rate-limits.md. Plus **per-signer token buckets** (warning mode from 2026-07-24): Standard tier 40 orders/s (burst 60), 80 cancels/s (burst 120); higher tiers by 30-day volume ($30k Copper … $10M Elite 600/s) — https://docs.polymarket.com/api-reference/trading-rate-limits.md. More than enough for a small bot.
- **Trade statuses:** `MATCHED → MINED → CONFIRMED` (or `RETRYING`/`FAILED`). Since 2026-07-24 FAK/FOK responses return `tradeIDs`, not tx hashes. A matched trade **can still fail on-chain** (see "ghost fills", §2.4).
- **Co-location:** primary servers AWS **eu-west-2 (London)**; closest non-geo-restricted region eu-west-1 (Ireland); direct eu-west-2 co-location available after a KYC/KYB form (https://docs.polymarket.com/api-reference/geoblock.md).

### 3.2 Collateral, wallets, gasless relayer

- **pUSD** (ERC-20 on Polygon, 6 decimals, 1:1 USDC-backed, enforced on-chain via `CollateralOnramp`/`CollateralOfframp`) replaced USDC.e as collateral on 2026-04-28 (https://docs.polymarket.com/concepts/pusd.md).
- Wallet types: **Deposit Wallet** (default for accounts created ≥ 2026-05-04), legacy Proxy (Magic/Google) and Safe (MetaMask etc.), or plain EOA; session keys allow a scoped, time-limited separate signer (https://docs.polymarket.com/trading/wallets-auth.md, https://docs.polymarket.com/trading/session-keys.md).
- **Gasless:** split/merge/redeem/approvals go through the Polymarket **Relayer** with a Relayer API key (polymarket.com → Settings → API Keys) — no POL needed. Relayer `/submit` limit 25 req/min.
- New unified SDKs: `@polymarket/client` / `polymarket` Python (`AsyncSecureClient`), and V2 CLOB clients `py-clob-client-v2`, `@polymarket/clob-client-v2`; legacy V1 SDKs no longer work (https://docs.polymarket.com/changelog/predictions.md, 2026-04-17/28).

### 3.3 Split / merge / convert / redeem

Source: https://docs.polymarket.com/trading/positions/manage.md , https://docs.polymarket.com/concepts/negative-risk.md

- **Split:** 1 pUSD → 1 YES + 1 NO (complete set). **Merge:** 1 YES + 1 NO → 1 pUSD, any time before resolution. These make "YES ask + NO ask < 1" (buy both, merge) and "YES bid + NO bid > 1" (split, sell both) arbitrage mechanically executable. Because the CLOB mirrors YES/NO books (a NO bid at q *is* a YES ask at 1−q, verified via `/book`), such single-market violations are almost never visible in the book.
- **Neg-risk (multi-outcome) events** (58,345 active markets have `negRisk: true`): 1 NO on outcome *i* can be **converted** into 1 YES on every other outcome via the Neg Risk Adapter (current V2 adapter `0xadA2005600Dec949baf300f4C6120000bDB6eAab`; old V1 adapter retired for relayer calls 2026-07-17). Consequence: a basket of NOs on k outcomes of an n-outcome event = (k−1) pUSD + YES on the rest. Gebele, Mutzel & Matthes (2026) find converter-enabled arbitrage realized ~$1.09M vs only $32k from settlement-based basket formation, and that violations concentrate on the *YES* side (buying all YES < $1 is not directly executable by conversion, so must wait for settlement) — https://arxiv.org/abs/2608.00666.
- "Augmented" neg-risk events have placeholder outcomes + "Other"; docs warn to trade only named outcomes.
- **Redeem:** after resolution, winning tokens → $1 pUSD each through the CTF collateral adapter; losing → 0. Since 2026-08-10 `/activity` shows one REDEEM row per outcome. Several third-party guides say payouts are automatic; the docs describe redeem as an action you (or the UI/relayer) perform — **for a bot, call redeem explicitly** (https://docs.polymarket.com/concepts/resolution.md).

### 3.4 Resolution: UMA Optimistic Oracle + native/automated paths

Sources: https://docs.polymarket.com/concepts/resolution.md ; UMA managed proposers: https://blog.uma.xyz/articles/managed-proposers

- **UMA flow:** proposer posts bond (docs: "typically $750"; gamma `umaBond` on recent markets is **250** for sports/crypto/weather and **500** for politics/mentions/culture) → **challenge (liveness) window**, default **2 h** → if undisputed, resolves. First dispute → re-proposal; second dispute → UMA DVM vote (24–48 h debate + ~48 h vote); disputed resolutions take **~4–6 days**. "Too early" and 50-50 outcomes exist.
- **Shorter custom liveness is common now.** Among the 3,000 most recently closed markets (gamma `closed=true`, probed 2026-09-26): `customLiveness` = 1,800 s (483 sports), 900 s (79 sports, 27 NFL/CFB, weather), 600 s (129 crypto "above X on date" markets), 3,600 s, 7,200 s, or null (default).
- **Proposers are whitelisted** ("Managed Optimistic Oracle V2", since 2025-08-12): 37 addresses with >95% accuracy make ~96% of proposals; disputes remain permissionless. UMA reports ~1.3% dispute rate overall.
- **Crypto up/down (5m/15m/4h) resolve natively from Chainlink TWAP data**, not via UMA: `resolvedBy: null`, closed ~**0.9 min** after `endDate` (median over 384 recent BTC/ETH/SOL/XRP/DOGE/BNB/HYPE/ZEC markets). Crypto "above X on date" daily markets closed ~12 min after end (600-s liveness). `/v2/resolutions` distinguishes `resolution_source: "reported"` (native) from UMA lifecycle rows.
- **Empirical timing (third party, unverified):** Poly Syncer indexed 18,427 settlements May-2025→May-2026: median 41 min after event end; NBA 22 min, soccer 28 min, crypto 38 min, politics 2 h 48 m, geopolitics 5 h 16 m; p99 4 d 5 h; 1.0% disputed (median +49 h) — https://www.polysyncer.com/blog/polymarket-resolution-time-2026 . The sub-2-hour medians are consistent with the shorter custom liveness windows I observed. Another report says disputes in Jan–May 2026 (>1,150) already exceeded all of 2025 (search result citing https://crypto.news/how-prediction-markets-resolve-uma-optimistic-oracle/) **[UNCERTAIN]**.
- Data endpoint: `GET https://data-api.polymarket.com/v2/resolutions?condition=<cid1>,<cid2>` → status, was_disputed, proposed_price, payouts, resolved_at.
- **Resolution risk is a real P&L factor** for "bond"/NO-harvesting strategies: wording ambiguities cause ~43% of disputes (Poly Syncer), and UMA votes have been publicly controversial (e.g. whale-vote flip, https://www.oddsshopper.com/articles/prediction-markets/uma-oracle-polymarket-disputes).

### 3.5 Geography, KYC, and a practical blocker for this project

- **Geoblock endpoint:** `GET https://polymarket.com/api/geoblock`. **From this sandbox it returns `{"blocked":true,"country":"US","region":"IL"}`** — i.e. orders placed from this machine's IP would be rejected. Any live trading must run from a permitted jurisdiction/host (and the account holder must be eligible — using a VPN to evade restrictions violates the ToS).
- Restricted list (https://docs.polymarket.com/api-reference/geoblock.md): **blocked completely** (OFAC): IR, SY, CU, KP, Crimea/Donetsk/Luhansk. **Close-only (frontend + API):** AU, BY, BE, BI, BR, CA-BC/ON/AB/QC, CF, CD, ET, **FR, DE, IT, PL, GB, US**, UM, IQ, LB, LY, MM, NZ, NI, RU, SG, SO, SK, SS, SD, TW, TH, VE, YE, ZW. **Close-only on frontend only (API not restricted):** IE, JP, MT (sports only), NL, KR.
- **KYC:** the international platform (polymarket.com) remains non-custodial with **no KYC** for normal use; Polymarket's VP Eng stated on 2026-05-28 "No KYC is being added to any part of existing polymarket.com" (KYC only for the Perps beta) — https://cryptobriefing.com/polymarket-kyc-beta-product-clarification/ . Co-location requires a KYC/KYB form. Fiat on-ramps (MoonPay etc.) do their own KYC.
- **US persons:** use **Polymarket US** (CFTC-regulated DCM, formerly QCEX; waitlist removed May 2026) — full KYC through the iOS app, API keys only for verified US users, different fee schedule (§1.6), separate liquidity (https://docs.polymarket.us/fees ; https://www.quantvps.com/blog/polymarket-us-api-available ; https://docs.polymarket.us/institutional/kyc/overview). Market coverage/liquidity there differs from polymarket.com **[not researched in depth]**.

---
## 4. Publicly documented strategies — evidence, capital, decay, execution risk

Evidence grading used below: **A** = peer-reviewed/arXiv with on-chain data or my own API measurement; **B** = verifiable on-chain/leaderboard data or official Polymarket statement; **C** = self-reported blog/X/GitHub claims, unverifiable; **D** = marketing/SEO content. Most "strategy" content on the web in 2026 is C/D-grade affiliate material — treat it as hypothesis generation only.

### 4.0 Cross-cutting facts that decide viability
- **Fees scale as `rate × p × (1−p)` per share** (§1). As a fraction of *stake* it is `rate × (1−p)` (punishing for cheap contracts: buying a 10¢ weather bucket as taker costs 4.5% of stake); as a fraction of *max gain* it is `rate × p` (≈4–7% of the upside for favourites). Makers pay 0 and receive rebates + LP rewards → **in 2026 almost every documented small-capital edge should be executed maker-side (post-only) where possible.**
- **Who wins:** Becker (Kalshi, 72.1M trades, 2021-11/2025) finds makers +1.12% vs takers −1.12% average excess return, and the gap flipped in makers' favour after Oct-2024 volume growth (https://www.jbecker.dev/research/prediction-market-microstructure; dataset incl. 400M+ Polymarket trades: https://github.com/jon-becker/prediction-market-analysis). This is Kalshi, not Polymarket — **by analogy only**.
- **Concentration:** marketing sites repeatedly claim "84% of Polymarket wallets lose money" / "3% consistently profitable" (e.g. https://polymarkets.co.il/en/guide/liquidity-rewards/) — **[unverified, grade D]**.

### 4.1 Pure arbitrage (single-market rebalancing, neg-risk baskets, combinatorial)
- **Evidence (A):** Saguillo, Ghafouri, Kiffer, Suarez-Tangil, "Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets" (AFT 2025; data 2024-04-01 → 2025-04-01): ~**$40M realized** arbitrage profit, overwhelmingly *market rebalancing* (YES+NO≠1 within a market, or multi-outcome sums ≠1); *combinatorial* (cross-market) arbitrage was tiny (~$95k across 5 election pairs). Top single address ≈ **$2.01M**, 4,049 txs → bot-dominated. https://arxiv.org/abs/2508.03474 (html: https://arxiv.org/html/2508.03474)
- **Evidence (A):** Cheng, Yang, Zou, "Arbitrage Analysis in Polymarket NBA Markets" (2026-04): 75M book snapshots, 173 games — only **7 executable single-market episodes** (median life **3.6 s**); 290 combinatorial episodes (mostly final minutes), median return 101 bp, but 76.9% capped at ~**14.8 shares** → "risk-free extraction confined to retail scale". https://arxiv.org/abs/2605.00864
- **Evidence (A):** Gebele, Mutzel, Matthes, "Executable Arbitrage and Market Efficiency in Prediction Markets" (2026-08): ~$1.12M neg-risk arbitrage, $1.086M via the NegRisk converter; violations persist mainly on the YES side where no conversion primitive exists. https://arxiv.org/abs/2608.00666
- **My live check (A, 2026-09-26):** of 7,384 neg-risk events, gamma snapshot flagged 12 with Σ(best YES bids) > 1.01. Re-checking live books: overrounds of **+1.1% to +3.0%** existed (e.g. Euro-2028 winner 1.029, Worlds-2026 1.019, Fed-rate-end-2027 1.016, Oura IPO mcap 1.020), but **taker fees across all legs (0.030–0.045 per set) made every one net negative (−0.15¢ to −8¢ per set)**, and depth at the best bid was often 0–5 shares. Σ(best asks) < 1 flags were artefacts of incomplete outcome lists.
- **Decay:** strong. 2026 taker fees on 10 of 11 categories convert most visible overrounds into losses; the remaining arbs are sub-second (bot races, co-located in eu-west-2). Geopolitics (fee-free) neg-risk events remain the only place where taker-side rebalancing arb is not fee-taxed.
- **Small-capital verdict:** ✗ as a taker strategy. Possible **maker variant**: rest post-only quotes that would complete an under-/over-round basket (earning rebates + rewards), accepting leg risk. Unproven.

### 4.2 Favourite–longshot bias / calibration trades
- **Evidence (A):** Cardozo & Rivero-Wildemauwe, "The Favorite–Longshot Bias in Prediction Markets: Evidence from Polymarket" (arXiv 2609.12878, Sep-2026; 588M trades, 2.48M wallets, 2022-11 → 2026-03-29). Buys **<10¢ lose −6.3%** per $ (equal-weight by market; −19.3% dollar-weighted, wide CI); buys **≥90¢ earn +0.28%** (equal-weight) to **+0.83%** (dollar-weighted). Pattern robust in **Crypto and Politics**, **reversed in Sports** (sports longshots earn positive returns), mixed in Finance/Weather/Culture/Tech. **Pre-fees and pre-rewards**; mixes makers and takers. Grouping by parent event flips longshots to +4.1% → results fragile to weighting. https://arxiv.org/abs/2609.12878
- **Evidence (A):** Reichenbach & Walther, "Exploring Decentralized Prediction Markets: Accuracy, Skill, and Bias on Polymarket" (SSRN Dec-2025, 124M trades): prices track realized probabilities closely; **no general longshot bias**, but a tendency to over-trade the default/"Yes" option. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5910522
- **Evidence (B/C):** calibration study of 16,759 markets resolving 6–20 Sep 2026 (mid-quotes 1 day before): 5–35% quotes **under**-priced (resolved YES 17–33% vs 10–26% quoted), 65–95% **over**-priced — the author explicitly says "spread and fees not modelled; nothing here is a tradable edge"; sample dominated by short-dated (sports/crypto) markets and it has two published corrections for harvesting bugs. https://github.com/shirleyshen0106/polymarket-calibration
- **Interpretation:** the sign of the bias depends on category (sports vs crypto/politics) and on horizon; the magnitude at the favourite end (+0.3–0.8%/trade) is of the same order as the taker fee there (rate×(1−p) ≈ 0.2–0.35% of stake at 95¢), so **a naive taker implementation is ~break-even**. Needs category-specific modelling and maker execution.

### 4.3 "Nothing Ever Happens" (always buy NO on non-sports markets)
- **Evidence (C/D):** bot by Sterling Crispin (Apr-2026): buys NO on every non-sports market when NO ask < $0.65, 2% sizing, hold to resolution; open-source; **no wallet or live P&L disclosed**. The "73.3% of markets resolve NO" figure is Polymarket's accuracy-page base rate, i.e. already reflected in prices. https://decrypt.co/364381/polymarket-bot-bets-no-has-a-point ; HN discussion https://news.ycombinator.com/item?id=47753472 ; critique https://thepixelspulse.com/posts/nothing-ever-happens-bot-polymarket-fails/
- The only rigorous related evidence is §4.2: in Crypto/Politics, NO-favourites (i.e. YES longshots overpriced) earn a small positive pre-fee return; in Sports the opposite. A base-rate win percentage is not an edge.
- **Verdict:** hype > evidence. Worth a backtest restricted to Politics/Crypto "will X happen by date" markets with the CLOB 1-min history (§5.1), fee-adjusted, and with dispute/"too early" resolution risk.

### 4.4 High-probability "bonds" / near-certain sweeping / resolution-lag harvesting
- **Mechanics:** buy 95–99.9¢ outcomes that are practically decided (post-game, post-announcement, crypto "above X" after the print) and hold to resolution. Fee ≈ rate×p of the upside (4–7%), small in $.
- **Evidence (A):** the ≥90¢ bucket earns +0.28–0.83% per $ pre-fee (§4.2). Resolution timing makes the annualised yield: crypto up/down resolve ~1 min after end (no lag to harvest); crypto "above X" daily ~12 min (600-s liveness); sports custom liveness 15–30 min common; politics/geopolitics hours to days (§3.4).
- **Evidence (C):** practitioner thread "bonding 101" (@probabilitygod, https://x.com/probabilitygod/status/1996498793026429058 — not fetchable, paywalled) and many guides (e.g. https://startpolymarket.com/strategies/bonding/, grade D) all stress the same **tail risk**: one wrong or disputed resolution erases dozens of wins (risk 95¢ to make 5¢; a 50-50 or "too early" UMA outcome also hurts).
- **Execution risk:** resolution/dispute risk (~1% of markets disputed; wording ambiguity is the #1 cause), capital lock-up, competition from bots sweeping the book seconds after events. Positive: works with small size, fees are low near 1, no speed needed if the edge is *information about resolution*, not speed.
- **Verdict:** plausible, low-return, needs careful rule reading + a data feed that tells you the event is decided before the book fully reprices. Backtestable with 1-min history.

### 4.5 Market making & liquidity-reward farming
- **Evidence (B):** Polymarket's own newsletter interview (2025-05-28): @defiance_cr started with **$10k**, earned ~$200/day, peaking at **$700–800/day** mostly from **liquidity rewards** during the 2024 election (> $25k/day of LP rewards then); stopped after rewards were cut post-election and open-sourced the bot. https://news.polymarket.com/p/automated-market-making-on-polymarket ; code https://github.com/warproxxx/poly-maker (README: "competitive and can lose money").
- **Evidence (A, own measurement §2.3–2.4):** today's pools total ≈ **$134.8k/day across 16,400 markets**; snapshot estimate of a new small maker's share: median $7–22/day per $1k in $20+/day pools, **weather median ≈ $71/day per $1k**, sports ≈ 0. Maker rebates add 15–25% of taker fees on filled volume (§1.5).
- **Evidence (B, leaderboard):** in crypto, the monthly PnL board shows MM-like profiles (e.g. $256k PnL on $27.6M volume ≈ 0.9% margin; $114k on $25.8M) — `GET https://data-api.polymarket.com/v2/leaderboard?category=crypto&time_period=month`.
- **Risks:** adverse selection around information events (weather obs, game events, crypto moves), inventory, ghost-fill reversals (§2.4), taker delays that protect makers in crypto (good for makers), matching-engine restarts, rule changes to reward pools (pools are discretionary).
- **Verdict:** **the most "structural" edge for small capital** in 2026, provided you pick low-competition rewarded markets and pull quotes around information arrival. Capital: $1–5k is enough given 20–50-share min sizes.

### 4.6 Weather (temperature/precipitation) markets with external forecasts
- **Market structure:** ~100 cities × daily high/low buckets (+ rain, drought), resolved from NOAA/Weather Underground station data (e.g. NYC = LaGuardia KLGA hourly "Temp", whole °F; description on event `highest-temperature-in-nyc-on-september-27-2026`). `weather_fees` rate 0.05, rebate 25%; 814 rewarded weather markets carry ~$20.3k/day of LP rewards (§2.3).
- **Evidence (B):** category PnL leaderboard (`/v2/leaderboard?category=weather`), 2026-09-26: last 30 days top-1 **$68.4k** (on $194k volume), top-10 sum **$292k**, top-50 sum **$586k**, #50 still **$4.1k**; all-time top-50 sum **$3.23M**. Weekly top-10 $119k. That is a real, broad profit pool (winners only — losers not shown; PnL definition incl./excl. rewards **[UNCERTAIN]**).
- **Evidence (C):** open-source bots using NOAA/Open-Meteo/GFS-ensemble vs market price (https://github.com/tobiasbischoff/polymarket-weather-bot ; https://github.com/suislanchez/polymarket-kalshi-weather-bot — README self-reports "highest profits $1.8k"); Medium write-ups about $24k–$88k weather wallets (https://medium.com/mountain-movers/inside-the-data-behind-polymarkets-viral-88k-weather-prediction-trading-strategy-and-results-2e65a8389f37 — grade C/D). Several sources say edges have compressed as bots entered (e.g. https://www.tradetheoutcome.com/polymarket-weather-strategy/, grade D).
- **Edges to test:** (i) ensemble forecast (ECMWF/GFS/HRRR, MOS) probability per bucket vs market, 1–3 days ahead; (ii) same-day **observation edge** — ASOS 1-/5-min obs and METAR/SPECI can show the day's max has been reached before the market fully reprices; (iii) quoting as maker to collect the unusually high weather LP rewards while forecast-informed.
- **Risks:** station-specific quirks (rounding, °F/°C conversion, data outages → "lowest bracket" fallback rule), low depth, fee drag on cheap buckets if taking.
- **Verdict:** **one of the best-evidenced niches for small capital** (broad leaderboard profits, cheap public data, modest competition vs sports/crypto).

### 4.7 15-min / 5-min crypto up/down bots
- **History (B):** late-2025 latency bots bought the "obvious" side after Binance/Coinbase moved; wallet "0x8dxd" reportedly turned ~$313 into ~$414k in a month (Finance Magnates, 2026-01-07: https://www.financemagnates.com/cryptocurrency/polymarket-introduces-dynamic-fees-to-curb-latency-arbitrage-in-short-term-crypto-markets/). Polymarket responded with taker fees (Jan-2026; ~3.15% of notional at 50¢ under the old curve), maker rebates, and later a **150 ms taker delay** (`itode`), **Chainlink TWAP settlement** (Aug-2026) and the current 0.07 rate (3.5% of notional at 50¢). (§1.2, §3.1)
- **Evidence (C):** self-reports that "pure latency arbitrage stopped working the same day" and that maker-side/momentum variants survived (https://dev.to/lkto1m/february-2026-changed-polymarket-forever-heres-what-happened-to-my-bots-numbers-2fi5 — no wallet). Many GitHub latency bots (e.g. https://github.com/learningworship/polymarket-latency-bot) are pre-fee designs.
- **Evidence (B):** crypto category monthly leaderboard still shows large winners, but profiles look like high-volume makers (≈0.5–1% margin on $4–28M volume).
- **Verdict:** ✗ for small-capital takers (3.5% fee at 50¢ + 150 ms delay + TWAP). Maker quoting in 5m/15m markets (rewards $50 min size, 4.5¢ spread; rebate 20%) competes with pro MMs holding Chainlink stream access. A remaining research idea: **late-window TWAP math** — with a 60-s TWAP settlement, the last minute's outcome is partly "locked in"; compute P(Up) from the live Chainlink TWAP stream (PolyBolt WS) vs market quotes. **[Hypothesis, no public evidence found.]**

### 4.8 Sports latency / in-play
- **Evidence (C):** X posts claim bots profit from the ~3 s data-feed vs ~45 s stream lag (https://x.com/0xMovez/status/2008298059059343819 , https://x.com/0xRicker/status/2008998834580427101). Polymarket applies per-market `seconds_delay` to marketable orders in live sports (1 s on the match I probed) and uses licensed feeds (Optic Odds metadata on markets).
- **Evidence (B):** sports monthly leaderboard winners make $1–3.7M with $4.5M–$166M volume — pro-scale operations.
- **Verdict:** ✗ for small capital (needs sub-second official data feeds, co-location; fee 0.05 and 15% rebate make it worse since 2026-07-10). NFL/CFB props currently zero-fee (§1.3) — possibly worth a look for model-based (not latency) pricing.

### 4.9 Mention markets ("Will X say Y") and tweet-count markets
- **Mentions:** `mentions_fees` rate 0.04; 289 active markets; LP rewards ~$3.1k/day. Monthly PnL board: top-1 $8.8k, top-50 sum **$80k**, #50 ≈ $560 (`/v2/leaderboard?category=mentions&time_period=month`) → **small, specialist, low-capacity niche**; edge = transcript base rates, speaker schedules, live listening. Grade B for profit pool size; no rigorous study found.
- **Tweet counts (Elon Musk # of posts, weekly/2-day buckets):** resolve on xtracker "Post Counter" (https://xtracker.live/ ; guide https://polymart.app/blog/elon-musk-tweet-count-api); strategy = pace projection + bucket structure; the 2026-09-26 live book for "Elon # tweets Sep 22–29" showed Σ best bids ≈ 1.005 (overround) with 5-share depth. Claims such as "$106k in a month" are grade C. Tweet-count markets were among the highest estimated LP-reward yields (§2.4) — again because informed flow (live counts) makes quoting risky.
- **Verdict:** viable niches for small capital with data automation (counts/transcripts), but capacity-limited; better as maker.

### 4.10 Copy trading
- **Evidence:** only grade C/D sources; common theme is that copiers get worse fills (latency, slippage), and "whales" can bait copiers (https://startpolymarket.com/strategies/copy-trading/). No rigorous study found. Leaderboards are survivorship-biased; many top PnL wallets are MMs or event insiders.
- **Verdict:** ✗ (no evidence of persistent edge net of slippage; manipulation risk).

### 4.11 Information-leakage / "insider" flow
- Academic work (ForesightFlow information-leakage score, https://arxiv.org/abs/2605.00493) documents informed pre-announcement flow; exploiting it by following flow is essentially copy trading with worse latency. Not a small-capital edge; noted for completeness.

---
## 5. Historical data for backtesting (tested 2026-09-26)

### 5.1 Price history

**A. Legacy CLOB endpoint — best for fine-grained history of old/resolved markets (for now).**
`GET https://clob.polymarket.com/prices-history?market=<token_id>&startTs=<unix>&endTs=<unix>&fidelity=<minutes>`
Tested on the resolved 2024 "Will Donald Trump win…" YES token (`21742633143463906290569050155826241533067272736897614950488156847949938836455`):

| request | result |
|---|---|
| `interval=max` (no fidelity) / `fidelity=1` / `fidelity=60` | **empty** `{"history":[]}` for this resolved market |
| `interval=max&fidelity=720` | 614 points, 12-h spacing, Jan-2024 → Nov-2024 |
| `startTs=1730419200&endTs=1730505600&fidelity=1` (1 day) | **1,440 one-minute points** |
| 7-day window, `fidelity=1` | 10,080 points |
| 15-day window, `fidelity=1` | 21,594 points (OK) |
| 16-day+ window | HTTP 400 `'startTs' and 'endTs' interval is too long` |
| `startTs` only (no `endTs`), `fidelity=1` | 31,762 points (22 days to resolution) — window cap not applied |
| `interval=1m&fidelity=1` | 400 `minimum 'fidelity' for '1m' range is 10`; `1w` min fidelity 5; presets are relative to *now* so useless for old markets |

Also tested on resolved BTC 15-min up/down markets from 2, 20, 100 and 200 days ago: `startTs/endTs` window with `fidelity=1` returned ~77 one-minute points each time, ending at ~0.9995/0.995 (the settlement drift). So **1-minute price history is still available for markets at least ~200 days old and for the 2024 election (~2 years)**. Response format: `{"history":[{"t":1730419203,"p":0.6325},…]}`. Batch version: `POST /batch-prices-history` (≤20 tokens; clob-openapi.yaml). Rate limit 1,000 req/10 s. The `p` series is Polymarket's displayed price (mid/last-trade composite) — **not executable bid/ask** [exact definition UNCERTAIN].

**Risk:** the 2026-09-04 changelog says `GET /v2/prices-history` on the data host "replaces the CLOB-hosted route". The CLOB route still works today but could be removed — **archive what you need now**.

**B. New Data API v2 endpoint** — `GET https://data-api.polymarket.com/v2/prices-history?token_id=<id>&(interval=max|all|1m|1w|1d|6h|1h | start=&end= | as_of=)&bucket_seconds=60..86400&limit≤10000&cursor=` (https://docs.polymarket.com/api-reference/markets/get-a-tokens-price-history.md)
- Documented retention: **3-hour and 12-hour series permanent back to 2022-11-18**; fine grains are windowed with minimums of **1-minute ≥ 7 days, 5-minute ≥ 60 days, 30-minute ≥ 90 days**; explicit `start/end` windows cap at 15 days. Resolved markets end with a settlement point (`resolution_seconds: 0`, price 0/1).
- Verified: for the 2024 election, `interval=max` → 615 points at 12 h (with pagination); `bucket_seconds=60` on a 2024 day → **empty**; for a BTC 15-min market 2 days old, 60-s buckets returned 76 points, but for 20/100/200-day-old markets 60-s buckets were **empty** (v2 only keeps 1-min ~7+ days). → **For backtests of short-horizon strategies use the CLOB route (A) while it lasts**, or third-party archives.

### 5.2 Trade history

- **Data API v1** `GET https://data-api.polymarket.com/trades?market=<condition_id>&limit=&offset=` — documented caps `limit ≤ 500`, `offset ≤ 1,000` (changelog 2025-08-26), although on 2026-09-26 `limit=10000` actually returned 10,000 rows. Fields: proxyWallet, side, asset, conditionId, size, price, timestamp, outcome, outcomeIndex, name/pseudonym, transactionHash. v1 is frozen.
- **Data API v2** `GET https://data-api.polymarket.com/v2/trades?condition=<cid>&limit=500&cursor=<next_cursor>` — keyset cursor pagination (no offset), fixed **3-year window** for `condition`/`event_id`, bare feed = current+previous month, `user=` with `start/end` (`start=1` = full history). Tested: 40 pages × 500 = 20,000 rows walked on the 2024 election market with `has_more: true` still — deep history is reachable. Rate limit 300 req/10 s. Note the trade feed does not reliably flag which side was the maker.
- **Goldsky public subgraphs (orderbook, activity, positions, pnl, oi) are DEAD**: every query now returns `ENDPOINT_DEPRECATED — "paused and deprecated following Polymarket's migration to V2 — the data is stale and incorrect"`, pointing to the paid Goldsky Edge Data API (https://edge.goldsky.com/data/docs/). Goldsky/ClickHouse "CryptoHouse" SQL (https://crypto.clickhouse.com), Dune and Allium remain (https://docs.polymarket.com/resources/blockchain-data.md).
- **Polymarket-v1 Database** (Qin & Yang 2026, https://arxiv.org/abs/2606.04217): complete on-chain trade archive of the V1 CTF Exchange **2022-11-21 → 2026-04-28**, 1.20 B trades, 1.30 M markets, $61 B volume, with ground-truth aggressor side and CTF split/merge/redeem events; ~52.7 GB Parquet, CC-BY-4.0, **https://huggingface.co/datasets/TimeSeventeen/Polymarket-v1**. No order-book data. Stops at the V2 cut-over.
- Dune starter queries: volume https://dune.com/queries/6545441 , TVL https://dune.com/queries/6588784 , OI https://dune.com/queries/6555478 ; dashboards e.g. https://dune.com/hildobby/polymarket , accuracy https://dune.com/alexmccullough/how-accurate-is-polymarket .

### 5.3 Order-book history

- **Polymarket provides no historical order-book endpoint.** Only live `/book`, `/books` and the WebSocket market channel (`wss://ws-subscriptions-clob.polymarket.com/ws/market`, https://docs.polymarket.com/api-reference/wss/market.md). You must record it yourself.
- **Free third-party archive:** https://archive.pendulumflow.com/ — hourly Parquet files of Polymarket order-book events/snapshots, eras from **Feb-2026 to present** (V1/V2 "snapshot grade" mirrors of third-party captures with gaps, V3 own multi-recorder capture with µs timestamps), no key/no rate limit. Verified reachable: `https://archive.pendulumflow.com/v3/2026-09-25/10/2026-09-25T10.parquet` → HTTP 200, **1.2 GB for one hour** (all markets). Quality/completeness per their site: V1 misses ~1/3 of traded markets, V2 ~1/8. **[Independent validation not done.]**
- Paid vendors (not evaluated): Telonex (https://telonex.io/), PolymarketData (L2 from Aug-2025, https://www.polymarketdata.co/), PMData (https://pmdata.dev/).
- NBA order-book study used 75 M snapshots across 173 games (own collection) — https://arxiv.org/abs/2605.00864.

### 5.4 Other useful live/meta endpoints
- Gamma markets/events: `GET https://gamma-api.polymarket.com/markets/keyset?…&after_cursor=` (≤100/page), `/events/keyset`, `/markets?slug=…&closed=true` (note `closed` defaults to **false** since 2026-04-09 — resolved markets are invisible unless you pass `closed=true`).
- Resolution lifecycle: `GET https://data-api.polymarket.com/v2/resolutions?condition=…`.
- Leaderboards / PnL: `/v2/leaderboard`, `/v2/user-pnl`, `/v2/holders?include_pnl=true` (useful for studying who profits; https://docs.polymarket.com/migrate/data-api-v1-to-v2.md).
- Reference prices for crypto markets: PolyBolt WS `wss://ws-live-v2.polymarket.com/ws` (Chainlink TWAP, crypto, equity prices; needs CLOB API creds) — the exact settlement feed for up/down markets.

---

## 6. Ranking for a small-capital (≈$1k–$10k) Polymarket-only operation

| # | Edge | Evidence grade | Why it may work for small capital | Main risks / decay | First test to run |
|---|---|---|---|---|---|
| 1 | **Reward-aware passive MM** in low-competition rewarded markets (weather 0.5–3 d, culture, finance, economics, mentions); post-only, 20–100-share quotes, pull around information events; add maker rebates; park idle cash in hedged holding-reward positions (3.25% APY) | A (own API measurement of pools & competition) + B (Polymarket interview: $10k → $200–800/day in 2024 when pools were bigger) | Paid by Polymarket, not by beating other traders; min sizes are tiny; pools are fragmented across 16k markets that pros ignore | Adverse selection (weather obs, forecast updates, counts); pools are discretionary; ghost-fill reversals; needs always-on bot + fast cancels | Paper-quote 50–100 weather/culture markets for 1–2 weeks: log `/order-scoring`, `/rewards/user/percentages`, fills and mark-outs; compare rewards vs adverse-selection loss |
| 2 | **Weather markets with external forecasts/obs** (ECMWF/GFS ensembles 1–3 d ahead; ASOS/METAR same-day), executed maker-side where possible | B (category leaderboard: 30-day top-50 PnL $586k; all-time top-50 $3.2M) + C (open-source bots) | Cheap public data, daily repetition (≈100 cities × high/low), low capital needs, 0.05 fee rate, big LP pools | Bots have compressed edges since 2025; bucket rounding & station quirks; taker fees heavy on cheap buckets | Backtest forecast-implied bucket probabilities vs CLOB 1-min price history for resolved weather markets (§5.1) |
| 3 | **Selective favourites / resolution-lag "bonds"** (≥90¢ where the outcome is effectively known; categories with positive favourite returns: crypto/politics; avoid sports favourites) | A (FLB paper: ≥90¢ +0.28–0.83%/$ pre-fee; category split) + C (practitioner threads) | Fees tiny in $ near 1; no speed race if the edge is rule/data interpretation; scales down well | Tail/resolution/dispute risk (≈1% disputed), capital lock-up, low % returns | Backtest: buy at T−1h/T−1d when p∈[0.90,0.99] by category, fee-adjusted, using 1-min history + `/v2/resolutions` dispute flags |
| — | Worth a look, lower confidence | | Mentions/tweet-count niches (capacity-limited, top-50 monthly mentions PnL only $80k); NFL/CFB zero-fee props (model-based pricing); late-window TWAP math in 5m/15m crypto (hypothesis) | | |
| ✗ | Deprioritise | | Taker arbitrage (fee-negative), 15-min crypto latency (fees + 150 ms delay + TWAP), sports latency (pro feeds, delays), copy trading (no evidence), "nothing ever happens" (unverified; base rate already priced) | | |

