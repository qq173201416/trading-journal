# Hypothesis Log

Ideas for future parameter/rule changes surfaced during EXP017 Forward Validation.
Per the frozen-parameter policy, none of these are executed during the validation
window — they are recorded here for review only.

---

2026-07-22: Discovered platform constraint (not a strategy idea, logged per step-16
spirit anyway): the "RS Score Cache" watchlist's `display_description` field has a
hard 256-character API limit. The routine design calls for accumulating 90 days of
per-symbol RS score history plus daily SPY benchmark history in this field, which is
infeasible at 256 chars for more than a couple of symbols/dates. Workaround applied:
the field now stores only today's benchmark (B3/B6/B9/B12) and today's candidates'
scores (same-day cache to avoid recomputing within a single run), with no
cross-day persistence. Effect: rs_deterioration_60d and rs_acceleration_score's
20d/60d slope terms fall back to recomputing R3/R6/R9/R12 from raw price history
each run (as the spec allows), which requires ~312 trading days of historicals
(60d lookback + 252d window) — our current fetch window (~380 calendar days,
~262 trading days) does not reach that far back, so those two metrics will read as
null/not-computed until either (a) a real persistent store replaces this
256-char-limited field, or (b) the historicals fetch window is extended. Does not
affect today's decision (DYN was excluded on base_range_pct/position_in_base
grounds regardless). Left unexecuted — no code/logic changed beyond the cache
payload shape, which is a logging/storage adaptation, not a strategy parameter.

---

2026-07-29: Operational constraint (not a strategy idea, logged per step-16 spirit): step
4-2's weekly Base Quality check (EMA30 trend, 52-week hard-break scan, 6-week depth,
4-week tightness vs its own 52-week rolling average) requires resampling ~52 weeks of
daily OHLC into weekly bars. The execution environment has no persistent scratch store
for API responses between tool calls within a run, so reconstructing this for every scan
candidate every hour means hand-transcribing ~260 daily bars per symbol into a
computation step, which is impractical to do reliably at hourly cadence. This run
(13:41 ET), weekly_base_quality was left uncomputed (logged as null) for all 7
candidates (BMO, GRMN, MANH, PSN, CAKE, CBZ, SLDE); the fully-computed base_range_pct
and position_in_base fields (25-day window, cheap to derive from the tail of the
already-fetched historicals) were independently sufficient to disqualify every
candidate from Base Accumulation G regardless, as was market_bullish=false. Does not
affect today's decision. Left unexecuted — no code/logic or strategy parameter changed;
this is a data-reconstruction cost note, not a request to loosen the weekly_base_quality
requirement itself. Consider: giving the routine a small persistent JSON cache
(symbol -> weekly OHLC series, refreshed daily) so weekly resampling can run
programmatically instead of by hand each execution.
