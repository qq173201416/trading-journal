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

## Fixes applied in this copy (before first run)

Three issues were found reviewing the draft and fixed here:

1. **Idempotency check was sequenced before branch checkout.** The draft
   read `state/ymag_position.csv`'s `date` field to detect "already ran
   today" *before* `git checkout`/`git pull` of this branch. Since each
   run starts from a fresh clone, that file either doesn't exist yet at
   that point or reflects a stale/unrelated checkout — the guard would
   never actually see this branch's latest committed state. **Fix:**
   moved the idempotency check to immediately after `git pull`.

2. **`total_account_value` was recomputed too early.** The draft placed
   the recompute right after the live-quote layer (3.5), before dividend
   routing (layer 4) and the buy/sell decision engine (layer 5) run —
   both of which change `shares`/`cash_reserved`/`cash_uninvested`/
   `cash_principal`. The value computed at that point would be stale by
   the time the position file is written, and would fail the routine's
   own commit-time validation (`total_account_value` must equal the
   current field sum). **Fix:** moved the recompute to after layer 5,
   reusing the same `live_mid` captured once in layer 3.5 (no second
   quote pull needed).

3. **Fixed 14:15 UTC schedule silently stops running for ~5 months a
   year.** 14:15 UTC is 10:15 ET during EDT (Mar–Nov) — correct, per the
   "45 minutes after open" design intent. But during EST (Nov–Mar) the
   same fixed UTC time is only **09:15 ET** — 15 minutes after the 09:30
   open, and *earlier* than this routine's own 09:35–15:55 ET time-window
   guard. Every weekday for roughly five winter months, the routine would
   fail its own time check at step 1 and exit doing nothing — with no
   error, indistinguishable from "no signal today." (`claude/scanner-state`
   hit the same DST class of bug previously.) **Fix:** schedule moved to
   **15:15 UTC**, which lands at 11:15 ET (EDT) / 10:15 ET (EST) — safely
   inside the intended window under both offsets, no twice-a-year manual
   retiming needed.

The dividend-detection layer (§4 below) is also written out in full here
rather than "see v1.0" as in the original draft — a routine's executing
agent has no access to another branch's routine text and is explicitly
forbidden from reading `claude/ymag-paper-state` to look it up, so this
prompt has to be self-contained. The text below already includes the two
fixes applied to v1.0 (`TRIM_STOPLOSS` as a one-shot `== 3` cross-trigger,
and `shares_before_ex_date` derived only from `trade_log` replay, never
from `ymag_position.csv`).

---

## Routine — YMAG Intraday Signal & Paper Trade

Trigger: Schedule, weekdays, 15:15 UTC (= 11:15 EDT / 10:15 EST —
DST-safe, always lands mid-morning within the market-hours guard below;
no manual retiming needed across DST transitions)
Repository: trading-journal

```
【執行時機檢查,必須在分支持久化之前先做】
用 Bash 執行 `TZ=America/New_York date +"%u %H:%M"`,確認 (a) 星期一到五
(b) 時分在09:35到15:55之間(即確保當下真的是開市時段,不是假日提前收盤或
其他異常情況)。任一不成立就直接結束,不做任何git操作。

【分支持久化,第一步必做】
git fetch origin claude/ymag-paper-state-intraday
git checkout claude/ymag-paper-state-intraday 2>/dev/null || git checkout -b claude/ymag-paper-state-intraday

後續所有讀寫、push,一律針對這個分支。不要與 claude/ymag-paper-state、
claude/scanner-state 或其他任何分支有讀寫互動。

git pull 拿最新版本。

【冪等性檢查:今天是否已經執行過,必須在git pull之後做】
讀取 state/ymag_position.csv 的date字段(這時已經是本分支最新已提交的版
本),若已經等於今天,說明今天這個routine已經跑過一次(比如schedule被意
外觸發兩次),直接結束,不重複執行、不重複買賣,避免同一天被記賬兩次。
(注意:這一步必須排在git pull之後——如果排在分支checkout之前,讀到的
要嘛是不存在的文件、要嘛是跟本分支無關的舊狀態,這個防重複機制就形同虛
設。)

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
prev_market_trend,prev_mag7_breadth_healthy,recovery_pending,status)。
若不存在,視為空倉,初始化 shares=0, cash_principal=100, cash_reserved=0,
cash_uninvested=0, cumulative_dividends=0, cumulative_realized_gain=0,
cumulative_dividend_cash_in=0, cumulative_sale_cash_in=0,
prev_market_trend="up", prev_mag7_breadth_healthy=true,
recovery_pending=false, status="flat"。
初始模擬本金:$100,全部放在cash_principal裡,初始 total_account_value=100。

資金流規則(本金/分紅池/賣股池的定義和v1.0完全一致):
- invested_tranches = (shares × avg_cost) / 25,用於判斷是否還能加倉,不
  用單獨維護計數器
- 買入時優先扣cash_reserved,不足從cash_principal扣;賣出所得全部計入
  cash_reserved,avg_cost賣出時不變
- shares允許小數(碎股處理),原因同v1.0(本金規模小,取整會造成明顯的資
  金利用率損失)

【第三點五層:實時報價(本版本與v1.0最大的差異所在)】
調用 get_equity_quotes(symbols=["YMAG"]) 取得當下(routine執行這一刻)的
bid_price、ask_price、last_trade_price。記為 live_bid、live_ask、
live_last。
- live_mid = (live_bid + live_ask) / 2,作為之後給total_account_value估
  值用的參考價(不是成交價,只是用來估算賬戶當下市值),本次執行全程只
  拉一次報價、複用同一組數值,不需要在後面重新拉取
- 若買入條件成立,模擬買入的實際成交價 = live_ask(買方要付出的價格,包
  含了要吃掉賣方報價的價差成本)
- 若賣出條件成立,模擬賣出的實際成交價 = live_bid(賣方能拿到的價格,同
  樣包含價差成本)
- spread_cost_pct = (live_ask − live_bid) / live_mid,記錄下來,方便回頭
  看這個策略實際執行時付出的價差成本有多大

若get_equity_quotes當下沒有返回有效報價(比如臨時數據異常),本次不執行
任何買賣判斷,只更新價格歷史和分紅檢測,在報告裡註明"本次未能取得實時報
價,跳過買賣判斷",不得用T-1收盤價代替實時報價去模擬"盤中成交"——那樣就
失去了這個版本存在的意義。

【重要,修正點:total_account_value不在本層計算】本層只負責取得並保存
live_bid/live_ask/live_mid/spread_cost_pct,供下面第四層(分紅)、第五層
(交易)使用。total_account_value的重新計算挪到第五層決策引擎執行完之
後,理由見文件頂部"本副本已修正的問題"第2點——分紅入賬和交易都會改變
shares/cash_reserved/cash_uninvested/cash_principal,提前算會在最終驗證
時對不上。

【第四層:每日檢測分紅信息(雙源交叉驗證,已證實Robinhood單一源會滯後)】
每天執行本routine時都跑一次本層檢測,不再假設分紅只會在固定星期幾出現。
邏輯與v1.0完全一致,不因為改成盤中執行而變化——分紅這件事本身是基於每
日/每週的規律,不受"今天幾點跑"影響:

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

買入條件(1-3必須同時滿足,4決定倉位大小,5是硬性宏觀門檻,全部基於第
二/二點五層算出的T-1數值):
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

若滿足買入條件:
- 本次建倉金額按上述規則確定,優先從cash_reserved扣減,不足部分從
  cash_principal裡扣(兩個字段都要實際做減法)
- 成交價 = live_ask(不是T-1收盤價,也不是live_mid)
- 按live_ask計算模擬買入股數(允許小數股),更新shares,並按加權平均重
  新計算avg_cost = (原shares×原avg_cost + 本次買入金額) / 新shares;若
  買入前status為"flat",買入後把status更新為"holding"
- 寫入 state/ymag_trade_log.csv 一行:date,execution_time_et(執行時的
  美東時間,精確到分鐘),action="BUY",signal_basis_date(T-1日期),
  execution_price(=live_ask),live_bid,live_ask,spread_cost_pct,
  shares_traded,cash_amount(=本次花費金額),realized_gain(留空/0),
  reason(寫明命中的具體條件、當時的月份倉位倍數、market_trend和
  mag7_breadth數值)

【Recovery Buy】規則與v1.0相同,僅在recovery_pending=true時生效:
mag7_breadth >= 6 且 market_trend == "up" 且 mag7_mom_5d > 0(均為T-1數
值)且 invested_tranches < 4 時,豁免"range_pct_4w < 5%"這一條(其餘條件
仍適用,包括price_vs_ma20_pct>0),成交價同樣是live_ask,按標準月份規則
基礎金額買入一檔,寫入trade_log,action="RECOVERY_BUY",並把
recovery_pending重置為false。

賣出/減倉條件(優先級從高到低,先檢查賣出,再檢查買入,同一天只執行第
一條命中的,不疊加,全部基於T-1數值判斷):
1. 【cross trigger】prev_mag7_breadth_healthy == true 且 (T-1)
   mag7_breadth <= 2 且 status != "flat":減倉40%,不受除息日保護限
   制。執行後prev_mag7_breadth_healthy更新為false、recovery_pending更
   新為true——寫入trade_log,action="TRIM_MAG7_BREADTH"
2. 【cross trigger】prev_market_trend == "up" 且 (T-1)market_trend ==
   "down" 且 status != "flat":減倉20%,不受除息日保護限制。執行後
   prev_market_trend更新為"down"、recovery_pending更新為true——寫入
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

若滿足賣出條件:
- 成交價 = live_bid
- 賣出股數 × live_bid = 賣出所得,計入cash_reserved;avg_cost不變;
  realized_gain_this_trade = 賣出股數 × (live_bid − avg_cost),累加進
  cumulative_realized_gain;賣出所得全額累加進cumulative_sale_cash_in
- 寫入 state/ymag_trade_log.csv 一行:date,execution_time_et,
  action(TRIM_MAG7_BREADTH/TRIM_MARKET_TREND/TRIM_STOPLOSS/
  EXIT_BREAKDOWN/TRIM_PROFIT/TRIM_SEASONAL),signal_basis_date,
  execution_price(=live_bid),live_bid,live_ask,spread_cost_pct,
  shares_traded,cash_amount(=賣出所得),realized_gain,reason

【重新計算total_account_value,必須在本層(第五層)全部買賣判斷執行完
之後做】(見文件頂部"本副本已修正的問題"第2點,不要挪到更早的層):
total_account_value = shares × live_mid + cash_principal + cash_reserved
                       + cash_uninvested
這裡的live_mid複用第三點五層拉到的同一組報價,不需要重新調用
get_equity_quotes。

【第六層:輸出報告】
生成 reports/ymag-intraday/{今天日期}.md,包含:
- 決策依據的T-1日期和當時的ma20/range_pct_4w/consec_below_ma20/
  month_return_so_far/market_trend/mag7_breadth/mag7_mom_5d
- 執行時的live_bid/live_ask/live_mid/spread_cost_pct
- 今日命中的買入/賣出條件及執行結果(執行價格、成交時間);若未命中任
  何條件,註明"今日無操作"
- 若本次未能取得實時報價而跳過買賣判斷,註明原因
- 分紅檢測結果(格式同v1.0)
- 若本次發生了cash_uninvested釋放(RELEASE_UNINVESTED):註明釋放金額
  和轉入後的cash_reserved餘額
- 當前倉位狀態(shares、avg_cost、用live_mid計算的浮動盈虧%、
  invested_tranches、cash_principal、cash_reserved、cash_uninvested、
  cumulative_dividends、cumulative_realized_gain、total_account_value)
- 現金來源構成:cumulative_dividend_cash_in vs cumulative_sale_cash_in
- 總回報拆分:相對初始本金$100的總收益率、價格端浮盈浮虧、已實現價差
  (cumulative_realized_gain)、分紅貢獻(cumulative_dividends),四項分
  開列出
- Dividend Dashboard(Forward Annual Income、Trailing 12M Dividend
  Yield、當前年化股息率估算、累計分紅佔初始本金比例、已持有週數,計算
  方式同v1.0)
- 累計價差成本:把trade_log裡所有BUY/SELL的spread_cost_pct按成交金額
  加權平均,展示"這個策略因為在盤中用真實報價成交、而不是理想化的收盤
  價成交,額外付出了多少成本"——這是這個版本相對v1.0最重要的新增對比信
  息
- 若今日執行了模擬交易,列出具體動作和原因(若是RECOVERY_BUY,額外註明
  是在哪次TRIM_MAG7_BREADTH/TRIM_MARKET_TREND之後觸發的回補)

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
- total_account_value 必須等於 shares×live_mid + cash_principal +
  cash_reserved + cash_uninvested(允許極小的浮點誤差,比如0.01以內),
  不相等視為計算錯誤,不commit
- market_trend 字段只能是"up"或"down"二選一,status字段只能是"flat"或
  "holding"二選一,出現其他值視為計算錯誤,不commit
- 若本次執行了買入或賣出,state/ymag_trade_log.csv 必須新增對應行,且
  execution_price、live_bid、live_ask均不可為空或負數,且
  execution_price必須落在live_bid和live_ask之間(不能出現成交價比bid
  還低或比ask還高這種不合理的情況)
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

【目前只跑這一份,不跑v1.0】
claude/ymag-paper-state(v1.0,收盤記賬版)分支和文件仍保留在repo裡,但
沒有設定排程觸發——依決定,只讓這個盤中真實報價成交版本作為唯一實際運
行的routine,因為它更貼近真實下單會經歷的成交價格與價差成本。

首次運行前置條件
無需依賴v1.0或其他routine——本routine第一層會自行拉取YMAG完整歷史價
格,可以獨立作為第一個"Run now"手動觸發(建議手動觸發時選一個真實的開
市時段內運行,才能測出get_equity_quotes是否正常返回)。
```

## Initial state (seeded 2026-07-23)

`state/ymag_position.csv`, `state/ymag_trade_log.csv` (header only, with
the intraday-specific columns `execution_time_et`/`signal_basis_date`/
`execution_price`/`live_bid`/`live_ask`/`spread_cost_pct` in addition to
the v1.0 columns), and `state/ymag_dividend_log.csv` (header only) were
pre-seeded so the first run's starting state is explicit and auditable.
`data/prices/` is left empty (`.gitkeep` only) — Layer 1 populates all 9
symbols' full ~13-month history on first run.
