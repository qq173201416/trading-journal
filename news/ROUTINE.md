# Telegram 新闻 → 股市影响分析 routine

代码在 `tg-news` 分支。本 routine **只读仓库、不 push**：读到哪了由 Telegram 服务端记录，报告直接发到个人 Telegram。

## 步骤

1. `git clone -b tg-news https://github.com/qq173201416/trading-journal.git && cd trading-journal`（已有仓库则 `git fetch origin tg-news && git checkout tg-news && git pull origin tg-news`）
2. `python3 news/tg_news.py fetch` —— 拿到本次新消息（JSON）。
   - `count == 0`：直接结束，**不推送**。
3. 分析（见下方规范）。需要时可以用 WebSearch 核实消息真伪、补充背景或查最新价格。
4. 报告写到本地临时文件，例如 `/tmp/tg_report.md`。
5. `python3 news/tg_news.py send /tmp/tg_report.md` 推送到个人 Telegram。
6. 发送成功后 `python3 news/tg_news.py ack`。

任何一步失败：不要 ack（消息会在 Telegram 保留 24h，下次重拿），在输出里写清失败原因。

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
- 最后给 **综合结论**：本批消息整体偏多/偏空/中性，以及对现有持仓（仓库根目录 `virtual_account.json`，若有）的提示。
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
