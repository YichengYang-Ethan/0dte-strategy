# Round 3 Follow-up — New Information + Strategic Pivot Question

Thank you for Round 1 and Round 2. I acted on the Day 4 instrument sanity check you prescribed and the results matched your hypothesis — spot has edge, option wrapper eats it. Now I have a completely new set of information from my friend Joey that changes the decision. I need Round 3.

## What changed

I re-read Joey's full WeChat history end-to-end, with specific attention to execution and infrastructure details I had glossed over. Major corrections to my prior belief about his bot:

### 1. Joey's bot is **fully automatic**, not discretionary

I had told you his bot "outputs signals and he clicks manually." That was wrong. His own words:

> Me: "so is your bot outputting information or placing trades directly?"
> Joey: **"directly trading. connected to the broker API."**
> Joey: "yesterday it used market orders and got baited by fake-depth orders, lost me a few hundred bucks. I changed it to limit bid-ask."

He uses **moomoo API** (IB does not give him options permissions). His bot runs locally (not AWS — "because the bot is still half-finished, I have to watch it"), but watching = monitoring for bugs, not making trading decisions. Trade execution is fully auto.

### 2. His holding horizon is precisely defined

- **Single stocks** (NVDA, MRVL, CRDO, NFLX): **minutes to ~1 hour** after signal triggers
- **Indices** (SPX): **1–3 hours** "slow grind"
- Quote: "generally once it's started, everything except indices moves fast"

### 3. His bot has an exit bug he hasn't fixed

Direct quotes:
> "+120% and the bot still took a loss"
> "this one went from 0.25 to 0.67 [should have locked profit]"
> "most infuriating trade"

So his claimed 70% win rate is **despite** a broken exit. If exit is fixed, the WR could be higher — or the 70% claim is already hopeful and the exit bug eats actual realized PnL.

### 4. Payoff profile is precisely asymmetric

- **70% win rate**
- **Losses capped at about −40%** (not −100%, because he exits before expiry)
- **Winners often +100% to +1500%**

This is convex 0DTE option payoff — lottery-like positive skew, small-loss / big-winner distribution.

### 5. Data stack — Massive is "essential" not "luxury"

- Theta Data streaming "often disconnects" → not safe for live
- He switched live-trading to **massive.com WebSocket, $200/month**
- He still uses Theta for historical backtest
- His quote: "bot makes more than $200/day, so it's worth it"

### 6. Capacity is hard-capped ~$1M

> "single-symbol order over 1k contracts, you will be hunted by MMs"
> "SPX might go a bit higher, but over 10k contracts you will get hit"
> "my bot maxes out around 1M"

This is **retail-only alpha** — impossible to scale institutional size. And it's explicitly why he won't publish: "real money strategies should never be published, once published they die."

### 7. Core thesis in his own words

> "I basically follow the market maker"
> "My job is to predict what the market maker will do"
> "Longs and shorts use options to hijack the MM → MM then pushes the price"

Critically: **follow MM, do not fight MM**. This is important because it means his thesis is **not** "dealer short gamma → price pins at walls" (the traditional Barbon-Buraschi / SpotGamma story). His thesis is closer to: "identify the strike where MM inventory forces them to push price, then ride along."

### 8. Extraordinary prediction claim

> "My model has successfully called SPX closing price for 8 consecutive days"
> "intraday it varies, but close-to-close is basically accurate"

If true, this is not a "signal" — it's a gold mine. If it's survivorship / selection bias in his memory, it's Joey-telling-himself-stories. I cannot distinguish from outside.

### 9. Specific bot output he showed me

"$7175 is where someone was pushing hard → MM gamma exposure → long target zone → bears broke it with news → longs gave up → target migrated to $7125 → closed at $7126"

I asked him explicitly: "was this your observation or the bot's output?"
Joey: **"the bot's output."**

Either he has a narrative-generation layer on top of numeric signals, or he has a rule that outputs strike + direction + justification tag, or he's retconning. I can't tell.

### 10. News/front-running observation (operationally useful)

> "Recently there's been a lot of front-running — unusual option flow appears before the news breaks"
> "By the time you see the news, they're already unloading at the top"

This means **unusual option flow 30–60 minutes before news** is a lead indicator a bot can catch.

### 11. JPM collar hedge levels (mentioned in passing)

> "JPM + SPX have huge collars at 6180/6845"
> "below 6180 there's no step protection, next floor is 5400"

This is specific institutional positioning info that matters for systemic-risk tail modeling.

### 12. Moomoo vs IB specifics

- IB does not give him options permissions (so he can't use IB for 0DTE)
- He uses moomoo API (which is known-clunky for algorithmic trading but works)
- I do have IB approved for options, so I could in principle use IB

## The decision I'm facing

Given everything you said in Rounds 1 and 2, and given this new information, I have three candidate paths:

### Path A — Your Round 2 prescription, unchanged
- Validate v5 as a delta-one strategy on SPOT/MES
- Paper trade spot primary + long-call audit
- Budget: $0 additional data (keep current Theta Standard $80)
- Time: 2–3 weeks to 30–50 live signals

### Path B — Pivot to replicating Joey's intraday 0DTE bot
- Upgrade to Theta Options Pro $160/month (intraday 1-min quotes + Greeks + OI)
- Optionally add massive.com $200/month for live streaming (or stay on Theta streaming and accept reconnects)
- Rewrite the engine from EOD swing to bar-level intraday replay
- Implement Joey's architecture: 11 raw features + aggregated + cross features + per-symbol specialization
- Fully auto bot on SPX 0DTE (European cash-settled, no early assignment) via IB API
- Budget: $160–360/month data + ~6–8 weeks engineering
- Time to paper trade: ~2 months

### Path C — Run both in parallel (expensive but thorough)
- Ship Path A in 2 weeks (current infra already 80% there)
- Then start Path B as a longer project
- Budget: Path A first, then $160/mo later
- Time: A ships fast, B is the "real project"

## Constraints

- IB paper account with options permissions available.
- moomoo OpenD running locally as an alternative broker.
- Prior experience writing auto-execution bots (Python, broker APIs).
- Data budget: up to $360/month is acceptable.
- Engineering budget: 6–8 weeks of evening/weekend work.

## Questions for Round 3

### Q1. Does the "Joey bot is fully auto" fact change your instrument recommendation?

In Round 2 you said Path A (spot/MES delta-one) is correct **for research now**, partly because 1DTE options are a bad wrapper for an EOD drift signal. But Joey's actual strategy is NOT "EOD signal + overnight long call." It's **intraday signal + intraday option structure (butterfly / spread / ATM call)**, held 1–3 hours, fully automated, with limit-bid-ask execution.

This is a different strategy family entirely. Does your "long-option wrapper eats the edge" analysis still apply? Or is a 1-hour intraday option scalp a fundamentally different P&L geometry than an overnight 1DTE carry trade?

### Q2. Is replicating Joey's bot (Path B) feasible in 6–8 weeks for an experienced undergrad?

Specifically:
- Is Theta Options Pro $160/mo sufficient, or do I need massive at $200?
- Is 3 months of historical 1-min SPX 0DTE data enough to avoid overfitting his style of rule-based engine?
- Is tick-rule-based aggressor classification (from Theta trades+quotes) a viable substitute for Cboe Open-Close or massive's pre-classified aggressor side? How much accuracy do I lose?
- Is doing this on SPX (European, cash-settled) strictly better than SPY (American, physically settled) for a 0DTE bot, given assignment / pin-risk / dividend concerns you raised?

### Q3. What's the actual EV of Path B given 0DTE's properties?

Joey claims 70% WR with convex payoff. I should assume at least 30–50% haircut on self-reported numbers. If true pattern is closer to 55% WR with +80% winners / −40% losers, what does that look like after:
- Execution slippage (limit bid-ask with partial fills during fast markets)
- Bid-ask widening during the exact moments signals fire (news, flow surges)
- Competition from other 0DTE retail / MM gamma desks that grew 10× post-2023
- Capacity-induced market impact at $50–200k notional

Is this a project that has a plausible Sharpe 1–2 after realistic frictions, or is it more likely to end up at Sharpe 0.3 and a rough drawdown year?

### Q4. Strategic ranking of A / B / C / D

Please rank with explicit reasoning:
- **A** — ship fast, clean delta-one validation on SPOT/MES, no data upgrade
- **B** — full pivot to replicating Joey's intraday 0DTE bot, ~6–8 weeks
- **C** — A first (2 weeks), B as longer-term project
- **D** — something else entirely (please name it)

### Q5. Red flags in Joey's self-report to watch for

His "70% WR", "8 consecutive days correct SPX close prediction", "bot makes $200+/day" are self-reported, not logged. What specific tells should I look for if I end up working with him more closely that would indicate the claims are much softer than they sound? What should I ask him for that would actually prove it?

### Q6. Timestamp / leakage concerns specific to Path B

If Path B uses 1-minute bars from Theta with EOD-updated OI (i.e. OI is yesterday's snapshot, not today's intraday), what's the correct way to handle this?

- Is yesterday's OI close enough to today's intraday OI to compute meaningful intraday GEX? (MM inventories don't turn over that much hour-to-hour, but new OI opens every morning)
- If Joey uses massive.com's live OI-equivalent (they claim aggressor-signed volume live), do I need that, or is yesterday's OI + today's signed-volume-proxy-from-tick-rule acceptable?

### Q7. My implicit "why not buy data tomorrow" question

Currently I'm over-thinking this because $160–360/mo feels like a lot for an undergrad. Your pushback (in Round 1) that Theta tiers actually cover what I need for well under $200 was a real update. Is there any reason I shouldn't just subscribe to Theta Options Pro tonight and start downloading data while I decide on Path A vs B?

## Format for your response

Please rank A / B / C / D with explicit reasoning. If the answer is "subscribe to Theta Pro and ship Path A; revisit Path B only after you've done Path A properly," say so.

Extended thinking. Brutal honesty.
