# 止盈监控 + INFQ回调加仓 — 完整设计文档 v3.1(最终版）

本版取代 v1、v2、v3，整合所有已锁定决策 + 事件ID绑定/ATR冻结/持仓快照/执行顺序 4项工程加固，可直接对照在网页版实现。

---

## 一、共享模块：swing_structure.py

**位置**：只放在 `main` 分支 `lib/swing_structure.py`，各项目分支运行时借用，不复制：
```bash
git show main:lib/swing_structure.py > swing_structure.py
```

**职责边界**：只输出"市场结构事实"（HH/HL/LH/LL、趋势状态、波段点），不包含任何交易逻辑（加仓、止盈、Tier）。这样以后改算法不会连带改变各routine的交易规则。

**算法**：ZigZag + ATR自适应反转阈值
```
reversal_pct = clamp(ATR_20d / price × 1.5, 0.03, 0.10)
```
用 high/low（不是close）找波段极值；用最新一根已收盘bar的ATR算一次阈值（不逐点重算，保证同一段历史可稳定复现）。

**固定枚举**（`current_state` 和 `last_transition` 统一用这套，不留大小写歧义）：
```
HH_CONFIRMED / HL_CONFIRMED / LH_CONFIRMED / LL_CONFIRMED / INSUFFICIENT_DATA
```

**独立的 trend_state 枚举**（综合最近一高一低判断）：
```
BULLISH（HH+HL）/ BEARISH（LH+LL）/ TRANSITIONAL（只破一边）/ UNKNOWN（数据不足）
```

**输出结构**：
```python
{
    "current_state": "HL_CONFIRMED",
    "trend_state": "BULLISH",
    "last_swing_high": {"date":..., "price":..., "kind":"high", "label":"HH"},
    "last_swing_low": {...},
    "previous_swing_high": {...},
    "previous_swing_low": {...},
    "last_transition": "HL_CONFIRMED",
    "reversal_threshold_used": 0.045,
    "sequence": [...]  # 最近20个波段点
}
```

**关键规则**：调用方必须自己剔除当前未收盘的bar再传入——盘中实时低点/高点绝不能被当作已确认的HL/LH。这是修复INFQ误判的核心。

已用合成数据验证跑通，无报错。边界测试（上涨回调、下跌反弹、V型反转、假突破、横盘、连续HH-HL、连续LH-LL共7组）确认：连续多波段场景分类完全正确；单次"顶-底-顶"这类只有1个高点+1个低点的短窗口场景会返回`INSUFFICIENT_DATA`——这是设计上正确的行为（HH/HL/LH/LL定义要求至少2个同类型点才能比较），不是bug，但意味着**实盘接入时历史窗口不能太短**：波动率不高的票如果只给3-4个月数据，可能长期停在`INSUFFICIENT_DATA`。建议给至少6-12个月日线数据，保证有足够完整波段可比较。

---

## 二、INFQ 回调加仓 routine 接入规则

```
current_state == "HL_CONFIRMED" and trend_state != "BEARISH"
    → 允许进入 ≥1/3 加仓信号评估

trend_state == "TRANSITIONAL" and current_state == "LH_CONFIRMED"
    → 仅标记 WATCHING，不允许产生 ≥1/3 加仓建议

trend_state == "BEARISH"
    → 禁止 ≥1/3 加仓建议
```
按顺序判断，命中即停止往下看。盘中低点只作为原始价格数据喂给 `compute_swing_structure`，不再直接等同于Higher Low——这条替换掉原来"单日盘中低点比较"的逻辑。

其余原有规则不变：门槛1/3判断、Higher Low/站回MA5/放量三项打星、`market_state`大盘过滤、红K线场景下的谨慎处理，都在这套结构判断之上叠加，不冲突。

---

## 三、止盈 routine 接入规则

### 3.1 两条状态线，完全独立，互不修改

| | 百分比分层止盈 | 结构化 Trailing Stop |
|---|---|---|
| 状态字段 | `executed_tier` | `trailing_stop_price`、`trailing_stop_triggered` |
| 驱动信号 | 浮盈% + 日线RSI（config.yaml阈值） | swing_structure 的 LH_CONFIRMED / 收盘价对比 |
| Tier 3 (`LL_CONFIRMED`) | 直接触发原有 Tier 3 逻辑（跳过其他条件） | — |

### 3.2 Trailing Stop 精确定义（事件驱动，非每次运行重算）

**事件必须有唯一ID，否则同一个LH会被反复"处理"。** 用swing high自身的日期+价格+kind做身份，**不用sequence_index**——index是当前一次计算结果里的位置，以后swing_structure的sequence长度调整、算法优化、历史数据补齐，都可能让同一个swing的index改变，用它做身份不稳定：
```
lh_event_id = f"{swing_high.date}|{swing_high.price}|high"
```
sequence_index可以额外记录做审计参考，但不作为身份判断的必要部分。state.json记录 `last_processed_lh_event`。只有当本次算出的 `lh_event_id` 与记录的不同，才继续往下走candidate计算；相同则跳过，不重新算。

**ATR锁定的值必须真正写进state.json**（不能只是文字上说"冻结"，代码/routine逻辑里没有落地）：新增字段 `atr_at_event`，记录这次事件确认时用的ATR_20d数值，且只在该事件首次被处理时取一次、写入state冻结——之后即使ATR逐日变化，也不会让同一个LH事件的trailing stop继续上移，上移只能来自**新的**LH_CONFIRMED事件。这样避免"LH没变、ATR自己涨、trailing stop却跟着悄悄上调"的隐式漂移，以后审计run_log时也能直接回答"这个trailing stop当时为什么是这个数"，不用回溯重算。

```
本次运行 current_state == "LH_CONFIRMED"
    ↓
lh_event_id = swing_high.date + swing_high.price + "high"
    ↓
lh_event_id != state.last_processed_lh_event ?
    ↓ YES（真正的新事件，不是同一个LH的重复读取）
atr_at_event = 最新已收盘日线 ATR_20d（只取这一次，冻结）
candidate = max(last_swing_low.price, last_swing_high.price − 2.0 × atr_at_event)
trailing_stop_price = max(old_trailing_stop_price, candidate)   # 只能上调
state.last_processed_lh_event = lh_event_id
state.atr_at_event = atr_at_event
    ↓
写入 state.json + run_log，不发 Telegram（记账动作，非可执行事件）
```

```
每次运行独立检查：
    收盘价 < trailing_stop_price  AND  trailing_stop_triggered == false
        → 发送 Telegram（"跌破移动止损，建议保护利润"）
        → trailing_stop_triggered = true（同一次跌破不重复提醒）
```

ATR倍数 `N=2.0` 放 config.yaml 可调。

### 3.3 state.json 完整结构

```json
{
  "NVDA": {
    "current_stage": "TIER_1_TRIGGERED",
    "executed_tier": 1,
    "last_triggered_at": "2026-08-13T14:00:00ET",
    "rsi_peak": 74.2,
    "highest_price_since_buy": 135.5,
    "trailing_stop_price": 128.40,
    "trailing_stop_triggered": false,
    "last_processed_lh_event": "2026-08-13|135.50|high",
    "atr_at_event": 2.73,
    "last_known_shares": 100,
    "last_known_avg_cost": 118.5,
    "position_active": true
  }
}
```
`last_known_shares` / `last_known_avg_cost` 是上一轮读到的positions.yaml快照，用来判断这次变化是"减仓"（shares↓、avg_cost不变）还是"新买入/摊薄"（avg_cost变了）——不能只看shares变化本身，必须两个字段一起对比，否则routine（尤其是没有独立脚本、靠LLM每次解读规则跑的情况下）容易把两种情况搞混。

### 3.4 重置规则（两条状态线一起清空）

触发场景（任一满足即重置）：
- 现价收盘价 < avg_cost
- `positions.yaml` 检测到该ticker新买入或 avg_cost 变动（加仓/摊薄）

重置动作：`executed_tier=0`、`current_stage=IDLE`、**同时** `trailing_stop_price=null`、`trailing_stop_triggered=false`——防止新一轮建仓继承上一轮的trailing stop。

**防错铁律（不变）**：单纯减仓（shares↓，avg_cost不变）绝不触发以上任何重置。

---

## 四、其余部分（继承v1，未变动）

- **执行层**：Claude Code Routines（非GitHub Actions）。Environment存 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` 环境变量+网络白名单（`api.telegram.org`+行情数据源域名）。分支 `claude/takeprofit-monitor-state`，默认只能推 `claude/` 前缀分支。
- **触发**：自定义cron，最小间隔1小时，只在ET开市时段+工作日，如 `30 13-19 * * 1-5`（注意夏令时切换需手动调UTC偏移）；部署前先确认plan每日routine运行上限够不够6-7次/天。
- **数据来源**：moomoo无API，`positions.yaml`人工维护（ticker/shares/avg_cost/buy_date），减仓后手动改文件（Plan B，未来可选升级Telegram双向指令）；价格/技术面数据走独立公开数据源，与券商账户解耦。
- **执行节奏**：每日开盘前算一次日线RSI/MA/ATR/`next_earnings_date`存daily_cache；hourly只比对实时价+做Tier3辅助的hourly RSI>80极值检测。
- **大盘过滤器**：复用 `claude/ymag-paper-state` 分支已有的 `market_trend`/`mag7_breadth`，不重新实现。
- **财报避险**：财报前3天内触发的信号，Telegram追加 `[⚠️ 财报即将来临]`，减仓门槛降一档。
- **分层止盈默认阈值**（config.yaml，支持逐票override）：Tier1 +15%/RSI65，Tier2 +30%/RSI70，Tier3 +50%/RSI75；NVDA类高波动票override为20%/40%/70%。
- **Telegram**：`telegram_bot.py` 已完成（env var版，安全），token已在BotFather重新生成，GitHub secrets已改名为 `TELEGRAM_CHAT_ID`。

---

## 五、执行顺序（每次运行严格按此顺序，不可乱序）

```
1. 读取 positions.yaml，与 state.json 里的 last_known_shares/last_known_avg_cost 对比
2. 判断是否重置：avg_cost变化 → 重置 executed_tier/trailing_stop_price/
   trailing_stop_triggered/last_processed_lh_event；单纯shares减少 → 不重置
3. current_state == "LL_CONFIRMED" → 直接触发 Tier 3（跳过Tier1/2判断），发送Telegram
4. 否则按 Tier 1/2 的浮盈%+日线RSI条件判断（config.yaml阈值），命中才发Telegram
5. 检查 current_state == "LH_CONFIRMED" 且 lh_event_id 是新的 → 更新trailing_stop_price
   （第三节3.2的事件绑定逻辑），只写state+log，不发Telegram
6. 检查 收盘价 < trailing_stop_price 且 trailing_stop_triggered==false → 发送Telegram，
   标记triggered=true（这一步与第3/4步独立，即使本次已经因Tier3/Tier1/2发过一次提醒，
   trailing stop被击穿依然要单独提醒——这是两条状态线互不干扰的体现）
7. 以上都未命中 → 只记录本次原始数据到run_log，不发送任何Telegram
```
第3步（Tier3/LL_CONFIRMED）必须排在第5/6步（trailing stop更新与击穿检测）前面判断，避免同一次运行里trailing stop分支"截获"了本该属于Tier3的信号而漏发。

---

## 六、部署清单

- [x] `telegram_bot.py`（env var版）
- [x] `swing_structure.py`（已测试，main分支lib/下）
- [ ] `positions.yaml`
- [ ] `config.yaml`（含分层阈值 + trailing stop的N=2.0 + override）
- [ ] `state.json` 初始结构（含trailing_stop字段）
- [ ] `daily_cache.json` 初始结构
- [ ] INFQ routine：接入swing_structure判断规则（第二节）
- [ ] 止盈routine：接入Tier3+trailing stop规则（第三节）
- [ ] Claude Routine本体：Environment + cron trigger + prompt
