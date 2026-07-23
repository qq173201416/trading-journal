# Scanner Routines — claude/scanner-state

Reference copy of the two Claude Code Routine prompts running against this
branch. This is documentation only — the routines themselves are configured
at claude.ai/code/routines and read/write this branch directly, not this file.

Repository: `trading-journal`
Branch: `claude/scanner-state` (fixed, orphan — independent from `main` and
from any other branch in this repo, e.g. the trading-journal execution
project's own branch)
Branch permission: default (no "Allow unrestricted branch pushes" needed —
`claude/`-prefixed branches are pushable by default)

## Routine A — Scanner Universe Update

Trigger: Schedule, weekly, Monday 18:37 UTC (~1:30–2:30pm ET depending on DST —
mid-session, past the thin pre-market/open window)
Repository: trading-journal

```
【分支持久化,第一步必做】
這個repo每次執行都會從main重新clone,不會記得上次的狀態。
所以第一件事(在git pull之前)一定要先做:

git fetch origin claude/scanner-state
git checkout claude/scanner-state 2>/dev/null || git checkout -b claude/scanner-state

後面所有讀寫、git pull、git push,都一律針對這個固定分支
(claude/scanner-state)進行,不要用session預設建立的分支,也不要跟這個
repo裡其他分支(例如claude/base-lifecycle-v2-state,那是完全不同的
交易日誌專案)有任何互動或讀寫。

git pull 拿最新版本。

【這個routine只做一件事:重建股票池,不做任何篩選判斷、不查個股歷史K線】

1. 用 Robinhood 的 run_scan(或 create_scan/update_scan_filters 建立/更新
   一個掃描)套用以下條件:
   - Last(股價) > $20
   - Market Cap > $2,000,000,000
   - Average Volume(30日,1d區間) > 500,000
   - Sector 排除(對應 config.yaml 的 exclude_sectors,不要另外用白名單
     限制只留特定板塊):Financial, Utility, Energy, REIT, Biotech。
     先呼叫 get_scanner_filter_specs 確認 sector 篩選欄位支援的
     predicate——優先用排除類的predicate(例如NOT_IN_LIST/EXCLUDE等,
     實際名稱以get_scanner_filter_specs回傳為準);若該API不支援排除
     predicate,退而求其次:取得完整sector清單後,用ANY_OF列出「除了
     這5個以外的所有sector」,讓最終效果等同於排除這5個。

2. 取得掃描結果的完整清單(ticker、sector、market_cap、average_volume)。

3. 讀取現有的 data/universe.csv(schema:
   ticker,exchange,sector,market_cap,avg_volume,last_updated)。
   若檔案不存在,視為空清單。

4. 用本次掃描結果整份覆蓋 data/universe.csv 的內容(不是追加——這是
   股票池的最新快照,舊的一份會被完全取代;overwrite前,新內容需先
   通過下方第5步驗證)。每一列的 last_updated 欄位填今天日期。

5.【驗證,commit前必做】
   - 檔案至少要有1列資料(不能是空清單,若掃描結果是空的,判定失敗,
     保留原本的universe.csv不覆蓋,在commit message裡記錄
     "scan returned 0 results, universe.csv unchanged")
   - 每一列的 ticker 欄位不可為空字串
   - 每一列的 market_cap、avg_volume 需為正數

6. 驗證通過:
   git add data/universe.csv
   git commit -m "universe update YYYY-MM-DD"
   git push origin claude/scanner-state

   若push失敗(例如非fast-forward),先 git pull 重新同步一次,
   再重試push一次。若第二次仍失敗,結束並在最後的回覆裡明確說明
   push失敗、universe.csv本次未能更新。

【禁止事項】
這個routine只更新 data/universe.csv,不碰 data/prices/、
data/features/、experiments/、reports/ 裡的任何檔案,不呼叫任何
下單、watchlist修改、或帳戶操作類工具。
```

## Routine B — Scanner Daily Pipeline

Trigger: Schedule, weekdays, 21:30 UTC (16:30 ET in EST / 17:30 ET in EDT —
chosen so it always lands at or after the 16:30 ET gate below in both DST
states; the previous 21:00 UTC only cleared the gate in EDT and would have
self-aborted every day once DST ended)
Repository: trading-journal

```
【執行時機檢查,必須在分支持久化之前先做】
用 Bash 執行 `TZ=America/New_York date +"%u %H:%M"`,取得目前真實的美東
時間與星期幾(這個指令會自動處理夏令時轉換,不用自己換算UTC offset)。
確認:(a) 星期幾是1-5(週一到週五),且 (b) 時分已經是16:30或之後
(即收盤4:00pm ET之後至少30分鐘)。兩個條件都成立才繼續往下執行;
任一不成立就直接結束,不做任何git操作、不呼叫任何其他工具。

【分支持久化,第一步必做】
git fetch origin claude/scanner-state
git checkout claude/scanner-state 2>/dev/null || git checkout -b claude/scanner-state

後續所有讀寫、push,一律針對這個分支,不要跟repo裡其他分支
(例如claude/base-lifecycle-v2-state,不同專案)有任何互動。

git pull 拿最新版本。

【第一層:讀取股票池(唯讀)】
讀 data/universe.csv。若檔案不存在或是空的,結束執行並記錄錯誤——
代表Universe Update routine還沒成功跑過至少一次,不要在這裡自己
重新掃描全市場。

【第二層:更新每檔股票的歷史價格,以及SPY基準 —— 分批處理,可跨多次
執行接續完成,不要為了在一次執行內處理完全部股票池而放棄這個上限】

【重要禁令,優先於下面所有步驟】全程只能在單一個連續的主線程裡循序
處理每一檔股票,絕對不可以用Task/Agent工具或任何背景、非同步子任務
的方式平行處理多檔股票。這個routine run被判定完成時,只看主線程有沒有
跑完——任何丟給背景子任務去做的工作,就算子任務本身之後真的執行完成,
也沒有任何東西會在routine run結束後回來把它的結果commit進repo,等於
白做、資料會遺失。這不是效能考量的建議,是這個平台執行模型下的硬性
限制:寧可循序處理少一點(受下方60檔上限保護),也不要平行處理更多但
可能全部遺失。

0. SPY 永遠第一個處理,不受下方batch上限限制(只有1檔,成本低):
   檢查 data/prices/SPY.csv 是否存在且資料列數>=260。不存在或不足,
   用 get_equity_historicals(interval="day", start_time設為約13個月前)
   取得完整歷史;已存在且足夠,只查「最後日期隔天」到「今天」的新K線
   追加進去。

A.【回填批次 —— 尚未完成初始回填的股票,每次執行有上限】
   依 universe.csv 裡的 ticker 字母順序(不含SPY),找出
   data/prices/{TICKER}.csv 不存在或資料列數<260 的股票(視為
   "尚未完成初始回填"),從順序中第一檔開始,最多處理60檔:
   用 get_equity_historicals(單一symbol、interval="day",
   start_time設為約13個月前)取得完整歷史,寫入
   data/prices/{TICKER}.csv(欄位:begins_at,open_price,close_price,
   high_price,low_price,volume,session),過濾掉interpolated=true
   的補值bar。
   這60檔的上限是為了避免單次執行處理過多股票導致中途被中斷、
   留下不完整的資料——如果全部1008檔還沒回填完,本來就需要跨好幾個
   交易日的執行才能全部補齊,這是預期中的正常過程,不是錯誤。
   (60是保守估計的起始值,若之後觀察到實際能穩定處理更多或更少,
   之後可以調整這個數字,不用經過我的prompt改動,你自己在
   Instructions欄位改這個數字即可。)

B.【增量批次 —— 已完成初始回填的股票,沒有上限】
   對「本次執行開始時就已經有>=260列資料」的股票(A的產出不算,
   避免同一檔股票同一次執行內被查兩次),讀取檔案最後一列的日期,
   只用get_equity_historicals查詢「最後日期隔天」到「今天」這段
   區間的新K線,追加到檔案尾端(不要整批重下載)。若查回來的區間裡
   今天的bar還沒收盤結算(例如盤中執行),仍先寫入、下次執行會用
   同樣邏輯再次核對更新最新一筆。

- 【重要】get_equity_historicals查歷史範圍時,一次只查一檔symbol,
  不要把多檔股票或股票與SPY放進同一次呼叫的symbols陣列裡一起查
  這麼長的範圍。

【第二層批次進度commit —— 這是本routine唯一允許在第四層最終驗證
之前就先commit的情況,跟下面第四層那個"全部驗證通過才commit"的
規則是分開的兩件事】
若A或B這次有任何一檔股票的data/prices/{TICKER}.csv被新增或更新過:
  git add data/prices/
  git commit -m "prices batch YYYY-MM-DD (N tickers backfilled, M tickers incremented)"
  git push origin claude/scanner-state
  (push失敗處理同其他步驟:先pull重新同步一次,再重試一次)
這個commit範圍只限data/prices/,不影響第四層features_daily.csv、
registry.csv、reports/那組最終commit的獨立驗證規則。

【第三層:跑技術引擎 —— 對每檔已完成回填的股票,用其目前最新一筆
真實(非interpolated)資料計算特徵】
【重要,實測發現】Robinhood歷史K線API對「今天」這個日曆日期的資料,
執行當下(即使已經收盤數小時)往往只會回傳interpolated=true的佔位
bar(volume=0,沒有真實成交數據),已經在第二層被過濾掉,不會出現在
data/prices/{TICKER}.csv裡。真實的「今天」日K線通常要等到隔天才查得
到。所以這裡**不要求**最後一列日期一定要等於執行當下的日曆日期——
只要求資料本身足夠(>=260列)即可,直接用檔案裡實際存在的最新一筆
真實資料計算,那就是目前能拿到的最新狀態。

對 universe.csv 裡「此刻data/prices/{TICKER}.csv已存在且資料列數
>=260」的股票(不含SPY本身),讀取該檔案和data/prices/SPY.csv 的
完整內容,用 scripts/technical_engine.py 的 compute_features(symbol,
bars, spy_bars) 算出完整特徵(trend_score、rs_score、atr_pct、stage、
phase、extension_pct、weeks_in_base、vol_dry_up_ratio、rs_improving
等,完整欄位見該函式回傳的dict)。還沒完成初始回填的股票,這次就
跳過,不算錯誤,之後每次執行涵蓋的股票數會逐步增加。

每一檔股票的features列,date欄位填該股票資料檔案裡「最後一列的實際
日期」(即這次compute_features實際使用的最新bar日期,不是執行當下
的日曆日期——不同股票這個日期可能不完全一樣,這是正常的)。把這次
算出的計算結果,追加寫入 data/features/features_daily.csv(欄位順序
需與現有檔案表頭一致)。若某檔股票、這個date的組合已經在檔案裡出現
過,不要重複追加。

【第四層:篩選輸出】
從今天算出的特徵裡,篩出 stage == "deep_base_watch" 的股票
(對應config.yaml裡extension區塊的門檻:extension_pct <= -30%、
vol_dry_up_ratio < 0.7、weeks_in_base >= 8且base_low_undercut_since
為false)。

1. 產生 reports/{今天日期}.md,列出這些股票的完整細節表格
   (ticker、extension_pct、weeks_in_base、vol_dry_up_ratio、
   rel_ret_30d、price)。若今天沒有任何股票符合,報告裡仍要產生,
   內容寫明"今天沒有股票通過deep_base_watch門檻"。若universe裡還有
   股票尚未完成初始回填(第二層A還沒處理到),在報告開頭加一行註記
   今天實際涵蓋了幾檔、還剩幾檔沒回填,讓每天的結果口徑透明,不要
   讓人誤以為today的報告已經涵蓋整個universe。

2. 對每一檔符合的股票,在 experiments/registry.csv 追加一列
   (欄位:signal_date,ticker,price_at_signal,stage,trend_score,
   rs_score,extension_pct,weeks_in_base,vol_dry_up_ratio,model_version,
   future_5d_return,future_20d_return,future_60d_return,
   future_120d_return),signal_date用第三層算出的該股票features那一列
   的date(該股票最新一筆真實資料的實際日期,不是執行當下的日曆日期),
   model_version填config.yaml裡目前的版本號,四個future_return欄位
   留空。若這檔股票、這個signal_date的組合已經在registry.csv裡存在,
   不要重複追加。

【驗證,commit前必做】
- reports/{今天日期}.md 檔案存在且非空
- features_daily.csv、registry.csv 裡新增的每一列,score類欄位數值
  需在合理範圍(0-100,或百分比欄位在-100到+100之間),ticker欄位
  不可為空,price不可為null或負數
- 若任何一項驗證失敗:不要commit,保留現有檔案內容不變,在最後回覆裡
  明確說明失敗原因,不要嘗試自己修正資料後硬是commit

驗證通過:
git add data/prices/ data/features/features_daily.csv experiments/registry.csv reports/
git commit -m "daily pipeline YYYY-MM-DD"
git push origin claude/scanner-state

若push失敗,先git pull重新同步,再重試一次;若仍失敗,結束並在回覆裡
說明push失敗、本次結果未能寫入repo。

【禁止事項】
這個routine只產生候選名單和特徵數據,不做任何進場/出場判斷,不呼叫
任何下單、watchlist修改、或帳戶操作類工具,不涉及虛擬或真實資金部位,
不跟repo裡其他分支(例如trading-journal本身的交易日誌分支)有任何
讀寫互動。不可以用Task/Agent工具或任何背景/非同步子任務處理股票批次
(見第二層開頭的禁令說明)。
```

## First-run order

Universe Update must be run once (manual "Run now") before Daily Pipeline's
first run — Daily Pipeline's Layer 1 refuses to run against an empty
`data/universe.csv`, and the seed file committed to this branch has headers
only, no rows.

## Bootstrap period (initial price backfill)

The universe currently has ~1008 tickers. Layer 2's first-time historical
fetch is one `get_equity_historicals` call per ticker (~380 days each) —
too much for a single routine run to finish in one pass, which is what
caused the 2026-07-21 run to stop after 1 ticker (`data/prices/A.csv`) and
leave a stray `fetch prices: partial batch update (in progress)` commit
that didn't follow the prompt's commit rules at all.

Fixed by capping Layer 2's backfill to 60 not-yet-backfilled tickers per
run, with an explicit intra-run checkpoint commit (`prices batch YYYY-MM-DD
(N tickers backfilled, M tickers incremented)`) separate from Layer 4's
final all-or-nothing commit. Resume state is just "does
`data/prices/{TICKER}.csv` exist with >=260 rows" — no separate cursor
file needed. At 60/weekday run and one run/day, full backfill of ~1008
tickers takes roughly 3-4 weeks; Layer 3/4 run against whatever subset is
ready each day and grow their coverage daily rather than waiting for the
full backfill to finish. Manually clicking "Run now" more than once a day
is safe and speeds up the bootstrap — each run picks up the next 60
un-backfilled tickers.

60 is a starting estimate, not a measured limit — if commit history shows
a run consistently finishing well under 60 with room to spare, or getting
cut off before 60, adjust the number directly in the Instructions field.

### 2026-07-21 evening run: lost work from background subagents

A manual run committed the SPY refresh (`cb3873d`) then, on its own
initiative (not instructed to), dispatched 3 background Task/Agent
subagents to backfill the 60-ticker batch in parallel (20 tickers each).
The routine run was marked complete while those subagents still showed as
"running" in the UI, and none of their work ever landed — no further
commits appeared. Routines are judged complete based on the main thread
only; work handed off to background subagents has nothing left alive to
commit and push it once the run ends, so it's effectively lost, not just
delayed. Added an explicit prohibition at the top of Layer 2 (and restated
under 禁止事項) against using Task/Agent or any background/async execution
for batch processing — everything must happen sequentially in the single
live thread so it's guaranteed to be captured before the run ends.
