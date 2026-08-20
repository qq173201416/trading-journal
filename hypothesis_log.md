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

---

2026-08-19: TOOLING NOTE (per step-16, not a strategy parameter change) --
the 15:39 ET run's parallel per-symbol subagent fan-out (9 new candidates
plus a combined MRK/URGN verification task, 10 subagents total) mostly
completed in under 2 minutes each, but 6 of the 10 took ~19.6-19.7 million ms
(~5.5 hours) of wall-clock time apiece for reasons not diagnosed here
(execution-environment/tooling delay, not a data or logic problem --
sequential API calls and computations inside each agent were correct once
they ran). This pushed the run's actual write-back to well after 21:00 ET,
past the 16:00 ET market close, even though every market-data snapshot used
(SPY quote, scan results, per-symbol quotes/historicals) was captured within
the legitimate 15:37-15:39 ET execution window. No trading decision was
affected this run: all 20 scanned candidates independently failed
base_accumulation_pass on hard structural grounds (weekly EMA30 hard-breaks
or blown-out daily base ranges), so no entry would have been placed
regardless of when the write-back completed. Risk: if a future run's fan-out
hangs like this AND a candidate would otherwise qualify, the entry could get
priced/logged well after the snapshot was taken, close to or past market
close. Idea for future runs (not executed, still a strategy/orchestration
question, not decided here): cap how many candidates get full parallel
subagent evaluation per run, or set a hard wall-clock budget per subagent
with a "insufficient_time_to_evaluate" fallback cancel_reason instead of an
unbounded wait, so a slow tool call can't silently drag the whole run's
write-back past market close. Not executed -- no code/logic or strategy
parameter changed this run, just a tooling risk observation.

---

2026-08-20: RESOLVED (infrastructure fix per step-16, not a strategy
parameter change) -- root cause identified for both the file-collision
incident above and the 2026-08-19 multi-hour delay: this routine's execution
session has an allowed_tools list of Bash/Read/Write/Edit/Glob/Grep/
WebFetch/WebSearch only -- the Agent/Task tool used to fan out parallel
subagents is not on it. Spawning subagents anyway triggers a permission
request that, in an unattended scheduled run, nobody is present to approve;
the run then stalls until either it times out or a human happens to log in
and approve it manually, which is what produced the ~5.5 hour and
multi-hour delays observed. This is not a performance optimization the
routine opted into -- it's an unauthorized-tool-use failure mode that
happened to sometimes still produce correct (if very late) output. Fix:
the routine prompt now contains an explicit, high-priority prohibition on
Task/Agent tool use and any parallel/background subagent fan-out for
per-candidate computation -- every candidate must be processed sequentially
in the single main thread, same constraint already in place on the Scanner
routines. This removes both the file-collision class of bug and the
permission-stall/delay class of bug at the source, since no subagent is ever
spawned. No strategy thresholds, entry/exit rules, or frozen parameters were
touched -- this is an execution-model constraint, not a strategy change.

---

2026-08-20 11:38 ET: INFRASTRUCTURE FAILURE (per step-16, not a strategy
parameter change) -- `git push` failed this run with
`fatal: could not read Username for 'https://github.com'`. The execution
container has no git credential helper configured
(`git config --get credential.helper` is empty, no ~/.git-credentials, no
GIT_ASKPASS), so HTTPS pushes to origin cannot authenticate. Anonymous
`git fetch`/`git pull` still work because the repo is public, which means
the failure is silent on the read path and only surfaces at write time.
This is a regression within the same trading day: the 10:37 ET run of this
same routine pushed successfully (commit 357d04e is on origin), so
credentials were present earlier this morning and are absent now. Retried
the push 3x with backoff per the routine's git instructions; all three
failed identically -- this is an auth failure, not a network flake, so
retries cannot fix it. The GitHub MCP server IS still authenticated
(get_me returns qq173201416), which is how this note reached the repo.
Impact this run: NONE on strategy state. The scan returned 0 candidates,
there are no open positions, and virtual_account.json /
rs_score_cache.json / weekly_base_quality_cache.json are all byte-identical
to origin -- the only thing that failed to persist is one risk-check log
line in trader_history.jsonl, recording a run in which nothing happened.
That line is reproduced here so it is not lost entirely:
{"date":"2026-08-20","time":"11:38 ET","virtual_equity":100000.00,
"weekly_pnl_pct":0.0,"weekly_loss_breaker_triggered":false,
"current_position_count":0,"position_limit_triggered":false,
"daily_risk_used_pct":0.0,"daily_risk_limit_triggered":false,
"spy_change_pct":-0.4148,"black_swan_triggered":false,
"new_entries_allowed":true}
trader_history.jsonl itself (441KB) was NOT rewritten through the MCP
Contents API, because that API requires resending the entire file body and
hand-reproducing 514 lines of accumulated history risks corrupting real
trade records to save one no-op entry -- not a trade worth making.
RISK GOING FORWARD, needs a human fix: every subsequent hourly run will hit
the same wall, and a run that actually opens or closes a virtual position
will lose that position's state at container teardown, silently desyncing
virtual_account.json from the trades recorded against it. The routine also
has no PushNotification tool in its allowed list, so it cannot alert anyone
when this happens -- this file is the only channel it has. Fix needed:
restore git credentials in the scheduled-run environment (credential helper
or tokenized remote URL). Not executed as a strategy change -- no
thresholds, entry/exit rules, or frozen parameters touched.
