"""
Phase 1 - Technical Engine
Computes Trend Score + RS Score + ATR% from raw daily OHLCV bars.
Input: per-symbol list of daily bars (dicts with begins_at, close_price, high_price, low_price, volume)
Output: per-symbol feature dict, appended to data/features/features_daily.csv
"""
import pandas as pd


def bars_to_df(bars):
    df = pd.DataFrame(bars)
    df["date"] = pd.to_datetime(df["begins_at"])
    for col in ["open_price", "close_price", "high_price", "low_price"]:
        df[col] = df[col].astype(float)
    df["volume"] = df["volume"].astype(float)
    return df.sort_values("date").reset_index(drop=True)


def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def atr(df, period=14):
    high, low, close = df["high_price"], df["low_price"], df["close_price"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def trend_score(df):
    """0-100. Price>EMA50>EMA150>EMA200 + EMA200 slope + proximity to 52w high."""
    close = df["close_price"]
    e50, e150, e200 = ema(close, 50), ema(close, 150), ema(close, 200)
    price = df["close_price"].iloc[-1]
    score = 0
    if price > e50.iloc[-1]:
        score += 20
    if e50.iloc[-1] > e150.iloc[-1]:
        score += 20
    if e150.iloc[-1] > e200.iloc[-1]:
        score += 20
    if len(e200.dropna()) > 10 and e200.iloc[-1] > e200.iloc[-10]:
        score += 20
    wk52_high = df["high_price"].tail(252).max()
    if wk52_high > 0 and price >= wk52_high * 0.90:
        score += 20
    return score, {
        "price": price, "ema50": e50.iloc[-1], "ema150": e150.iloc[-1],
        "ema200": e200.iloc[-1], "pct_of_52w_high": price / wk52_high if wk52_high else None,
    }


def relative_return(df, spy_df, days):
    if len(df) <= days or len(spy_df) <= days:
        return None
    stock_ret = df["close_price"].iloc[-1] / df["close_price"].iloc[-days] - 1
    spy_ret = spy_df["close_price"].iloc[-1] / spy_df["close_price"].iloc[-days] - 1
    return stock_ret - spy_ret


def rs_score(df, spy_df):
    """0-100 via a squashed blend of 3M/6M/12M relative return vs SPY (0.4/0.3/0.3)."""
    r3 = relative_return(df, spy_df, 63)
    r6 = relative_return(df, spy_df, 126)
    r12 = relative_return(df, spy_df, 252)
    parts = [(r, w) for r, w in [(r3, 0.4), (r6, 0.3), (r12, 0.3)] if r is not None]
    if not parts:
        return None, {}
    total_w = sum(w for _, w in parts)
    blended = sum(r * w for r, w in parts) / total_w
    score = max(0, min(100, 50 + blended * 100))
    return score, {"rel_ret_3m": r3, "rel_ret_6m": r6, "rel_ret_12m": r12}


def extension_metrics(df, lookback_days=252, exclude_recent=20):
    """
    Placeholder for the real Pivot (which the Cup/Handle detector will supply later).
    Approximates the 'base high' as the highest close BEFORE the most recent
    `exclude_recent` trading days, then measures:
      - extension_pct: how far above that base_high price currently sits
      - weeks_since_break: how long ago price first closed above base_high
    This is deliberately crude — it exists only to stop the ranking engine from
    surfacing stocks that have already run, until Cup detection lands and can
    supply a real Pivot price.
    """
    closes = df["close_price"]
    window = closes.tail(lookback_days)
    if len(window) <= exclude_recent + 5:
        return {"base_high": None, "extension_pct": None, "weeks_since_break": None, "stage": "insufficient_data"}

    pre_window = window.iloc[:-exclude_recent]
    base_high = pre_window.max()
    price = closes.iloc[-1]
    extension_pct = price / base_high - 1 if base_high else None

    # find first day (within the excluded/most-recent window) price closed above base_high
    recent = window.iloc[-exclude_recent:]
    breakout_days = recent[recent > base_high]
    if len(breakout_days) > 0:
        days_since_break = exclude_recent - recent.index.get_loc(breakout_days.index[0])
    elif extension_pct is not None and extension_pct > 0:
        # BUGFIX (found running this against ~87 real tickers): price is currently
        # above base_high but didn't break out within the recent window -- that can
        # only mean the breakout happened further back than `exclude_recent` days
        # ago. The old code searched `window[window > base_high]`, which is
        # mathematically empty by construction (base_high IS pre_window's max), so
        # it always returned None here and these names were mislabeled
        # 'insufficient_data' instead of 'extended'. Since we can't see far enough
        # back to date it exactly, treat it as clearly beyond the fresh-breakout
        # window rather than reporting unknown.
        days_since_break = exclude_recent + 1
    else:
        days_since_break = None

    weeks_since_break = round(days_since_break / 5, 1) if days_since_break is not None else None
    return {
        "base_high": round(base_high, 2) if base_high else None,
        "extension_pct": round(extension_pct * 100, 2) if extension_pct is not None else None,
        "weeks_since_break": weeks_since_break,
    }


def classify_stage(price, ema50, extension_pct, weeks_since_break,
                    stage2_max_pct=10.0, stage2_max_weeks=4.0, extended_max_pct=20.0):
    """
    Hard classification gate, NOT part of the weighted Bottom Score.
    Runs BEFORE ranking -- a stock in 'extended' or 'weakening' should not
    reach the Top 20 regardless of how high its Trend/RS/Cup/VCP scores are.
    """
    if price is None or ema50 is None or extension_pct is None:
        return "insufficient_data"
    if price < ema50:
        return "weakening"          # broke its own trend -- exclude regardless of score
    if extension_pct <= 0:
        return "base"               # still inside/below the prior base -- watchlist, not yet actionable
    # weeks_since_break only matters once extension_pct > 0 (i.e. there IS a breakout to date)
    if weeks_since_break is None:
        return "insufficient_data"
    if extension_pct <= stage2_max_pct and weeks_since_break <= stage2_max_weeks:
        return "early_breakout"     # the actual target zone for Top 20
    if extension_pct > extended_max_pct or weeks_since_break > stage2_max_weeks * 2:
        return "extended"           # already ran -- exclude from Top 20, log separately
    return "watch"                  # borderline, neither fresh nor clearly extended


def weeks_in_base(df, lookback_weeks=30):
    """
    Weekly-timeframe view of how long a stock has been basing.
    Resamples to weekly closes, finds the low point within the lookback window,
    and returns how many weeks have passed since that low WITHOUT it being
    undercut since -- i.e. how long price has held above its own recent bottom.
    This is the direct measure for '底部震荡2-3個月以上'.
    """
    weekly = df.set_index("date")["close_price"].resample("W").last().dropna()
    window = weekly.tail(lookback_weeks)
    if len(window) < 6:
        return {"weeks_in_base": None, "base_low": None, "base_low_undercut_since": None}

    min_idx = window.idxmin()
    base_low = window.loc[min_idx]
    since_low = window.loc[min_idx:]
    undercut_since = (since_low.iloc[1:] < base_low).any() if len(since_low) > 1 else False
    weeks_since_low = len(window.loc[min_idx:]) - 1
    return {
        "weeks_in_base": weeks_since_low,
        "base_low": round(base_low, 2),
        "base_low_undercut_since": bool(undercut_since),
    }


def bottoming_signal(df, deep_pullback_pct=-20.0, stabilize_window=20, recent_window=5, atr_lookback=20):
    """
    Rough proxy for '黄金坑' / deep weekly-timeframe base: a stock that has
    pulled back hard from its prior high, but has STOPPED making new lows and
    whose volatility is contracting -- i.e. the decline looks like it's
    settling into a base rather than still falling.
    This is deliberately crude (no real Cup/VCP yet) -- it exists only to
    separate 'still falling' from 'deep pullback that may be basing'.
    """
    closes = df["close_price"]
    lows = df["low_price"]
    if len(df) < stabilize_window + recent_window + atr_lookback:
        return {"bottoming": False, "is_making_new_lows": None, "atr_trend": None}

    recent_low = lows.tail(recent_window).min()
    prior_low = lows.tail(stabilize_window + recent_window).iloc[:-recent_window].min()
    is_making_new_lows = recent_low < prior_low  # still digging -> not yet a base

    atr_series = atr(df)
    atr_recent = atr_series.tail(atr_lookback).mean()
    atr_prior = atr_series.tail(atr_lookback * 2).iloc[:-atr_lookback].mean()
    atr_contracting = atr_recent < atr_prior if pd.notna(atr_prior) else None

    bottoming = (not is_making_new_lows) and bool(atr_contracting)
    base_info = weeks_in_base(df)
    bottoming = bottoming and not base_info["base_low_undercut_since"] and \
        (base_info["weeks_in_base"] is not None and base_info["weeks_in_base"] >= 8)
    return {
        "bottoming": bottoming, "is_making_new_lows": is_making_new_lows,
        "atr_contracting": atr_contracting, **base_info,
    }


def volume_dry_up_ratio(df, short=20, long=60):
    """<1.0 means recent volume is drying up relative to the longer baseline."""
    vol = df["volume"]
    if len(vol) < long:
        return None
    return round(vol.tail(short).mean() / vol.tail(long).mean(), 3)


def rs_improving(df, spy_df, short_days=30, baseline_days=180):
    """
    Catches 'sellers have exhausted, buyers are stepping back in' even while the
    longer RS Score (used in rs_score()) is still weak/lagging -- this is the
    direct fix for the NXPI problem (RS Rating only turns up long after the base
    is already over). Returns the short-window relative return and whether it's
    meaningfully better than the longer baseline.
    """
    r_short = relative_return(df, spy_df, short_days)
    r_baseline = relative_return(df, spy_df, baseline_days)
    if r_short is None or r_baseline is None:
        return {"rel_ret_30d": None, "rs_improving": None}
    return {"rel_ret_30d": round(r_short * 100, 2), "rs_improving": r_short > r_baseline and r_short > 0}


def classify_phase(price, ema20, ema20_slope_positive, is_making_new_lows, atr_contracting,
                    vol_dry_up_ratio, rs_improving_flag):
    """
    Phase tag, NOT a weighted score -- deliberately kept as explicit flags rather
    than a single number until there's backtest evidence for how to weight them.
    Falling -> Stabilizing -> Accumulating -> Breaking Out (breakout itself is
    already covered by classify_stage's 'early_breakout').
    NOTE: Second Test (double-bottom) detection is intentionally NOT implemented
    here. It requires the same swing-high/low peak-detection machinery as the
    Cup/Handle detector, which was already deferred to last in the build order
    specifically to limit overfitting risk -- adding an ad hoc, un-backtested
    'L2 within 5% of L1' rule now would reintroduce that exact risk early.
    """
    signals = {
        "no_new_low": is_making_new_lows is False,
        "atr_contracting": bool(atr_contracting),
        "volume_dry_up": (vol_dry_up_ratio is not None and vol_dry_up_ratio < 0.7),
        "rs_improving": bool(rs_improving_flag),
        "above_ema20": (price is not None and ema20 is not None and price > ema20),
        "ema20_rising": bool(ema20_slope_positive),
    }
    if is_making_new_lows:
        phase = "falling"
    elif signals["above_ema20"] and signals["ema20_rising"]:
        phase = "accumulating"
    elif signals["atr_contracting"] or signals["volume_dry_up"]:
        phase = "stabilizing"
    else:
        phase = "falling"
    return phase, signals


def compute_features(symbol, bars, spy_bars):
    df, spy_df = bars_to_df(bars), bars_to_df(spy_bars)
    t_score, t_detail = trend_score(df)
    r_score, r_detail = rs_score(df, spy_df)
    atr14 = atr(df).iloc[-1]
    atr_pct = atr14 / df["close_price"].iloc[-1]
    ext_detail = extension_metrics(df)
    bottom_detail = bottoming_signal(df)
    e20 = ema(df["close_price"], 20)
    ema20_now = e20.iloc[-1]
    ema20_slope_positive = len(e20.dropna()) > 5 and e20.iloc[-1] > e20.iloc[-5]
    vdu = volume_dry_up_ratio(df)
    rs_imp = rs_improving(df, spy_df)

    stage = classify_stage(
        price=t_detail["price"], ema50=t_detail["ema50"],
        extension_pct=ext_detail["extension_pct"], weeks_since_break=ext_detail["weeks_since_break"],
    )
    # Tightened per real-world feedback: a "weakening" name only counts as a genuine
    # deep-base candidate if ALL of these hold -- not making new lows, ATR contracting
    # and weeks_in_base intact (from bottoming_signal), a deep enough pullback
    # (>=30%, not just >=20%), AND volume has actually dried up (<0.7). Without the
    # volume-dry-up requirement this bucket let through names (e.g. AVGO at -23%,
    # ratio 0.92) that were still "probing" rather than genuinely stabilized -- the
    # extra gate is what separates those from a name like NOW that passes all four.
    if stage == "weakening" and bottom_detail["bottoming"] and ext_detail.get("extension_pct") is not None \
            and ext_detail["extension_pct"] <= -30.0 and vdu is not None and vdu < 0.7:
        stage = "deep_base_watch"

    phase, phase_signals = classify_phase(
        price=t_detail["price"], ema20=ema20_now, ema20_slope_positive=ema20_slope_positive,
        is_making_new_lows=bottom_detail.get("is_making_new_lows"),
        atr_contracting=bottom_detail.get("atr_contracting"),
        vol_dry_up_ratio=vdu, rs_improving_flag=rs_imp.get("rs_improving"),
    )

    row = {
        "ticker": symbol,
        "date": df["date"].iloc[-1].strftime("%Y-%m-%d"),
        "trend_score": t_score,
        "rs_score": round(r_score, 1) if r_score is not None else None,
        "atr_pct": round(atr_pct * 100, 2),
        "stage": stage,
        "phase": phase,
        "vol_dry_up_ratio": vdu,
    }
    for k, v in {**t_detail, **r_detail, **ext_detail, **bottom_detail, **rs_imp, **phase_signals}.items():
        row[k] = round(v, 4) if isinstance(v, float) else v
    return row
