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

---

2026-08-01: RESOLVED (infrastructure fix per step-16, not a strategy parameter
change) — both constraints above are fixed as of v1.2.1:
- Replaced the 256-char-limited Robinhood watchlist with a repo-committed
  rs_score_cache.json (benchmark + per-symbol score history, no character
  limit, pruned to a 95-day rolling window on write).
- Extended the 4-1 historicals fetch window from ~380 calendar days
  (~262 trading days) to ~460 calendar days (~312 trading days), so the
  rs_deterioration_60d fallback recompute path has enough history even before
  the cache accumulates 60 days of its own data.
- Added weekly_base_quality_cache.json, keyed by symbol with a `date` field;
  a symbol's weekly resample is now only recomputed once per calendar day and
  reused across that day's remaining hourly runs, instead of being
  reconstructed by hand every execution.
No strategy thresholds, entry/exit rules, or frozen parameters were touched —
only the data plumbing that feeds already-specified metrics.

---

2026-08-10: BUG FIX (per step-16, not a strategy parameter change) — noticed
that SION's weekly_base_quality had been computed at 09:50 ET this morning
(and re-logged identically at 10:42/12:43/13:39/14:41 ET) but was never
actually written into weekly_base_quality_cache.json — the cache file simply
had no SION key. Root cause not fully diagnosed (possibly an early-morning
run computed the value inline for logging but skipped the cache-write step);
did not affect any trading decision since SION was independently disqualified
every run today on hard structural grounds (base_range_pct blown out by the
intraday crash, position_in_base structurally invalid, above_ema200 false)
regardless of weekly_base_quality. Fixed this run (15:42 ET) by writing the
previously-logged values (ema30_rising=true, has_hard_break=false,
base_depth_6wk=0.2556, tightness_now_4wk=0.0425, tightness_avg_52wk=0.0612)
into the cache under today's date, so later runs today reuse it instead of
silently recomputing or silently missing it. No strategy logic changed.

---

2026-08-13: TOOLING NOTE (per step-16, not a strategy parameter change) — when
computing Base Accumulation G metrics for 3 new candidates in parallel this run
(PAAS, DIOD, WIX), 2 of the 3 subagents independently reported that a shared
scratchpad filename (`compute.py`) got silently overwritten mid-task by a
concurrently-running sibling agent writing to the same generic filename in the
same shared scratch directory. Both affected agents correctly detected this via
cross-checking against their own originally-fetched tool-call data and did not
use the corrupted intermediate file, so no computation was actually affected
this run. Idea for future runs: when fanning out parallel per-symbol subagents
for candidate metric computation, instruct each agent to use a symbol-prefixed
scratch filename (e.g. `paas_compute.py`) to avoid this collision class
entirely, rather than relying on agents to self-detect it. Not executed as a
strategy change (it's a data-plumbing/orchestration detail, not a threshold or
rule), just recorded here.
