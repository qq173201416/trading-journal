"""
swing_structure.py
========================================
共享结构分析模块（只放在 main 分支的 lib/ 下，各项目分支运行时借用）:

    git show main:lib/swing_structure.py > swing_structure.py

用 ZigZag 算法 + ATR 自适应反转阈值，标记波段高低点，并把每个新确认的
swing point 相对上一个同类型的点分类为 HH / HL / LH / LL。

本模块只负责"市场结构是什么"，不做任何交易判断——LH要不要收紧止损、
LL要不要触发Tier3，这些由各个routine自己根据结构结果决定。
"""

from dataclasses import dataclass
from typing import Optional, Literal
import numpy as np
import pandas as pd

SwingType = Literal["HH", "HL", "LH", "LL"]


@dataclass
class SwingPoint:
    index: int
    date: pd.Timestamp
    price: float
    kind: Literal["high", "low"]
    label: Optional[SwingType] = None


def _wilder_atr(df: pd.DataFrame, period: int = 20) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _reversal_threshold(
    df: pd.DataFrame,
    atr_period: int,
    atr_multiplier: float,
    min_reversal_pct: float,
    max_reversal_pct: float,
) -> float:
    """
    单一动态阈值：用序列末尾最新的 ATR/价格 算一次，clamp 在 [min, max]。
    简化版——不逐点用当时的ATR重算，避免同一段历史在不同时间点跑出不同
    结果（不利于 state.json 的稳定复现）。以后要做逐点自适应，需要额外
    把"阈值本身"也做成 state 持久化，现在先不做。
    """
    atr = _wilder_atr(df, atr_period)
    latest_atr = atr.iloc[-1]
    latest_price = df["close"].iloc[-1]
    if pd.isna(latest_atr) or latest_price <= 0:
        return min_reversal_pct
    raw_pct = (latest_atr / latest_price) * atr_multiplier
    return float(np.clip(raw_pct, min_reversal_pct, max_reversal_pct))


def _run_zigzag(df: pd.DataFrame, reversal_pct: float) -> list[SwingPoint]:
    """
    标准ZigZag：跟踪当前方向上的极值点，价格从极值反向运动超过
    reversal_pct，才"确认"上一个极值点为swing point，并翻转方向。
    用 high/low（不是close）找极值，更贴近真实波段高低点。
    """
    highs, lows = df["high"].to_numpy(), df["low"].to_numpy()
    dates = df.index

    swings: list[SwingPoint] = []
    direction: Optional[str] = None
    last_pivot_idx = 0
    last_pivot_price = highs[0]

    for i in range(1, len(df)):
        if direction is None:
            if highs[i] >= last_pivot_price * (1 + reversal_pct):
                direction = "up"
                last_pivot_idx = int(np.argmin(lows[: i + 1]))
                last_pivot_price = lows[last_pivot_idx]
            elif lows[i] <= last_pivot_price * (1 - reversal_pct):
                direction = "down"
                last_pivot_idx = int(np.argmax(highs[: i + 1]))
                last_pivot_price = highs[last_pivot_idx]
            continue

        if direction == "up":
            if highs[i] > last_pivot_price:
                last_pivot_price, last_pivot_idx = highs[i], i
            elif lows[i] <= last_pivot_price * (1 - reversal_pct):
                swings.append(SwingPoint(last_pivot_idx, dates[last_pivot_idx], last_pivot_price, "high"))
                direction = "down"
                last_pivot_price, last_pivot_idx = lows[i], i
        else:
            if lows[i] < last_pivot_price:
                last_pivot_price, last_pivot_idx = lows[i], i
            elif highs[i] >= last_pivot_price * (1 + reversal_pct):
                swings.append(SwingPoint(last_pivot_idx, dates[last_pivot_idx], last_pivot_price, "low"))
                direction = "up"
                last_pivot_price, last_pivot_idx = highs[i], i

    return swings


def _classify(swings: list[SwingPoint]) -> None:
    last_high: Optional[SwingPoint] = None
    last_low: Optional[SwingPoint] = None
    for sp in swings:
        if sp.kind == "high":
            if last_high is not None:
                sp.label = "HH" if sp.price > last_high.price else "LH"
            last_high = sp
        else:
            if last_low is not None:
                sp.label = "HL" if sp.price > last_low.price else "LL"
            last_low = sp


def compute_swing_structure(
    ohlc_df: pd.DataFrame,
    atr_period: int = 20,
    atr_multiplier: float = 1.5,
    min_reversal_pct: float = 0.03,
    max_reversal_pct: float = 0.10,
) -> dict:
    """
    ohlc_df: 必须包含 ['high','low','close'] 列，按时间正序排列。
    调用方必须自己先剔除当前未走完的那一根bar——本模块不做这个判断，
    只处理传进来的数据（这正是修 INFQ 那次bug的关键：把"今天盘中低点"
    传进来 != Higher Low，只有ZigZag真正完成一次反转、确认新的swing low
    之后，对应的label才会是"HL"）。

    返回值只描述结构事实，不含交易建议。
    """
    if len(ohlc_df) < atr_period + 5:
        return {
            "current_state": "INSUFFICIENT_DATA",
            "trend_state": "UNKNOWN",
            "last_swing_high": None,
            "last_swing_low": None,
            "previous_swing_high": None,
            "previous_swing_low": None,
            "last_transition": None,
            "reversal_threshold_used": None,
            "sequence": [],
        }

    threshold = _reversal_threshold(ohlc_df, atr_period, atr_multiplier, min_reversal_pct, max_reversal_pct)
    swings = _run_zigzag(ohlc_df, threshold)
    _classify(swings)

    highs = [s for s in swings if s.kind == "high" and s.label is not None]
    lows = [s for s in swings if s.kind == "low" and s.label is not None]
    last_high = highs[-1] if highs else None
    last_low = lows[-1] if lows else None
    prev_high = highs[-2] if len(highs) >= 2 else None
    prev_low = lows[-2] if len(lows) >= 2 else None

    # 固定枚举，current_state 和 last_transition 用同一套命名，不留给调用方猜大小写:
    #   HH_CONFIRMED / HL_CONFIRMED / LH_CONFIRMED / LL_CONFIRMED / INSUFFICIENT_DATA
    labeled = [s for s in swings if s.label is not None]
    last_transition = f"{labeled[-1].label}_CONFIRMED" if labeled else "INSUFFICIENT_DATA"
    current_state = last_transition  # current_state 就是"最近一次被确认的swing分类"，不再另外发明复合命名

    # trend_state 是独立的一套枚举（综合最近一高一低判断整体趋势），不与 current_state 混用
    if last_high and last_low:
        if last_high.label == "HH" and last_low.label == "HL":
            trend_state = "BULLISH"
        elif last_high.label == "LH" and last_low.label == "LL":
            trend_state = "BEARISH"
        else:
            trend_state = "TRANSITIONAL"  # 例如只出现LH但低点还没破，或反之
    else:
        trend_state = "UNKNOWN"

    def _sp(sp: Optional[SwingPoint]) -> Optional[dict]:
        return None if sp is None else {"date": str(sp.date), "price": sp.price, "kind": sp.kind, "label": sp.label}

    return {
        "current_state": current_state,
        "trend_state": trend_state,
        "last_swing_high": _sp(last_high),
        "last_swing_low": _sp(last_low),
        "previous_swing_high": _sp(prev_high),
        "previous_swing_low": _sp(prev_low),
        "last_transition": last_transition,
        "reversal_threshold_used": threshold,
        "sequence": [_sp(s) for s in swings[-20:]],
    }


def _make_ohlc(closes: np.ndarray, noise: float = 0.4, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    high = closes + rng.uniform(0.1, noise, len(closes))
    low = closes - rng.uniform(0.1, noise, len(closes))
    dates = pd.date_range("2026-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({"high": high, "low": low, "close": closes}, index=dates)


def _run_case(name: str, closes: np.ndarray) -> None:
    df = _make_ohlc(closes)
    result = compute_swing_structure(df, min_reversal_pct=0.03, max_reversal_pct=0.10)
    labels = [s["label"] for s in result["sequence"] if s and s["label"]]
    print(f"\n=== {name} ===")
    print("current_state:", result["current_state"], "| trend_state:", result["trend_state"])
    print("label sequence:", labels)


if __name__ == "__main__":
    n = 100
    x = np.arange(n)

    # 1. 上涨 -> 回调 -> 再上涨（应看到 HH/HL 为主）
    _run_case("上涨-回调-再上涨", np.concatenate([
        100 + x[:40] * 0.5,
        100 + 40 * 0.5 - (x[:15] * 0.3),
        100 + 40 * 0.5 - 15 * 0.3 + x[:45] * 0.5,
    ]))

    # 2. 下跌 -> 反弹 -> 再下跌（应看到 LH/LL 为主）
    _run_case("下跌-反弹-再下跌", np.concatenate([
        140 - x[:40] * 0.5,
        140 - 40 * 0.5 + x[:15] * 0.3,
        140 - 40 * 0.5 + 15 * 0.3 - x[:45] * 0.5,
    ]))

    # 3. 横盘（波动幅度小于min_reversal_pct，应几乎不产生swing，或INSUFFICIENT_DATA）
    _run_case("横盘", 100 + np.sin(x / 5) * 1.0)

    # 4. V型反转（先大跌再大涨）
    _run_case("V型反转", np.concatenate([
        120 - x[:50] * 0.8,
        120 - 50 * 0.8 + x[:50] * 0.8,
    ]))

    # 5. 假突破（先上涨、短暂新高后迅速跌回，不应误判为稳定HH+HL延续）
    _run_case("假突破", np.concatenate([
        100 + x[:30] * 0.5,
        [115, 118, 108, 104, 102],
        100 + x[:65] * 0.5 - 20,
    ]))

    # 6. 连续 HH/HL（健康上升趋势，多个波段）
    wave = np.tile(np.concatenate([np.linspace(0, 8, 10), np.linspace(8, 3, 10)]), 5)
    _run_case("连续HH-HL", 100 + np.cumsum(np.diff(wave, prepend=0)) + x * 0.3)

    # 7. 连续 LH/LL（健康下降趋势，多个波段）
    _run_case("连续LH-LL", 140 - (100 + np.cumsum(np.diff(wave, prepend=0)) + x * 0.3 - 100))

    print("\n全部用例跑完，检查：current_state应等于sequence最后一个非空label+'_CONFIRMED'，"
          "且横盘/数据不足场景应返回INSUFFICIENT_DATA或很短的sequence，不应崩溃或输出None。")
