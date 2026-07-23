# YMAG Paper Trading Routine — claude/ymag-paper-state

Reference copy of the Claude Code Routine prompt running against this branch.
This is documentation only — the routine itself is configured at
claude.ai/code/routines and reads/writes this branch directly, not this file.

Repository: `trading-journal`
Branch: `claude/ymag-paper-state` (fixed, orphan — independent from `main` and
from any other branch in this repo, e.g. `claude/scanner-state`,
`claude/base-lifecycle-v2-state`, `claude/trading-journal-state`. No
read/write interaction with any of those.)
Branch permission: default (`claude/`-prefixed branches are pushable by
default)

This is **paper trading only**. The routine never calls any real
order-placement or account-action tool — it only reads market data
(`get_equity_historicals`, `get_equity_fundamentals`) and simulates
positions/decisions in files on this branch.

## Status: v1.0, frozen, in paper-trading observation period

Three rounds of external review confirmed no known architectural gaps in the
capital model, dividend tracking, reinvestment logic, risk controls, or
macro filter. A fourth review (the one that produced this file) found and
fixed two issues before the first live run — see "Fixes applied in this
copy" below. From here the strategy is frozen: no new technical indicators
(RSI, VIX, etc.) and no removal of the existing seasonal position sizing
unless paper trading surfaces an actual bug or data gap.

Suggested cadence:
- **Phase 1 (~90 days):** verify dividends are being captured correctly,
  cash flow (`cash_principal`/`cash_reserved`/`cash_uninvested`) always
  reconciles, and every trade is booked accurately.
- **Phase 2 (6–12 months):** check realized max drawdown, cumulative
  dividend income, and capital utilization against expectations.

## Fixes applied in this copy (before first run)

1. **TRIM_STOPLOSS repeat-fire bug.** The original wording used
   `consec_below_ma20 >= 3` as the trigger, with no guard against firing
   again on every subsequent day the streak continues. Conditions 1
   (`mag7_breadth` cross) and 2 (`market_trend` cross) are explicitly
   one-shot cross-triggers, and conditions 5/6 have an explicit "haven't
   already trimmed for this reason this month" guard — but condition 3 had
   neither. Since `consec_below_ma20` doesn't reset when a trim fires, a
   sustained multi-day close-below-MA20 streak would trigger a fresh 50%
   cut of the *remaining* position on every qualifying day (50% → 25% →
   12.5% → 6.25% → ...), silently decaying the position toward zero over
   about a week instead of taking one controlled risk-management cut.
   **Fix:** the condition below now fires on `consec_below_ma20 == 3`
   (the exact day the streak first reaches 3), not `>= 3`. Because the
   counter increments by exactly 1 per qualifying day and resets to 0 the
   moment price closes back above MA20, checking for exact equality is a
   correct one-shot cross-trigger and needs no extra state field.

2. **`shares_before_ex_date` source.** The original wording said to derive
   it "from `ymag_position.csv` history or `trade_log`" — but
   `ymag_position.csv` is explicitly overwrite-only (current state, not a
   history), so it cannot serve as a source when dividend detection lags
   (which is exactly the scenario the dual-source Robinhood/web check
   exists to catch — the ex-date can be discovered days after it occurred,
   with trades having happened in between). **Fix:** `shares_before_ex_date`
   is now derived only by replaying `state/ymag_trade_log.csv`
   chronologically up to (and excluding) `candidate_ex_date`.

Both fixes are reflected inline in the routine text below.

---

## Routine — YMAG Daily Signal & Paper Trade

Trigger: Schedule, weekdays, 21:30 UTC (16:30 ET / 30 min after market
close, same post-close window convention as the existing daily pipeline)
Repository: trading-journal

```
【執行時機檢查,必須在分支持久化之前先做】
用 Bash 執行 `TZ=America/New_York date +"%u %H:%M"`,確認 (a) 星期一到五
(b) 時分已經是16:30或之後。任一不成立就直接結束,不做任何git操作。

【分支持久化,第一步必做】
git fetch origin claude/ymag-paper-state
git checkout claude/ymag-paper-state 2>/dev/null || git checkout -b claude/ymag-paper-state

後續所有讀寫、push,一律針對這個分支。不要與 claude/scanner-state 或其他
任何分支有讀寫互動。

git pull 拿最新版本。

【第一層:增量更新價格數據(YMAG本體 + SPY + 七巨頭)】
對 YMAG、SPY、以及七巨頭(AAPL、MSFT、GOOGL、AMZN、NVDA、META、TSLA)共9個
symbol,分別檢查 data/prices/{TICKER}.csv 是否存在:
- 不存在或行數<260行:視為首次執行,用 get_equity_historicals(單一symbol、
  interval="day"、start_time設為約13個月前)取得完整歷史,寫入
  data/prices/{TICKER}.csv(字段:begins_at,open_price,close_price,
  high_price,low_price,volume,session),過濾掉interpolated=true的補值bar。
- 已存在且數據充足:讀取最後一行日期,只查詢"最後日期隔天"到"今天"的新K線
  並追加。

【重要】get_equity_historicals一次只查一個symbol,不要把這9個symbol放進
同一次調用的symbols數組裡一起查這麼長的時間範圍(與現有scanner-state分支
上的既有約定一致)。

【第二層:計算技術特徵】
基於 data/prices/YMAG.csv 全部數據,計算當天的:
- ma20:20日收盤價均線
- price_vs_ma20_pct:今日收盤相對ma20的百分比偏離
- range_pct_4w:過去20個交易日(收盤價)的(最高-最低)/20個交易日前收盤價,
  作為箱體寬度
- consec_below_ma20:今日收盤價連續低於ma20的天數(向前數,遇到高於ma20即
  中斷計數)
- month_return_so_far:自然月至今的開盤到今日收盤漲跌幅
- month:當前自然日期所屬月份(1-12),僅作為下方決策的次要參考因子

【第二點五層:大盤與七巨頭趨勢(宏觀確認層)】
基於第一層拉到的SPY和七巨頭數據,計算:
- ma50_spy:SPY的50日收盤均線;market_trend = "up" 若今日SPY收盤 >
  ma50_spy,否則 "down"
- mag7_breadth:AAPL、MSFT、GOOGL、AMZN、NVDA、META、TSLA各自算自己的20日
  收盤均線,統計其中收盤價站上自己20日均線的家數,得到0-7之間的整數,
  數值越高代表七巨頭整體走勢越強
- mag7_mom_5d:七巨頭過去5個交易日漲跌幅的算術平均值(百分比),作為短期
  動能參考

這三個指標只作為下面第四層買賣判斷的輸入,本層不直接產生任何交易動作。
判斷market_trend、mag7_breadth是否"剛剛轉弱"(cross trigger)需要用到
上一次運行時存下的 prev_market_trend、prev_mag7_breadth_healthy(見第三層
的倉位字段),本層只負責算出今天的原始數值,不做比較。

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
初始模擬本金:$100,全部放在cash_principal裡(僅用於計算,不涉及任何真實
資金),初始 total_account_value=100。

【資金流封閉:cash_principal是真正的"本金餘額"】買入時先扣cash_reserved,
不夠的部分從cash_principal裡扣(不是從一個籠統的"本金"概念裡扣,而是這個
具體字段實際做減法)。這樣任何時候都能準確知道本金還剩多少,不會出現
"不知道扣到哪兒了"的問題。

【cash_reserved的資金來源可追溯,但不物理拆分成多個池子】cash_reserved本
身還是一個統一的池子(分紅和賣股所得都會進這裡,買入時也是統一從這裡
扣),但用兩個只增不減的計數器分開記錄歷史來源構成,方便報告裡顯示:
- cumulative_dividend_cash_in:歷史上一共有多少分紅流進過cash_reserved或
  cash_uninvested(每次分紅入賬時累加,不管當時流向哪個池子)
- cumulative_sale_cash_in:歷史上一共有多少賣股所得流進過cash_reserved
  (每次TRIM/EXIT時累加賣出股數×當日收盤價)
這兩個計數器純粹用於報告的"這筆錢主要是分紅還是賣股票賺的"這種可讀性展
示,不影響實際的買賣資金計算邏輯。

【關於tranche_count:改為動態計算,不再單獨維護計數器】
不再用一個單獨遞增/遞減的tranche_count字段(這會在部分減倉後跟丟真實倉
位,導致減倉後卻因為"計數已滿"而永久無法再加倉的bug)。改為每次需要判斷
"是否還能加倉"時,現算:
invested_tranches = (shares × avg_cost) / 25
(25即標準檔基準金額,深跌減半或非優選月份減半買入後,shares×avg_cost會
自然反映成小於1個整檔的比例,不需要額外處理;這個算法有意用"投入成本"而
不是"當前市值"計算,符合資金管理的原意——跌了不代表少買了幾檔,只有實際
減倉才會讓這個數字下降)
買入條件裡原本"tranche_count < 4"改為"invested_tranches < 4"。這樣任何一
次減倉,shares同步減少而avg_cost不變(見下方說明),invested_tranches會
自動同步下降,不會再出現減倉後無法重新加倉的問題。

【重要:小額本金下的份額處理】本金降到$100後,每檔建倉金額約$25,而YMAG
股價在$11-12區間,一檔只能買2股左右,取整會帶來明顯的資金利用率損失
(比如買2股實際只用掉約$23,剩$2零頭長期閒置,佔本金2%不是小數目)。因此
在$100這個量級下,shares字段允許保留小數(模擬層面按小數股處理,不做整
數取整),這樣25%檔位的資金能被精確用滿,分紅計算(shares_before_ex_date
× per-share金額)也能對應到準確的持股比例,不會因為取整損失精度。

每次執行到本層末尾時(在第四層買賣判斷執行完之後)都要重新計算:
total_account_value = shares × 當日收盤價 + cash_principal + cash_reserved
                       + cash_uninvested
這是賬戶的真實總值,本金、分紅、賣股所得三塊現金都獨立記錄、互不覆蓋,
任何時候都能拆開看清楚賬戶裡的錢具體來自哪裡。

【第三點五層:每日檢測分紅信息(雙源交叉驗證,已證實Robinhood單一源會滯
後)】
每天執行本routine時都跑一次本層檢測,不再假設分紅只會在固定星期幾出現。
已實測發現Robinhood的get_equity_fundamentals字段有滯後(某次實測中
stockanalysis.com已顯示新的除息日,Robinhood仍停留在上一筆),因此改為
雙源交叉檢查:

1. 源A(Robinhood):調用 get_equity_fundamentals(symbols=["YMAG"]),取得
   dividend_per_share、ex_dividend_date、record_date、payable_date,記為
   rh_ex_date、rh_amount。
2. 源B(網頁,更新更快):web_fetch https://stockanalysis.com/etf/ymag/dividend/ ,
   從頁面裡的分紅歷史表格中取最新一行的 ex-dividend date 和 per-share金
   額,記為 sa_ex_date、sa_amount。若該頁面結構變化導致抓取失敗,嘗試改
   抓 https://www.dividendinvestor.com 或
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
     的部分),記為shares_before_ex_date。
     【修正,見本文件頂部"本副本已修正的問題"第2點】這個數字只能從
     state/ymag_trade_log.csv 按時間順序回放到candidate_ex_date(不含
     當天)倒推取得——不能用ymag_position.csv,因為該文件是每次覆蓋式
     更新的當前狀態,不保留歷史,在偵測滯後(源A/源B都可能滯後)導致
     ex_date是幾天前而期間又有交易發生的情況下,只有trade_log能正確
     回放出當時的持股數。
   - dividend_income = shares_before_ex_date × 確定的per-share金額
   - cumulative_dividends += dividend_income
   - cumulative_dividend_cash_in += dividend_income(不管下面流向哪個池
     子,都計入這個只增不減的來源追蹤計數器)
   - 若當前(執行當天)同時滿足"站上20日均線 且 range_pct_4w<5%":
     dividend_income 計入 cash_reserved
   - 否則:計入 cash_uninvested
   - 寫入 state/ymag_dividend_log.csv 一行:date(執行日),ex_dividend_date,
     source_used("robinhood"或"web:域名"),rh_amount,sa_amount,
     shares_before_ex_date,dividend_income,routed_to
7. 釋放擱置資金(目標是"今天實際會用到的建倉金額",不是寫死的$25):若
   當前(執行當天)同時滿足"站上20日均線 且 range_pct_4w<5%",且
   cash_uninvested > 0:先按第四層的月份/深跌例外規則算出"如果今天要買
   入,基礎金額會是多少"(標準月$25、非優選月$12.5、深跌例外$6.25),記
   為next_tranche_target;release_amount = min(cash_uninvested,
   max(0, next_tranche_target − cash_reserved))。cash_reserved +=
   release_amount,cash_uninvested −= release_amount,寫入
   state/ymag_dividend_log.csv 一行記錄本次轉移
   (action="RELEASE_UNINVESTED",amount=release_amount)。若
   release_amount為0(cash_reserved已經達到next_tranche_target),本次
   不釋放,cash_uninvested留待下次機會——這樣即使當前月份對應的檔位只
   需要$12.5,cash_reserved攢到$12.5左右就會持續釋放,不會因為死等一個
   不再適用的$25門檻而卡住。
8. 本層只處理分紅入賬與資金池調度,不觸發任何買入/賣出判斷。

【第四層:決策引擎(不下真實訂單,只寫入模擬決策)】
【預先計算:預估下次除息日】若state/ymag_dividend_log.csv裡至少有兩條
歷史分紅記錄,用最近兩次ex_dividend_date之間的實際天數差作為
interval_days;若不足兩條記錄,interval_days默認用7天。
estimated_next_ex_date = 最後一次記錄的ex_dividend_date + interval_days。
ex_date_within_window = (estimated_next_ex_date − 今天) <= 3天 且 >= 0
(容忍±3天誤差,應對假期導致的除息日實際提前或推遲,不用精確到某一天)。

買入條件(1-3必須同時滿足,4決定倉位大小,5是硬性宏觀門檻):
1. price_vs_ma20_pct > 0(收盤站上20日均線)
2. 箱體壓縮確認:若 shares == 0(空倉狀態下的首次建倉,即"Initial
   Position Exception"),放寬為 range_pct_4w < 8%;一旦建過第一檔
   (shares > 0 之後的所有後續加倉),恢復標準的 range_pct_4w < 5%。這條
   例外只在完全空倉時生效一次,原因是策略目標是建立分紅底倉而不是等一
   個完美的窄幅突破,若長期橫盤但一直達不到<5%的箱體,不應該永遠進不
   了場
3. invested_tranches < 4(用shares×avg_cost/25動態算出,還沒建滿4檔)
4. 倉位大小由月份決定,不再是"禁止/允許"的硬開關(策略目標是持續持股吃
   分紅,月份只影響倉位大小,不影響能不能買):
   - month in [5,7,9]:按標準檔位買入,基礎金額=$25
   - 其餘月份(1,6,8,10,11,12):基礎金額減半,=$12.5(仍然買,只是降低
     這幾個月歷史上風險偏高時期的倉位)
   - month in [2,3,4]:默認也只減半買入(=$12.5),除非命中下面的"深跌
     反轉例外"
5. market_trend == "up" 且 mag7_breadth >= 5:大盤和七巨頭多數(至少5/7)
   保持在自己的20日均線上方,才允許建倉——這是硬性門檻,不因為月份或深
   跌例外而放寬

深跌反轉例外(僅限month in [2,3,4]時使用,在第4條基礎上再減半,即
$6.25):
- month_return_so_far < -8%
- 公式化的"不再創新低"條件:rolling_low_5d = min(最近5個交易日收盤
  價);rolling_low_prior5d = min(再往前5個交易日收盤價,即第6-10個交易
  日);要求 rolling_low_5d >= rolling_low_prior5d(最近5日的最低點沒有
  比再往前5日的最低點更低)
- 成交量較前兩週均值下降
- 注意:即使命中這條例外,仍然必須同時滿足上面第5條的
  market_trend/mag7_breadth條件,不能因為是"深跌反轉"就跳過宏觀確認

若滿足買入條件:
- 計算本次建倉金額(按上面第4/深跌例外規則確定基礎金額),優先從
  cash_reserved扣減,不足部分從cash_principal裡扣(兩個字段都要實際做
  減法,不能只是概念上"從本金拿",cash_principal必須相應減少)
- 按今日收盤價計算模擬買入股數(允許小數股,見上方小額本金說明),更新
  shares,並按加權平均重新計算avg_cost = (原shares×原avg_cost + 本次買
  入金額) / 新shares;若買入前status為"flat",買入後把status更新為
  "holding"
- invested_tranches會在下次讀取倉位時根據新的shares×avg_cost自動算出,
  不需要單獨維護計數器
- 寫入 state/ymag_trade_log.csv 一行:date,action="BUY",price,
  shares_traded,amount_spent,reason(寫明命中的具體條件、當時的月份倉位
  倍數、market_trend和mag7_breadth數值)

【Recovery Buy:僅針對因宏觀信號被砍倉的情況】常規買入條件本身就是恢復
機制的一部分——減倉後invested_tranches會下降,只要之後價格重新站上均
線、箱體重新壓縮、mag7_breadth重新回到>=5,標準買入路徑會自然重新觸
發,不需要額外設計。但有一種情況標準路徑可能反應偏慢:如果之前是因為
TRIM_MAG7_BREADTH或TRIM_MARKET_TREND被砍倉(即recovery_pending=true),
而七巨頭廣度強力反彈,此時箱體寬度可能還沒來得及壓縮到<5%(V形反彈本身
就會短期內擴大波動區間),導致遲遲等不到標準買入條件全部滿足。為此增加
一條補充規則,僅在recovery_pending=true時生效:
- 觸發條件:mag7_breadth >= 6(比標準買入門檻5更嚴格)且 market_trend
  == "up" 且 mag7_mom_5d > 0(七巨頭近5日平均動能為正,確認不是假反
  彈)且 invested_tranches < 4
- 滿足時:豁免"range_pct_4w < 5%"這一條箱體壓縮要求(其餘買入條件仍然
  適用,包括price_vs_ma20_pct>0),按標準月份規則的基礎金額買入一檔,寫
  入trade_log,action="RECOVERY_BUY",並把recovery_pending重置為false
- recovery_pending這個標記只在TRIM_MAG7_BREADTH或TRIM_MARKET_TREND觸發
  時被設為true,其餘賣出原因(止損/破位/止盈/季節性)不設置這個標記,
  因為那幾種情況的減倉是YMAG自身或月份層面的判斷,不是宏觀急跌造成
  的,不需要這條加速回補的例外

賣出/減倉條件(優先級從高到低,先檢查賣出,再檢查買入,同一天只執行第
一條命中的,不疊加):
1. 【cross trigger】prev_mag7_breadth_healthy == true 且 今日mag7_breadth
   <= 2 且 status != "flat":七巨頭剛剛從"多數健康(>2)"轉為"多數走弱
   (<=2)"的那一天才觸發,減倉40%(而不是50%——考慮到這條和下面SPY那條
   可能在幾天內先後觸發,兩條都是較重比例的話會一次性砍掉過多分紅底
   倉,不符合"持股吃分紅優先於避開所有下跌"的策略定位)——不因為breadth
   連續多天維持在<=2就每天重複觸發。此條不受下方"除息日保護"限制,風險
   控制優先。執行後把prev_mag7_breadth_healthy更新為false、
   recovery_pending更新為true;若之後mag7_breadth回升到>2,把
   prev_mag7_breadth_healthy更新回true(recovery_pending是否清除見上方
   Recovery Buy規則)——寫入trade_log,action="TRIM_MAG7_BREADTH"
2. 【cross trigger】prev_market_trend == "up" 且 今日market_trend ==
   "down" 且 status != "flat":SPY剛剛從站上50日均線轉為跌破的那一天才
   觸發,減倉20%(同樣從30%調輕,理由同上)——同樣不受除息日保護限制。
   執行後prev_market_trend更新為"down"、recovery_pending更新為true;回
   升到"up"後再更新prev_market_trend回來——寫入trade_log,
   action="TRIM_MARKET_TREND"
3. 【已修正,見本文件頂部"本副本已修正的問題"第1點】consec_below_ma20
   == 3(精確等於3,不是>=3)且 status != "flat":減倉50%(按當前shares
   計算),不受除息日保護限制——寫入trade_log,action="TRIM_STOPLOSS"。
   這是一個one-shot cross trigger:consec_below_ma20每個合格交易日只會
   +1、一旦收盤重新站上ma20就歸零,所以"精確等於3"只會在每一輪連續走
   低的第3天觸發一次,不會在第4、5、6...天因為條件仍然成立而重複減
   倉。若之後這一輪走弱持續惡化到range_pct_4w>8%且創20日新低,由下面
   條件4(EXIT_BREAKDOWN)接手清倉,兩者不重疊。
4. range_pct_4w > 8% 且 今日收盤為過去20日新低 且 status != "flat":清
   倉(shares歸零,status="flat"),不受除息日保護限制——寫入trade_log,
   action="EXIT_BREAKDOWN"
5. 【受除息日保護】month_return_so_far > 5% 且 status != "flat" 且 本月
   尚未因此條件減倉過 且 ex_date_within_window == false:減倉30%-50%
   (擇中40%)——寫入trade_log,action="TRIM_PROFIT"。若ex_date_within_window
   為true,本條本次不觸發,等過了除息日再評估(為了不錯過近在眼前的一
   筆分紅而提前賣飛)
6. 【受除息日保護】month in [10,11] 或 (month==1 且 日期>=20號):且
   status != "flat" 且 本月尚未因此條件減倉過 且
   ex_date_within_window == false:減倉30%(主動降倉位)——寫入
   trade_log,action="TRIM_SEASONAL"。同樣若臨近除息日則本次不觸發

若同一天觸發多條賣出條件,按上面編號順序只執行第一條命中的,不疊加執
行,避免同一天過度減倉。

【所有減倉/清倉動作統一遵循以下兩條規則,寫死避免每次算法不一致】:
- avg_cost在任何賣出動作中保持不變,只有買入動作才會重新計算加權平均
  成本
- 賣出所得 = 賣出股數 × 當日收盤價,全部計入cash_reserved(視為立即可
  用資金);同時計算 realized_gain_this_trade = 賣出股數 × (當日收盤價
  − avg_cost),累加進 cumulative_realized_gain;並把本次賣出所得全額累
  加進 cumulative_sale_cash_in,用於報告裡區分這個池子裡的錢歷史上有多
  少是分紅、多少是賣股票賺的

【第五層:輸出報告】
生成 reports/ymag/{今天日期}.md,包含:
- 今日價格、ma20、range_pct_4w、consec_below_ma20、month_return_so_far
- 大盤/七巨頭狀態:market_trend(up/down)、mag7_breadth(0-7)、
  mag7_mom_5d(現已用於Recovery Buy判斷,不再只是擺設)
- 今日命中的買入/賣出條件(若都未命中,寫明"今日無操作,維持現狀")
- 若本次檢測到新一筆分紅(ex_dividend_date比上次記錄更新):分紅
  per-share金額、分紅收入、流向(cash_reserved/cash_uninvested)、數據
  來源(robinhood或web源);若兩源數據均獲取失敗,註明"本次分紅數據未
  獲取";若兩源金額不一致,註明差異並說明已採用哪個數值
- 若本次發生了cash_uninvested釋放(RELEASE_UNINVESTED):註明釋放金額
  和轉入後的cash_reserved餘額
- 當前模擬倉位狀態(shares、avg_cost、浮動盈虧%、invested_tranches、
  cash_principal、cash_reserved、cash_uninvested、cumulative_dividends、
  cumulative_realized_gain、total_account_value)
- 現金來源構成(僅展示,不影響計算):cumulative_dividend_cash_in(歷史
  分紅流入合計)vs cumulative_sale_cash_in(歷史賣股所得合計),讓你一眼
  看出cash_reserved這個池子裡的錢主要是哪來的
- 總回報拆分:相對初始本金$100的總收益率(用total_account_value計
  算)、其中價格端浮盈浮虧貢獻多少、已實現價差(cumulative_realized_gain)
  貢獻多少、分紅貢獻多少(cumulative_dividends),四項都列出來,不要只
  給一個籠統的"總收益"數字
- 分紅儀表盤(Dividend Dashboard),因為這個策略的核心目標是分紅收益而
  不是價差:
  - Forward Annual Income(前瞻年化分紅收入)= 當前shares × 最近一次
    per-share分紅金額 × 52,代表按當前持股量和當前分紅水平推算,未來一
    年大概能拿到多少分紅
  - Trailing 12M Dividend Yield(過去12個月實際股息率)= 過去12個月內
    state/ymag_dividend_log.csv裡所有dividend_income加總 / 當前
    shares×avg_cost——這是"實際拿到過多少",和上面Forward的"照現在水平
    推算未來"是兩個不同的數字,都要展示,不要互相替代。YMAG是每週分紅
    且金額不固定的ETF,單看Forward可能因為某一週分紅金額偏高或偏低而
    失真,兩個對照著看更完整
  - 當前年化股息率估算 = 最近一次per-share分紅金額 × 52 / 當前收盤價
  - 累計分紅佔初始本金比例 = cumulative_dividends / 100
  - 已持有週數(從第一筆BUY記錄的日期算到今天)
  - 若ex_date_within_window為true,註明"臨近預估除息日,本次已跳過獲
    利了結/季節性減倉判斷"
- 若今日執行了模擬交易,列出具體動作和原因(若是RECOVERY_BUY,額外註明
  是在哪次TRIM_MAG7_BREADTH/TRIM_MARKET_TREND之後觸發的回補)

更新 state/ymag_position.csv 為最新一行(覆蓋式更新當前狀態,不是追加歷
史,歷史交易只在ymag_trade_log.csv裡追加)。

【驗證,commit前必做】
- reports/ymag/{今天日期}.md 文件存在且非空
- state/ymag_position.csv 中 shares、avg_cost、cash_principal、
  cash_reserved、cash_uninvested、cumulative_dividends、
  cumulative_realized_gain、cumulative_dividend_cash_in、
  cumulative_sale_cash_in、total_account_value 均不可為負數,也不可為
  NaN/空值(任一字段是NaN都視為文件損壞,不commit)
- 若 shares > 0,avg_cost 必須 > 0(否則說明持倉成本沒有正確計算或文件
  損壞,不commit)
- total_account_value 必須等於 shares × 當日收盤價 + cash_principal +
  cash_reserved + cash_uninvested(允許極小的浮點誤差,比如0.01以內),
  不相等視為計算錯誤,不commit
- market_trend 字段只能是"up"或"down"二選一,status字段只能是"flat"或
  "holding"二選一,出現其他值視為計算錯誤,不commit
- 若本次觸發了買入或賣出,state/ymag_trade_log.csv 必須新增對應行,且
  price字段不可為空或負數
- 若本次判定為新一筆分紅並已入賬,state/ymag_dividend_log.csv 必須新增
  對應行,且dividend_income不可為負數,source_used字段不可為空
- mag7_breadth 必須是0到7之間的整數,超出範圍視為計算錯誤,本次不commit
- 若任何一項驗證失敗:不commit,保留現有文件不變,在最後回復裡說明失敗
  原因

驗證通過:
git add data/prices/ state/ymag_position.csv state/ymag_trade_log.csv state/ymag_dividend_log.csv reports/ymag/
git commit -m "ymag paper trading YYYY-MM-DD"
git push origin claude/ymag-paper-state

若push失敗,先git pull重新同步,再重試一次;若仍失敗,結束並在回復裡說
明push失敗、本次結果未能寫入repo。

【禁止事項】
這個routine只做模擬倉位記錄和信號決策,絕不調用任何真實下單、真實賬戶
操作、真實資金劃轉類工具。不與claude/scanner-state或repo中其他分支有任
何讀寫互動。所有"買入""賣出"僅為文件內的模擬記賬,不代表任何真實交易指
令。

首次運行前置條件
無需依賴其他routine——本routine第一層會自行拉取YMAG完整歷史價格,可以
獨立作為第一個"Run now"手動觸發,驗證跑通後再設置為schedule自動執行。
```

## Initial state (seeded 2026-07-23)

`state/ymag_position.csv`, `state/ymag_trade_log.csv` (header only), and
`state/ymag_dividend_log.csv` (header only) were pre-seeded so the first
run's starting state is explicit and auditable, rather than relying on the
routine's own first-run initialization defaults. `data/prices/` is left
empty (just `.gitkeep`) — the routine's Layer 1 populates all 9 symbols'
full ~13-month history on its first run, per its self-bootstrap design.
