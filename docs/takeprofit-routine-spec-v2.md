# 止盈监控 Routine — 完整设计文档 v2(Claude Code Routines 版）

## 1-8 节:不变
数据结构、执行节奏、分层止盈阈值、大盘过滤器、财报避险、state.json 规则,和 v1 完全一致(见仓库里的 v1 文档)。以下只写变动的部分。

## 9. 执行层:改用 Claude Code Routines

**不再用 GitHub Actions**,改成 claude.ai/code/routines 上的一个 Cloud Routine。

### 9.1 Environment(先建这个,再建routine)
路径:claude.ai/code/routines → Settings → Environments → New environment

- 环境变量:
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`
- 出站网络白名单(只开这几个域名,不要开放全网):
  - `api.telegram.org`
  - 你选定的行情数据源域名(如用 Yahoo Finance 相关域名)
- Setup script(routine启动时先跑):
  ```bash
  pip install requests pyyaml pandas numpy
  ```

### 9.2 Routine 配置
- Repository: `trading-journal`
- Environment: 上面建的那个
- 分支:默认只能推 `claude/` 前缀分支 → 用 `claude/takeprofit-monitor-state`(和你其他项目的隔离习惯一致,不用改)
- Connectors:不需要额外MCP连接器,routine自带的shell + 网络访问就够(直接调用Telegram API + 行情API)

### 9.3 触发器(Trigger)
**不能用预设的"hourly"**(会24小时跑,你只要开市时段)。改用自定义 cron,最小间隔1小时:

```
30 13-19 * * 1-5
```
含义:UTC时间13:30-19:30、周一到周五、每小时的第30分触发,对应 ET 9:30-15:30(夏令时)。**注意**:ET和UTC的偏移3月和11月各切换一次(夏令时/冬令时),切换那两周要手动改一次cron,不然会提前或推迟1小时触发。

**先去 claude.ai/code/routines 确认你当前plan的每日routine运行上限**——开市时段每小时跑一次大概6-7次触发/天,如果你的plan每日上限不够这个数,要么升级plan,要么把频率降到每2小时一次(那样第2点hourly RSI极值辅助信号的意义会变小,需要相应调整)。

## 10. Routine Prompt 初稿(可直接粘贴)

Routine没有人工审批环节,所以prompt必须把规则和输出边界写清楚,不能模糊。草稿如下,你可以直接用,也可以按实际字段名调整:

```
你是一个止盈监控 routine,每次运行执行以下固定流程,不要偏离这个流程,不要自主决定额外操作。

1. 读取仓库 claude/takeprofit-monitor-state 分支下的 positions.yaml、config.yaml、state.json。
2. 对 positions.yaml 里的每个 ticker:
   a. 获取最新实时价格。
   b. 如果今天还没有today's daily cache(检查 daily_cache.json 里的日期戳),先计算 T-1 日线 RSI、20MA、ATR_20d、
      距近期高点百分比,并抓取 next_earnings_date,写入 daily_cache.json(视为当天缓存,一天只算一次)。
   c. 用当前价格 + avg_cost 计算浮盈%。
   d. 按 config.yaml 里的分层阈值(default_profit_targets,若该ticker在overrides里则用override)判断命中哪个tier
      (Tier 1/2/3 从高到低判断,只取最高命中的tier,不要同时报多个)。
   e. 同时检查 Hourly RSI 是否 > 80(仅作为 Tier 3 的紧急辅助触发,不影响 Tier 1/2 判断)。
   f. 读取大盘状态(SPY 50MA trend + mag7_breadth,复用 claude/ymag-paper-state 分支里已有的计算逻辑,不要重新实现)。
      如果大盘处于主升浪(market_trend=up 且 mag7_breadth>=5):命中的tier只建议小幅减仓/移动止盈,不建议清仓。
      如果大盘转弱:命中tier的减仓建议权重加倍。
   g. 检查 next_earnings_date,如果在3天以内,提醒文本前追加 [⚠️ 财报即将来临],并将建议减仓比例提高一档。
   h. 对比 state.json 里该ticker的 executed_tier:
      - 如果本次命中的tier <= 已执行的tier,不发送提醒(避免重复)。
      - 如果本次命中的tier > 已执行的tier,发送Telegram提醒,并更新 state.json 的 executed_tier、
        current_stage、last_triggered_at、rsi_peak、highest_price_since_buy。
   i. 重置检查:如果现价收盘价 < avg_cost,或 positions.yaml 里该ticker的 avg_cost/shares 相比上次读取发生变化
      (加仓/摊薄),将该ticker的 executed_tier 重置为 0,current_stage 重置为 IDLE。
      注意:单纯shares减少但avg_cost不变(减仓)绝不触发重置。
3. Telegram提醒格式:
   [ticker] Tier N 触发 | 浮盈 X% | RSI: Y | 大盘: up/down | [⚠️ 财报即将来临](如适用)
   建议: <action_suggestion 文本>
4. 把本次运行的完整结果(每个ticker的价格/信号/是否触发/tier)追加写入 run_log.jsonl,commit到
   claude/takeprofit-monitor-state 分支。
5. 不要执行任何交易、不要修改 positions.yaml 里的shares/avg_cost/这些只能人工改)、不要推送到claude/以外的分支、
   不要在没有命中新tier时发送Telegram消息。
```

## 11. 待建文件清单(更新)
- [ ] `positions.yaml` 模板
- [ ] `config.yaml`(骨架见 v1 文档第5节)
- [ ] `state.json` 初始结构(骨架见 v1 文档第8节)
- [ ] `daily_cache.json` 初始结构(新增,存当天算好的日线指标+财报日期)
- [ ] `signal_engine.py` 或直接让routine prompt里的逻辑跑(看你要不要脚本化,脚本化更稳定可调试)
- [x] `telegram_bot.py`(已完成,env var版,适配Claude Routine的Environment变量)
- [ ] Claude Routine 本体(Environment + Trigger cron + 上面第10节的prompt)
- [x] 原 GitHub Actions test-telegram.yml(作废,不再需要,Telegram测试改成直接跑一次routine看Actions/routine运行记录)

---

## 归档说明

这份 v2 是止盈监控最初的设计草稿。实际落地时经过多轮迭代修正(并发写入保护、首次初始化判断、
Hourly RSI 触发需要浮盈>0门槛、大盘/行情数据改用 Robinhood Connector 而非域名白名单、每日心跳、
开市时段兜底检查等),最终又被 [v14 SOP](./takeprofit-routine-spec-v14.md)(止盈+止损+顺势加仓+
观察名单重新建仓)整体取代。这份文件只做历史留档,当前实际生效的规则以 v14 文档、`config.yaml`、
以及 routine 的 Instructions 为准,不要按这份 v2 的内容去核对现在的行为。
