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
