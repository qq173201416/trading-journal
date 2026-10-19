# trading-journal
trading journal AI

## 分支 claude/holdings-reports

存放持仓日报/周报任务的输出,以及持仓论点:

- `thesis.yaml` — 每个持仓的买入理由与论点失效条件(人工维护)
- `logs/` — 日报任务运行日志(`daily_log.jsonl`)
- `reports/daily/` — 每日盘前持仓日报,`YYYY-MM-DD.md`
- `reports/weekly/` — 每周持仓周报,`YYYY-MM-DD.md`

持仓清单以 `claude/takeprofit-monitor-state` 分支的 `positions.yaml` 为准。
