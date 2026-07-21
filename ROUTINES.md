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

Trigger: Schedule, weekly
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
   - Sector ANY_OF: Technology, Communication Services, Consumer Cyclical,
     Healthcare, Industrials

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

Trigger: Schedule, every trading day (after close, e.g. after 16:30 ET)
Repository: trading-journal

```
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

【第二層:增量更新每檔股票的歷史價格,以及SPY基準】
對 universe.csv 裡每一檔 ticker(以及額外固定加上SPY作為大盤基準,
SPY只需維護一份、不受universe篩選影響),分別檢查
data/prices/{TICKER}.csv 是否存在:

- 若不存在,或現有資料列數少於260列:視為第一次執行或資料不足,
  用 get_equity_historicals(單一symbol、interval="day",
  start_time設為約13個月前)取得完整歷史,寫入
  data/prices/{TICKER}.csv(欄位:begins_at,open_price,close_price,
  high_price,low_price,volume,session),過濾掉interpolated=true
  的補值bar。

- 若已存在且資料足夠:讀取檔案裡最後一列的日期,只用
  get_equity_historicals查詢「最後日期隔天」到「今天」這段區間的
  新K線,追加到檔案尾端(不要整批重下載)。若查回來的區間裡今天
  的bar還沒收盤結算(例如盤中執行),仍先寫入、下次執行會用同樣邏輯
  再次核對更新最新一筆。

- 【重要】get_equity_historicals查歷史範圍時,一次只查一檔symbol,
  不要把多檔股票或股票與SPY放進同一次呼叫的symbols陣列裡一起查
  這麼長的範圍。

【第三層:跑技術引擎】
對每一檔股票(不含SPY本身),讀取 data/prices/{TICKER}.csv 和
data/prices/SPY.csv 的完整內容,用 scripts/technical_engine.py 的
compute_features(symbol, bars, spy_bars) 算出完整特徵(trend_score、
rs_score、atr_pct、stage、phase、extension_pct、weeks_in_base、
vol_dry_up_ratio、rs_improving等,完整欄位見該函式回傳的dict)。

把今天所有股票的計算結果,追加寫入 data/features/features_daily.csv
(欄位順序需與現有檔案表頭一致)。若今天的日期已經在檔案裡出現過
(代表這個routine今天已經執行過一次),不要重複追加,直接使用已有
的今天資料繼續下一步即可。

【第四層:篩選輸出】
從今天算出的特徵裡,篩出 stage == "deep_base_watch" 的股票
(對應config.yaml裡extension區塊的門檻:extension_pct <= -30%、
vol_dry_up_ratio < 0.7、weeks_in_base >= 8且base_low_undercut_since
為false)。

1. 產生 reports/{今天日期}.md,列出這些股票的完整細節表格
   (ticker、extension_pct、weeks_in_base、vol_dry_up_ratio、
   rel_ret_30d、price)。若今天沒有任何股票符合,報告裡仍要產生,
   內容寫明"今天沒有股票通過deep_base_watch門檻"。

2. 對每一檔符合的股票,在 experiments/registry.csv 追加一列
   (欄位:signal_date,ticker,price_at_signal,stage,trend_score,
   rs_score,extension_pct,weeks_in_base,vol_dry_up_ratio,model_version,
   future_5d_return,future_20d_return,future_60d_return,
   future_120d_return),model_version填config.yaml裡目前的版本號,
   四個future_return欄位留空。若今天這檔股票、這個日期的組合已經在
   registry.csv裡存在,不要重複追加。

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
讀寫互動。
```

## First-run order

Universe Update must be run once (manual "Run now") before Daily Pipeline's
first run — Daily Pipeline's Layer 1 refuses to run against an empty
`data/universe.csv`, and the seed file committed to this branch has headers
only, no rows.
