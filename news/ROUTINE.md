# Telegram 新闻 → 股市影响分析 routine

每次运行按顺序执行，工作分支 `tg-news`（报告和 state 都提交到这里）。

## 步骤

1. `git fetch origin tg-news && git checkout tg-news && git pull origin tg-news`
2. `python3 news/tg_news.py fetch` —— 拿到本次新消息（JSON）。
   - `count == 0`：直接执行第 6 步的 `ack`，提交 state 后结束，**不推送**。
3. 分析（见下方规范）。需要时可以用 WebSearch 核实消息真伪、补充背景或查最新价格。
4. 报告写到 `news/reports/YYYY-MM-DD_HHMM.md`（美东时间）。
5. `python3 news/tg_news.py send news/reports/<文件>.md` 推送到个人 Telegram。
6. `python3 news/tg_news.py ack`
7. `git add news/ && git commit -m "tg news analysis <时间> ET" && git push -u origin tg-news`

任何一步失败：不要 ack（消息会在 Telegram 保留 24h，下次重拿），在报告/输出里写清失败原因。

## 分析规范

- 先去重、合并同一事件的多条消息；纯闲聊/广告/无关内容直接忽略，在末尾注明忽略了几条。
- 每个有意义的事件给出：
  - **事件**：一句话概括 + 可信度（已证实 / 单一来源 / 传闻），有疑点说清楚
  - **影响方向与幅度**，分三档时间：
    - 短期（1–5 个交易日）：情绪、资金流、开盘跳空、期权波动
    - 中期（1–3 个月）：盈利预期、政策落地、行业轮动
    - 长期（6 个月以上）：基本面、结构性趋势、估值中枢
  - **受影响标的**：大盘指数（SPX/NDX/RUT）、行业 ETF、具体个股 ticker，标 利好/利空/中性
  - **关键观察点**：后续需要盯的数据、日期、价位
- 最后给 **综合结论**：本批消息整体偏多/偏空/中性，以及对现有持仓（`virtual_account.json`，若有）的提示。
- 区分事实和推断；不确定时明确写不确定，不要编造数字。

## 报告格式（纯文本友好，Telegram 直接可读）

```
📰 TG 新闻分析 | 2026-10-22 14:00 ET | 新消息 N 条

【事件1】……（可信度：……）
短期：利多/利空 …… 理由
中期：……
长期：……
相关：NVDA↑ SMH↑ QQQ↑
观察：……

【综合】……
（忽略 N 条无关消息）
```
