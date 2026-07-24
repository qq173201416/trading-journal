# YMAG Paper Trading Routine — Intraday Execution Variant — claude/ymag-paper-state-intraday

Reference copy of the Claude Code Routine prompt running against this
branch. This is documentation only — the routine itself is configured at
claude.ai/code/routines and reads/writes this branch directly, not this
file.

Repository: `trading-journal`
Branch: `claude/ymag-paper-state-intraday` (fixed, orphan — independent
from `claude/ymag-paper-state` (v1.0, close-price accounting),
`claude/scanner-state`, and every other branch in this repo. No read/write
interaction with any of them, and no shared `data/prices/` — this branch
maintains its own separate 9-symbol price history.)
Branch permission: default

This is **paper trading only**. The routine never calls any real
order-placement or account-action tool. "在開市時間執行" means the routine
runs during real market hours and prices its simulated fills off live
bid/ask quotes — it never sends a real order.

## Relationship to v1.0 (claude/ymag-paper-state)

Same buy/sell rules as v1.0, but with **decision basis and execution price
separated**: technical signals are computed from T-1 (yesterday's
already-settled close) to avoid look-ahead bias, while the simulated fill
price uses today's live bid/ask at execution time instead of today's
close — a closer approximation of a real live-market fill.

**This is the only YMAG routine actually scheduled to run.** v1.0's branch
and files exist in the repo (as the design this variant builds on) but has
no active Routine trigger — by decision, only this intraday/live-quote
variant runs on a schedule, since it's the more realistic simulation of
actual execution.

## Revision history

**Round 1 (before first run):** two issues found reviewing the draft:
idempotency check was sequenced before branch checkout (moved to after
`git pull`); `total_account_value` was recomputed before dividend routing
and the decision engine could still change cash/share fields (moved to
after the decision engine).

**Round 2 (before first run):** fixed 14:15 UTC schedule maps to 09:15 ET
during EST — earlier than the routine's own 09:35 ET time-window guard,
so it would silently no-op all winter. Rescheduled to 15:15 UTC.

**Round 3 (this revision, based on a second external review):** the live
deployment had drifted from the intended design (its schedule got set to
fire hourly across the whole session instead of once daily), and a second
review surfaced four more issues worth fixing before starting Paper
Trading in earnest. All four are incorporated below:

1. **Non-deterministic execution time.** The trigger was firing on an
   hourly cron across the whole session (`30 13-19 * * 1-5`) instead of
   once a day. The idempotency+time-window guards happened to make it
   *converge* to roughly one execution per day, but which hour actually
   executed was not fixed, so the same T-1 signal could fill anywhere
   from just after open to mid-afternoon — at potentially very different
   live prices. It also spun up 6-7x more sessions per day than needed,
   and created a narrow but real race window: if one firing was still
   mid-execution (multi-minute run: 9 symbols of history, two dividend
   web-fetches, a quote call, git operations) when the next hourly firing
   started, both could pass the idempotency check before either had
   pushed, and independently compute and push conflicting trades.
   **Fix:** single fixed daily trigger at 15:15 UTC (11:15 EDT / 10:15
   EST) — one deterministic execution point per day, DST-safe, no race
   window, no wasted sessions.
2. **No gap filter on buys.** A buy decided from yesterday's close could
   still execute at today's live ask even if today's price had already
   gapped hard in either direction by the time of execution — chasing a
   price the T-1 signal never actually confirmed, whether that's buying
   into a falling knife (gap down) or paying a premium the tranche sizing
   never accounted for (gap up). **Fix:** a symmetric gap gate — if
   today's live price has moved ≥5% from T-1's close in either direction,
   skip the buy for today and let tomorrow's fresh T-1 data re-evaluate.
3. **No same-day trade-direction lock.** `TRIM_PROFIT`/`TRIM_SEASONAL`
   don't share the hard macro gate that keeps the other four sell
   conditions mutually exclusive with buying, so a same-day sell-then-buy
   (or buy-then-sell) was theoretically possible even though the buy and
   sell checks were sequential in the same run. Real settlement makes
   same-day round-trips on the same tiny position awkward and it doesn't
   match this strategy's "build a dividend base position" intent anyway.
   **Fix:** if a sell action executes in a run, buy conditions are no
   longer checked at all that day — at most one directional action per
   day.
4. **Quote fetch had no retry, and account marking used the bid/ask
   midpoint instead of last trade.** A single transient `get_equity_quotes`
   hiccup skipped an entire day's trading, which is more fragile than
   necessary for what's usually a brief API blip. Separately, marking
   `total_account_value` off `live_mid` can misstate value when the
   spread is wide (mid isn't necessarily close to where the ETF actually
   last traded). **Fix:** retry the quote call up to 3 times (~30s apart)
   before giving up for the day; mark `total_account_value` and floating
   P&L off `live_last` instead of `live_mid` (mid is still used for
   `spread_cost_pct`, where it's the correct reference).

**Round 4 (this revision, based on a third external review):** four
refinements, none of which change the core design, all confirmed sound by
review:

1. **Fixed 09:45 ET instead of a DST-drifting single UTC time.** Round 3's
   15:15 UTC (11:15 EDT / 10:15 EST) was judged too late and, more
   importantly, not truly fixed — the ET wall-clock time it lands on
   drifts by an hour across DST. Since this platform's cron only runs in
   UTC (no DST-aware scheduling), a genuinely fixed ET time requires
   nudging the cron value at the DST boundary rather than a single
   set-and-forget value. **Fix:** cron set to `13:45 UTC` (= 09:45 EDT),
   correct for now (EDT runs roughly mid-March to early November). It
   must be changed to `14:45 UTC` when EST begins (~early November) and
   back to `13:45 UTC` when EDT resumes (~mid-March) — otherwise this
   silently reintroduces the exact Round 2 bug (a stale UTC value drifting
   outside the intended ET window, and potentially outside the 09:35 ET
   time-check guard, causing silent no-ops). This is a recurring
   maintenance item, not a one-time fix — flagged here so it isn't
   forgotten at the next DST transition.
2. **Gap filter made asymmetric.** Round 3's gap filter blocked a buy on
   either a big gap up or a big gap down. On reflection, gap-down before a
   buy isn't the same risk for a dividend-income ETF that gap-up is — a
   lower entry price usually just means a higher effective yield on that
   tranche, consistent with the strategy's "build the position, don't
   time it perfectly" intent. Gap-up is the one worth blocking: it means
   chasing a price the T-1 signal never confirmed, at a premium the
   tranche sizing didn't account for. **Fix:** only skip the buy when
   `gap_pct > +5%` (today's live price already up more than 5% from T-1
   close); gap-down no longer blocks a buy at all.
3. **Recovery Buy cooldown.** Without a minimum wait after a
   `TRIM_MAG7_BREADTH`/`TRIM_MARKET_TREND` cut, a choppy market could in
   principle trigger trim-then-recover-then-trim-again in quick
   succession. **Fix:** added `recovery_pending_since` (the date of the
   triggering trim) to `state/ymag_position.csv`; Recovery Buy now also
   requires at least 2 trading days (counted from `data/prices/YMAG.csv`,
   not naive weekday counting, so market holidays aren't miscounted) to
   have elapsed since that date.
4. **Slippage tracking.** Added `t1_close` and `slippage_pct` (=
   `(execution_price − t1_close) / t1_close`) to every trade log entry —
   distinct from `gap_pct` (which measures market movement using
   `live_last`, independent of the bid/ask spread). Slippage captures what
   was actually given up (gap *and* spread) relative to the T-1 reference
   price the signal was computed against, for later analysis of whether
   spread cost is eating the strategy's edge.

The dividend-detection layer is written out in full here rather than "see
v1.0" — a routine's executing agent has no access to another branch's
routine text and is explicitly barred from reading `claude/ymag-paper-state`
to look it up, so this prompt has to be self-contained.

---

## Routine — YMAG Intraday Signal & Paper Trade

Trigger: Schedule, weekdays, **13:45 UTC only** (= 09:45 ET, currently
EDT). Do NOT set this to an hourly or multi-hour range — see Round 3 fix
#1 above for why. **DST maintenance:** this value must change twice a
year to stay fixed at 09:45 ET — `13:45 UTC` during EDT (~mid-March to
early November, current setting), `14:45 UTC` during EST (~early November
to mid-March). See Round 4 fix #1 above.
Repository: trading-journal

```
【執行時機檢查,必須在分支持久化之前先做】
用 Bash 執行 `TZ=America/New_York date +"%u %H:%M"`,確認 (a) 星期一到五
(b) 時分在09:35到15:55之間。這是一道防呆(例如萬一被手動誤觸發、或遇到
假日),正常情況下這個routine只在13:45 UTC(=09:45 ET)這個固定時間點被
排程觸發一次,執行時間本身應該每天一致。【重要,需要季節性維護】因為排
程平台的cron只認UTC、不會自動處理夏令時,13:45 UTC只在夏令時(EDT)期間
等於09:45 ET;冬令時(EST,約每年11月初到隔年3月中)開始時,這個cron必須
手動改成14:45 UTC才能維持09:45 ET不變,否則會悄悄重演Round 2修過的那個
bug(UTC值沒跟著調整、實際執行的美東時間跑掉,甚至可能落在09:35的時機
檢查門檻之前導致每天空跑)。任一時機檢查條件不成立就直接結束,不做任何
git操作。

【分支持久化,第一步必做】
git fetch origin claude/ymag-paper-state-intraday
git checkout claude/ymag-paper-state-intraday 2>/dev/null || git checkout -b claude/ymag-paper-state-intraday

後續所有讀寫、push,一律針對這個分支。不要與 claude/ymag-paper-state、
claude/scanner-state 或其他任何分支有讀寫互動。

git pull 拿最新版本。

【冪等性檢查:今天是否已經執行過,必須在git pull之後做】
讀取 state/ymag_position.csv 的date字段(這時已經是本分支最新已提交的版
本),若已經等於今天,說明今天這個routine已經跑過一次,直接結束,不重
複執行、不重複買賣。(這一步必須排在git pull之後——如果排在分支
checkout之前,讀到的要嘛是不存在的文件、要嘛是跟本分支無關的舊狀態,這
個防重複機制就形同虛設。)

【第一層:增量更新價格數據(YMAG本體 + SPY + 七巨頭,截至昨天收盤)】
對 YMAG、SPY、以及七巨頭(AAPL、MSFT、GOOGL、AMZN、NVDA、META、TSLA)共9個
symbol,分別檢查 data/prices/{TICKER}.csv 是否存在:
- 不存在或行數<260行:視為首次執行,用 get_equity_historicals(單一
  symbol、interval="day"、start_time設為約13個月前、end_time設為昨天)
  取得完整歷史,寫入 data/prices/{TICKER}.csv(字段:begins_at,
  open_price,close_price,high_price,low_price,volume,session),過濾掉
  interpolated=true的補值bar。
- 已存在且數據充足:讀取最後一行日期,只查詢"最後日期隔天"到"昨天"的新
  K線並追加。不查詢、不使用今天的日K線,因為今天還沒收盤,這份數據本身
  也還不存在。

【重要】get_equity_historicals一次只查一個symbol,不要合併查詢。

【第二層:計算技術特徵(全部基於T-1即昨天收盤,不含今天)】
基於 data/prices/YMAG.csv 裡截至昨天的數據,計算:
- ma20:20日收盤價均線(用昨天及之前20個交易日)
- price_vs_ma20_pct:昨天收盤相對ma20的百分比偏離
- range_pct_4w:過去20個交易日(截至昨天,收盤價)的(最高-最低)/20個交易
  日前收盤價
- consec_below_ma20:截至昨天,收盤價連續低於ma20的天數
- month_return_so_far:自然月至今(截至昨天)的開盤到昨天收盤漲跌幅
- month:當前自然日期所屬月份(用今天的日期,這個不受"T-1"限制,因為月份
  判斷不涉及未走完的K線)
- t1_close:昨天收盤價本身,記下來供下面的跳空閘門使用

這一層刻意不用"今天"任何數據,因為今天的交易日還沒結束,用還在變動中的今
天數據做判斷會有前視偏差——你會在盤中看到一個還沒定型的信號,而真實交易
裡你也只能依據"昨天收盤確認過的狀態"做當天的決策。

【第二點五層:大盤與七巨頭趨勢(同樣基於T-1)】
基於第一層截至昨天的SPY和七巨頭數據,計算:
- ma50_spy:SPY截至昨天的50日收盤均線;market_trend = "up" 若昨天SPY收
  盤 > ma50_spy,否則 "down"
- mag7_breadth:七巨頭各自截至昨天的20日均線站上情況,0-7整數
- mag7_mom_5d:七巨頭截至昨天的過去5個交易日漲跌幅均值

判斷market_trend、mag7_breadth是否"剛剛轉弱"(cross trigger)用上一次運
行存下的 prev_market_trend、prev_mag7_breadth_healthy(見第三層倉位字
段),本層只算今天要用的T-1原始數值,不做比較。

【第三層:讀取當前模擬倉位】
讀取 state/ymag_position.csv(字段:date,shares,avg_cost,cash_principal,
cash_reserved,cash_uninvested,cumulative_dividends,cumulative_realized_gain,
cumulative_dividend_cash_in,cumulative_sale_cash_in,total_account_value,
prev_market_trend,prev_mag7_breadth_healthy,recovery_pending,
recovery_pending_since,status)。
若不存在,視為空倉,初始化 shares=0, cash_principal=100, cash_reserved=0,
cash_uninvested=0, cumulative_dividends=0, cumulative_realized_gain=0,
cumulative_dividend_cash_in=0, cumulative_sale_cash_in=0,
prev_market_trend="up", prev_mag7_breadth_healthy=true,
recovery_pending=false, recovery_pending_since=(空), status="flat"。
初始模擬本金:$100,全部放在cash_principal裡,初始 total_account_value=100。

資金流規則:
- invested_tranches = (shares × avg_cost) / 25,用於判斷是否還能加倉,不
  用單獨維護計數器
- 買入時優先扣cash_reserved,不足從cash_principal扣;賣出所得全部計入
  cash_reserved,avg_cost賣出時不變
- shares允許小數(碎股處理),本金規模小,取整會造成明顯的資金利用率損失

【第三點五層:實時報價(含重試)】
調用 get_equity_quotes(symbols=["YMAG"]) 取得當下(routine執行這一刻)的
bid_price、ask_price、last_trade_price。記為 live_bid、live_ask、
live_last。
- 若任一必要欄位缺失,或明顯不合理(例如bid/ask為0或負數、bid>ask):
  間隔約30秒後重試,最多重試3次(即最多共嘗試4次)。仍未取得有效報價,
  才視為本次無法取得報價(見下方失敗處理)。
- live_mid = (live_bid + live_ask) / 2,只用於計算spread_cost_pct,不用
  於帳戶估值(見下方"標記價格"說明)
- 若買入條件成立,模擬買入的實際成交價 = live_ask(買方要付出的價格)
- 若賣出條件成立,模擬賣出的實際成交價 = live_bid(賣方能拿到的價格)
- spread_cost_pct = (live_ask − live_bid) / live_mid,記錄下來,方便回頭
  看這個策略實際執行時付出的價差成本有多大

本次執行全程只拉一次報價(含重試在內算同一次),複用同一組live_bid/
live_ask/live_last數值,不需要在後面的層重新拉取。

若重試後仍沒有返回有效報價,本次不執行任何買賣判斷,只更新價格歷史和分
紅檢測,在報告裡註明"本次未能取得實時報價(已重試3次),跳過買賣判斷",
不得用T-1收盤價代替實時報價去模擬"盤中成交"。

【標記價格(mark price)說明,修正點】total_account_value與浮動盈虧的估
值一律用 live_last(最新成交價),不用live_mid(bid/ask中間價)——ETF在
價差較寬時,中間價不一定貼近真實市值,最新成交價更能反映當下市場實際認
定的價格。live_mid只用在計算spread_cost_pct這一個地方。

【重要:total_account_value不在本層計算】本層只負責取得並保存
live_bid/live_ask/live_last/spread_cost_pct,供下面第四層(分紅)、第五
層(交易)使用。total_account_value的重新計算挪到第五層決策引擎執行完之
後——分紅入賬和交易都會改變
shares/cash_reserved/cash_uninvested/cash_principal,提前算會在最終驗證
時對不上。

【第四層:每日檢測分紅信息(雙源交叉驗證,已證實Robinhood單一源會滯後)】
每天執行本routine時都跑一次本層檢測,不再假設分紅只會在固定星期幾出現。
分紅這件事本身是基於每日/每週的規律,不受"今天幾點跑"影響:

1. 源A(Robinhood):調用 get_equity_fundamentals(symbols=["YMAG"]),取得
   dividend_per_share、ex_dividend_date、record_date、payable_date,記為
   rh_ex_date、rh_amount。
2. 源B(網頁,更新更快):web_fetch https://stockanalysis.com/etf/ymag/dividend/ ,
   從頁面裡的分紅歷史表格中取最新一行的 ex-dividend date 和 per-share
   金額,記為 sa_ex_date、sa_amount。若該頁面結構變化導致抓取失敗,嘗試
   改抓 https://www.dividendinvestor.com 或
   https://marketchameleon.com/Overview/YMAG/Dividends/ 之一作為替代,
   仍失敗則 sa_ex_date 記為空。
3. 取兩個源裡日期較新的一個作為本次候選:candidate_ex_date =
   max(rh_ex_date, sa_ex_date)(忽略為空的一側)。若兩個源都為空,記錄
   "本次分紅數據兩個來源均未獲取",跳過入賬,不影響其他字段。
4. 去重判斷:讀取 state/ymag_dividend_log.csv 最後一行記錄的
   ex_dividend_date。
   - 若 candidate_ex_date 與已記錄的最後一次相同或更早:說明沒有新分
     紅,跳過
   - 若 candidate_ex_date 更新(出現了新日期):視為一次新分紅,繼續下
     一步
5. 確定金額:若 candidate_ex_date 由源A提供,用 rh_amount;若由源B提供,
   用 sa_amount。若兩個源都返回了同一個candidate_ex_date但金額不一致,
   兩個數值都寫入日誌的備註欄,金額本身取源A(Robinhood,同一賬戶體系,
   口徑更貼近實際持倉計算)為準,並在報告裡註明"兩源金額不一致,已採用
   Robinhood數值,請人工核對"。
6. 入賬(僅在步驟4判定為"新分紅"時執行):
   - 除息資格的持股數,明確定義為candidate_ex_date前一個交易日收盤時的
     持倉股數(即除息日當天開盤前已經持有、不含除息日當天或之後新買入
     的部分),記為shares_before_ex_date。這個數字只能從
     state/ymag_trade_log.csv 按時間順序回放到candidate_ex_date(不含
     當天)倒推取得——不能用ymag_position.csv,因為該文件是每次覆蓋式
     更新的當前狀態,不保留歷史,在偵測滯後(源A/源B都可能滯後)導致
     ex_date是幾天前而期間又有交易發生的情況下,只有trade_log能正確
     回放出當時的持股數。
   - dividend_income = shares_before_ex_date × 確定的per-share金額
   - cumulative_dividends += dividend_income
   - cumulative_dividend_cash_in += dividend_income(不管下面流向哪個池
     子,都計入這個只增不減的來源追蹤計數器)
   - 若當前(執行當天,用第二/二點五層算出的T-1技術指標判斷)同時滿足
     "站上20日均線 且 range_pct_4w<5%":dividend_income 計入
     cash_reserved
   - 否則:計入 cash_uninvested
   - 寫入 state/ymag_dividend_log.csv 一行:date(執行日),ex_dividend_date,
     source_used("robinhood"或"web:域名"),rh_amount,sa_amount,
     shares_before_ex_date,dividend_income,routed_to
7. 釋放擱置資金(目標是"今天實際會用到的建倉金額",不是寫死的$25):若
   當前(用T-1技術指標判斷)同時滿足"站上20日均線 且
   range_pct_4w<5%",且 cash_uninvested > 0:先按第五層的月份/深跌例外
   規則算出"如果今天要買入,基礎金額會是多少"(標準月$25、非優選月
   $12.5、深跌例外$6.25),記為next_tranche_target;release_amount =
   min(cash_uninvested, max(0, next_tranche_target − cash_reserved))。
   cash_reserved += release_amount,cash_uninvested −= release_amount,
   寫入 state/ymag_dividend_log.csv 一行記錄本次轉移
   (action="RELEASE_UNINVESTED",amount=release_amount)。若
   release_amount為0(cash_reserved已經達到next_tranche_target),本次
   不釋放,cash_uninvested留待下次機會。
8. 本層只處理分紅入賬與資金池調度,不觸發任何買入/賣出判斷。

【第五層:決策引擎(不下真實訂單,只寫入模擬決策;判斷基準是T-1,成交
價是live_ask/live_bid)】
【預先計算:預估下次除息日】若state/ymag_dividend_log.csv裡至少有兩條
歷史分紅記錄,用最近兩次ex_dividend_date之間的實際天數差作為
interval_days;若不足兩條記錄,interval_days默認用7天。
estimated_next_ex_date = 最後一次記錄的ex_dividend_date + interval_days。
ex_date_within_window = (estimated_next_ex_date − 今天) <= 3天 且 >= 0。

賣出/減倉條件(優先級從高到低,同一天只執行第一條命中的,不疊加,全部
基於T-1數值判斷):
1. 【cross trigger】prev_mag7_breadth_healthy == true 且 (T-1)
   mag7_breadth <= 2 且 status != "flat":減倉40%,不受除息日保護限
   制。執行後prev_mag7_breadth_healthy更新為false、recovery_pending更
   新為true、recovery_pending_since更新為今天日期(不管recovery_pending
   之前是不是已經是true,每次這條或下面第2條觸發都重置成今天,見下方
   Recovery Buy的冷卻期說明)——寫入trade_log,action="TRIM_MAG7_BREADTH"
2. 【cross trigger】prev_market_trend == "up" 且 (T-1)market_trend ==
   "down" 且 status != "flat":減倉20%,不受除息日保護限制。執行後
   prev_market_trend更新為"down"、recovery_pending更新為true、
   recovery_pending_since更新為今天日期(同上,每次觸發都重置)——寫入
   trade_log,action="TRIM_MARKET_TREND"
3. consec_below_ma20(截至T-1)精確等於3(one-shot cross trigger,不是
   >=3,不會在第4、5、6...天因為條件仍然成立而重複觸發)且 status !=
   "flat":減倉50%,不受除息日保護限制——寫入trade_log,
   action="TRIM_STOPLOSS"
4. range_pct_4w(截至T-1)>8% 且 T-1收盤為過去20日新低 且 status !=
   "flat":清倉(shares歸零,status="flat"),不受除息日保護限制——寫入
   trade_log,action="EXIT_BREAKDOWN"
5. 【受除息日保護】month_return_so_far(截至T-1)>5% 且 status != "flat"
   且 本月尚未因此條件減倉過 且 ex_date_within_window == false:減倉
   30%-50%(擇中40%)——寫入trade_log,action="TRIM_PROFIT"
6. 【受除息日保護】month in [10,11] 或 (month==1 且 日期>=20號):且
   status != "flat" 且 本月尚未因此條件減倉過 且
   ex_date_within_window == false:減倉30%——寫入trade_log,
   action="TRIM_SEASONAL"

若上面任一條賣出條件命中並執行:
- 成交價 = live_bid
- 賣出股數 × live_bid = 賣出所得,計入cash_reserved;avg_cost不變;
  realized_gain_this_trade = 賣出股數 × (live_bid − avg_cost),累加進
  cumulative_realized_gain;賣出所得全額累加進cumulative_sale_cash_in
- slippage_pct = (live_bid − t1_close) / t1_close(供事後檢視,跟第三點
  五層的gap_pct不同:gap_pct用live_last衡量純粹的價格波動,slippage_pct
  用實際成交價live_bid衡量連價差都算進去、實際上被"讓利"了多少)
- 寫入 state/ymag_trade_log.csv 一行:date,execution_time_et,
  action(TRIM_MAG7_BREADTH/TRIM_MARKET_TREND/TRIM_STOPLOSS/
  EXIT_BREAKDOWN/TRIM_PROFIT/TRIM_SEASONAL),signal_basis_date,
  t1_close,execution_price(=live_bid),live_bid,live_ask,spread_cost_pct,
  shares_traded,cash_amount(=賣出所得),realized_gain,gap_pct(留空,
  跳空閘門只套用在買入方向,賣出不受影響,這裡固定留空或記0以維持欄位
  對齊),slippage_pct,reason
- 【Trade Lock,修正點】今天已經執行了賣出動作,今天**不再檢查任何買入
  條件**(包括Recovery Buy)——直接跳到本層最後的total_account_value重
  新計算與第六層報告。一天最多只執行一個方向的交易動作,避免同一天先賣
  後買或先買後賣。

【若今天沒有任何賣出動作,才檢查買入條件】(1-3必須同時滿足,4決定倉位
大小,5是硬性宏觀門檻,全部基於第二/二點五層算出的T-1數值):
1. price_vs_ma20_pct > 0(昨天收盤站上20日均線)
2. 箱體壓縮確認:若 shares == 0(空倉狀態下的首次建倉,即"Initial
   Position Exception"),放寬為 range_pct_4w < 8%;一旦建過第一檔,恢
   復標準的 range_pct_4w < 5%
3. invested_tranches < 4
4. 倉位大小由月份決定:
   - month in [5,7,9]:標準檔位,基礎金額=$25
   - 其餘月份(1,6,8,10,11,12):基礎金額減半,=$12.5
   - month in [2,3,4]:默認也只減半買入(=$12.5),除非命中下面的"深跌
     反轉例外"
5. market_trend == "up" 且 mag7_breadth >= 5(硬性門檻,不因為月份或深
   跌例外而放寬)

深跌反轉例外(僅限month in [2,3,4]時使用,在第4條基礎上再減半,即
$6.25):
- month_return_so_far < -8%
- rolling_low_5d = min(最近5個交易日收盤價,截至昨天);
  rolling_low_prior5d = min(再往前5個交易日收盤價,即第6-10個交易日);
  要求 rolling_low_5d >= rolling_low_prior5d
- 成交量較前兩週均值下降
- 即使命中這條例外,仍然必須同時滿足上面第5條的
  market_trend/mag7_breadth條件

【Recovery Buy】僅在recovery_pending=true時生效(同樣受上面的Trade
Lock保護——今天已賣出就不會走到這裡):
mag7_breadth >= 6 且 market_trend == "up" 且 mag7_mom_5d > 0(均為T-1數
值)且 invested_tranches < 4 且【冷卻期,修正點】以下條件也成立時,豁免
"range_pct_4w < 5%"這一條(其餘條件仍適用,包括price_vs_ma20_pct>0):
cooldown_trading_days = data/prices/YMAG.csv裡日期晚於
recovery_pending_since、且不晚於昨天(T-1)的交易日筆數(用實際交易日曆
算,不是自然日/星期幾,這樣遇到假日不會算錯);要求
cooldown_trading_days >= 2(即距離觸發那次TRIM_MAG7_BREADTH或
TRIM_MARKET_TREND至少已經過了2個完整交易日,避免震盪行情下才剛砍倉又
馬上回補)。
全部條件(含冷卻期)都成立才按標準月份規則基礎金額買入一檔,
action="RECOVERY_BUY",並把recovery_pending重置為false、
recovery_pending_since清空。若recovery_pending=true但冷卻期還沒到,本
次不觸發Recovery Buy,不算錯誤,等下次執行再檢查。

【買入前的跳空閘門,修正點(已改為單向),買入方向專用(含Recovery
Buy),不適用於賣出】不管是常規買入條件還是Recovery Buy,只要判定"今天
應該買入",在真正下模擬單之前,先做這一道檢查:
gap_pct = (live_last − t1_close) / t1_close
若 gap_pct > 5%(只擋往上跳空追高的情況——今天價格已經比T-1收盤高出超
過5%):放棄本次買入,不執行、不消耗今天的Trade Lock額度,在報告裡註明
"信號來自T-1收盤,但今日價格已跳空上漲(gap_pct=X%),暫緩本次建倉,等明
天用新的T-1數據重新評估"。
若 gap_pct <= 5%(包含任何幅度的跳空下跌):通過閘門,照常執行買入,不
額外攔阻。
(理由:訊號是用昨天收盤算出來的,今天已經大幅追高再買,等於付出訊號當
初完全沒評估過的溢價;但跳空下跌不同——YMAG是分紅型ETF,價格更低通常代
表這一檔的有效殖利率更高,跟"建立分紅底倉、不追求完美擇時"的策略定位一
致,不需要因為跌了就迴避。)

若通過跳空閘門,執行買入:
- 本次建倉金額按上述規則確定,優先從cash_reserved扣減,不足部分從
  cash_principal裡扣(兩個字段都要實際做減法)
- 成交價 = live_ask(不是T-1收盤價,也不是live_last或live_mid)
- 按live_ask計算模擬買入股數(允許小數股),更新shares,並按加權平均重
  新計算avg_cost = (原shares×原avg_cost + 本次買入金額) / 新shares;若
  買入前status為"flat",買入後把status更新為"holding"
- slippage_pct = (live_ask − t1_close) / t1_close(供事後檢視,跟
  gap_pct不同,見上方賣出方向的說明)
- 寫入 state/ymag_trade_log.csv 一行:date,execution_time_et(執行時的
  美東時間,精確到分鐘),action="BUY"或"RECOVERY_BUY",
  signal_basis_date(T-1日期),t1_close,execution_price(=live_ask),
  live_bid,live_ask,spread_cost_pct,shares_traded,
  cash_amount(=本次花費金額),realized_gain(留空/0),
  gap_pct(本次跳空幅度,供事後檢視),slippage_pct,
  reason(寫明命中的具體條件、當時的月份倉位倍數、market_trend和
  mag7_breadth數值;RECOVERY_BUY要註明是在哪次
  TRIM_MAG7_BREADTH/TRIM_MARKET_TREND之後觸發的回補、冷卻期是否已滿足)

【重新計算total_account_value,必須在本層(第五層)全部買賣判斷執行完
之後做】,不要挪到更早的層,且用live_last(不是live_mid):
total_account_value = shares × live_last + cash_principal + cash_reserved
                       + cash_uninvested
這裡的live_last複用第三點五層拉到的同一組報價,不需要重新調用
get_equity_quotes。

【第六層:輸出報告】
生成 reports/ymag-intraday/{今天日期}.md,包含:
- 決策依據的T-1日期和當時的ma20/range_pct_4w/consec_below_ma20/
  month_return_so_far/market_trend/mag7_breadth/mag7_mom_5d/t1_close
- 執行時的live_bid/live_ask/live_last/spread_cost_pct,以及本次
  gap_pct(即使沒有觸發買入判斷,只要今天有算過月份對應的可能買入,也
  列出gap_pct供參考;若因跳空被擋下,清楚標註)
- 今日命中的買入/賣出條件及執行結果(執行價格、成交時間、Trade
  Lock是否因此鎖住了另一個方向);若未命中任何條件,註明"今日無操作"
- 若本次因跳空閘門擋下買入,註明gap_pct數值和方向
- 若本次因重試多次仍未取得實時報價而跳過買賣判斷,註明原因
- 分紅檢測結果
- 若本次發生了cash_uninvested釋放(RELEASE_UNINVESTED):註明釋放金額
  和轉入後的cash_reserved餘額
- 當前倉位狀態(shares、avg_cost、用live_last計算的浮動盈虧%、
  invested_tranches、cash_principal、cash_reserved、cash_uninvested、
  cumulative_dividends、cumulative_realized_gain、total_account_value)
- 現金來源構成:cumulative_dividend_cash_in vs cumulative_sale_cash_in
- 總回報拆分:相對初始本金$100的總收益率、價格端浮盈浮虧、已實現價差
  (cumulative_realized_gain)、分紅貢獻(cumulative_dividends),四項分
  開列出
- Dividend Dashboard:Forward Annual Income(當前shares × 最近一次
  per-share分紅金額 × 52)、Trailing 12M Dividend Yield(過去12個月
  state/ymag_dividend_log.csv裡所有dividend_income加總 / 當前
  shares×avg_cost)、當前年化股息率估算(最近一次per-share分紅金額 ×
  52 / 當前live_last)、累計分紅佔初始本金比例
  (cumulative_dividends/100)、已持有週數(從第一筆BUY記錄日期算到今
  天)
- 累計價差成本:把trade_log裡所有BUY/SELL的spread_cost_pct按成交金額
  加權平均,展示這個策略因為在盤中用真實報價成交而額外付出了多少成本
- 累計滑點(slippage):把trade_log裡所有交易的slippage_pct按成交金額加
  權平均,分開列出買入方向和賣出方向各自的平均值——這是"訊號來自T-1收
  盤、但實際用今天的live價格成交"這整套設計最終要驗證的核心指標:半年
  下來看這個數字能回答"價差加跳空,到底吃掉了多少報酬"

更新 state/ymag_position.csv 為最新一行(覆蓋式更新當前狀態,不是追加歷
史,歷史交易只在ymag_trade_log.csv裡追加)。

【驗證,commit前必做】
- reports/ymag-intraday/{今天日期}.md 文件存在且非空
- state/ymag_position.csv 中 shares、avg_cost、cash_principal、
  cash_reserved、cash_uninvested、cumulative_dividends、
  cumulative_realized_gain、cumulative_dividend_cash_in、
  cumulative_sale_cash_in、total_account_value 均不可為負數,也不可為
  NaN/空值
- 若 shares > 0,avg_cost 必須 > 0
- total_account_value 必須等於 shares×live_last + cash_principal +
  cash_reserved + cash_uninvested(允許極小的浮點誤差,比如0.01以內),
  不相等視為計算錯誤,不commit
- market_trend 字段只能是"up"或"down"二選一,status字段只能是"flat"或
  "holding"二選一,出現其他值視為計算錯誤,不commit
- 若本次執行了買入或賣出,state/ymag_trade_log.csv 必須新增對應行,且
  execution_price、live_bid、live_ask均不可為空或負數,且
  execution_price必須落在live_bid和live_ask之間
- 若本次同時新增了BUY/RECOVERY_BUY和任何SELL類(TRIM_*/EXIT_BREAKDOWN)
  行——即Trade Lock被違反——視為邏輯錯誤,不commit
- recovery_pending=true時,recovery_pending_since必須是有效日期(不可為
  空);recovery_pending=false時,recovery_pending_since必須為空——兩者
  不一致視為邏輯錯誤,不commit
- 若本次判定為新一筆分紅並已入賬,state/ymag_dividend_log.csv 必須新增
  對應行,且dividend_income不可為負數,source_used字段不可為空
- mag7_breadth 必須是0到7之間的整數,超出範圍視為計算錯誤,本次不commit
- 若任何一項驗證失敗:不commit,保留現有文件不變,在最後回復裡說明失敗
  原因

驗證通過:
git add data/prices/ state/ymag_position.csv state/ymag_trade_log.csv state/ymag_dividend_log.csv reports/ymag-intraday/
git commit -m "ymag intraday paper trading YYYY-MM-DD"
git push origin claude/ymag-paper-state-intraday

若push失敗,先git pull重新同步,再重試一次;若仍失敗,結束並在回復裡說
明push失敗、本次結果未能寫入repo。

【禁止事項】
只做模擬倉位記錄和信號決策,絕不調用任何真實下單、真實賬戶操作、真實資
金劃轉類工具。不與claude/ymag-paper-state、claude/scanner-state或repo中
其他分支有任何讀寫互動。所有買賣僅為文件內模擬記賬,即使用了真實的盤中
報價計算成交價,也絕對不代表任何真實交易指令。

首次運行前置條件
本routine第一層會自行拉取YMAG完整歷史價格,可以獨立作為第一個"Run now"
手動觸發(建議手動觸發時選一個真實的開市時段內運行,才能測出
get_equity_quotes是否正常返回)。
```

## Initial state (seeded 2026-07-23, updated Round 3/4)

`state/ymag_position.csv` (now includes `recovery_pending_since`),
`state/ymag_trade_log.csv` (header only, with the intraday-specific
columns `execution_time_et`/`signal_basis_date`/`t1_close`/
`execution_price`/`live_bid`/`live_ask`/`spread_cost_pct`/`gap_pct`/
`slippage_pct` in addition to the v1.0 columns), and
`state/ymag_dividend_log.csv` (header only) were pre-seeded so the first
run's starting state is explicit and auditable. `data/prices/` is left
empty (`.gitkeep` only) — Layer 1 populates all 9 symbols' full ~13-month
history on first run.
