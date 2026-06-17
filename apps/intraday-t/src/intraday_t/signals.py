from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .collector import DEFAULT_DATA_DIR
from .models import IntradayContext, MinuteBar, PositionContext, Signal, normalize_code, parse_codes
from .storage import SignalWriter, minute_bar_path, read_jsonl


def minute_bar_from_dict(payload: dict[str, Any]) -> MinuteBar:
    return MinuteBar(
        minute=str(payload["minute"]),
        code=normalize_code(str(payload["code"])),
        open=float(payload["open"]),
        high=float(payload["high"]),
        low=float(payload["low"]),
        close=float(payload["close"]),
        vwap=payload.get("vwap"),
        amount_delta=payload.get("amount_delta"),
        volume_delta=payload.get("volume_delta"),
        turnover_ratio=payload.get("turnover_ratio"),
        price_vs_vwap_pct=payload.get("price_vs_vwap_pct"),
        price_vs_open_pct=payload.get("price_vs_open_pct"),
        price_vs_pre_close_pct=payload.get("price_vs_pre_close_pct"),
        day_high_so_far=payload.get("day_high_so_far"),
        day_low_so_far=payload.get("day_low_so_far"),
    )


def _strength(value: float | None, base: int = 50) -> int:
    if value is None:
        return base
    return max(1, min(100, int(base + abs(value) * 10)))


def position_context_from_flags(*, has_position: bool = True) -> PositionContext:
    return PositionContext(has_base_position=has_position)


def position_state(position: PositionContext) -> str:
    if not position.has_base_position:
        return "no_base_position"
    if position.opened_side == "sold":
        return "sold_waiting_cover"
    if position.opened_side == "bought":
        return "bought_waiting_sell"
    return "base_available"


def _is_opening_risk(minute: str, opening_minutes: int) -> bool:
    hhmm = minute[11:16]
    if not hhmm.startswith("09:"):
        return False
    return int(hhmm[-2:]) < 30 + opening_minutes


def _is_trading_session(minute: str) -> bool:
    hhmm = minute[11:16]
    return "09:30" <= hhmm <= "11:30" or "13:00" <= hhmm <= "15:00"


def _minute_of_day(minute: str) -> int | None:
    try:
        hh = int(minute[11:13])
        mm = int(minute[14:16])
    except (ValueError, IndexError):
        return None
    return hh * 60 + mm


def _minutes_since_open(minute: str) -> int | None:
    value = _minute_of_day(minute)
    if value is None:
        return None
    start = 9 * 60 + 30
    return value - start if value >= start else None


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _bar_deviation(bar: MinuteBar) -> float | None:
    if bar.price_vs_vwap_pct is not None:
        return float(bar.price_vs_vwap_pct)
    if bar.vwap in (None, 0):
        return None
    return (bar.close - bar.vwap) / bar.vwap * 100


def _volume_is_weaker(current: MinuteBar, reference: MinuteBar) -> bool:
    if current.amount_delta is None or reference.amount_delta is None:
        return True
    return current.amount_delta <= reference.amount_delta * 1.05


def _context_signal(
    *,
    bar: MinuteBar,
    signal: str,
    strength: int,
    action: str,
    position: PositionContext,
    context: IntradayContext | None = None,
    strategy: str | None = None,
    stop_condition: str | None = None,
    reasons: list[str] | None = None,
    risk_flags: list[str] | None = None,
    reference_price: float | None = None,
) -> Signal:
    return Signal(
        ts=bar.minute,
        code=bar.code,
        signal=signal,
        strength=strength,
        action=action,
        position_required=True,
        price=bar.close,
        reference_price=reference_price if reference_price is not None else bar.vwap,
        stop_condition=stop_condition,
        reasons=reasons or [],
        risk_flags=(risk_flags or []) + (context.risk_flags if context else []),
        strategy=strategy,
        regime=context.regime if context else None,
        position_state=position_state(position),
    )


def classify_intraday_context(
    bars: list[MinuteBar],
    *,
    opening_range_minutes: int = 30,
    lookback: int = 5,
) -> IntradayContext:
    if not bars:
        return IntradayContext(regime="unknown", confidence=0, reasons=["缺少分钟数据"], risk_flags=["数据缺失"])

    latest = bars[-1]
    recent = bars[-lookback:]
    deviations = [value for value in (_bar_deviation(bar) for bar in recent) if value is not None]
    above_ratio = 0.0
    below_ratio = 0.0
    comparable = [bar for bar in recent if bar.vwap not in (None, 0)]
    if comparable:
        above_ratio = sum(1 for bar in comparable if bar.close >= (bar.vwap or 0)) / len(comparable)
        below_ratio = sum(1 for bar in comparable if bar.close <= (bar.vwap or 0)) / len(comparable)

    recent_high = max(bar.high for bar in recent)
    recent_low = min(bar.low for bar in recent)
    avg_abs_deviation = _avg([abs(value) for value in deviations]) or 0.0
    latest_deviation = _bar_deviation(latest) or 0.0
    latest_vs_pre_close = latest.price_vs_pre_close_pct or 0.0
    latest_vs_open = latest.price_vs_open_pct or 0.0

    opening_bars = [
        bar
        for bar in bars
        if (minutes := _minutes_since_open(bar.minute)) is not None and 0 <= minutes < opening_range_minutes
    ]
    open_range_high = max((bar.high for bar in opening_bars), default=None)
    open_range_low = min((bar.low for bar in opening_bars), default=None)
    post_opening = [
        bar
        for bar in bars
        if (minutes := _minutes_since_open(bar.minute)) is not None and minutes >= opening_range_minutes
    ]

    if open_range_high is not None and post_opening:
        ever_breakout = any(bar.high >= open_range_high * 1.003 for bar in post_opening)
        if ever_breakout and (latest.close <= open_range_high or (latest.vwap is not None and latest.close < latest.vwap)):
            return IntradayContext(
                regime="opening_failed_breakout",
                confidence=75,
                open_range_high=open_range_high,
                open_range_low=open_range_low,
                recent_high=recent_high,
                recent_low=recent_low,
                reasons=["开盘区间突破失败", "价格跌回开盘区间或 VWAP 下方"],
            )
        if latest.close >= open_range_high * 1.003 and latest.vwap is not None and latest.close > latest.vwap:
            return IntradayContext(
                regime="opening_breakout",
                confidence=72,
                open_range_high=open_range_high,
                open_range_low=open_range_low,
                recent_high=recent_high,
                recent_low=recent_low,
                reasons=["价格突破开盘区间高点", "站在 VWAP 上方"],
            )

    day_low = latest.day_low_so_far if latest.day_low_so_far is not None else min(bar.low for bar in bars)
    if (
        len(bars) >= 5
        and day_low is not None
        and latest.close >= day_low * 1.008
        and min(bar.low for bar in bars[:-1]) <= day_low * 1.002
        and latest_vs_pre_close <= -1.0
    ):
        return IntradayContext(
            regime="panic_reversal",
            confidence=70,
            open_range_high=open_range_high,
            open_range_low=open_range_low,
            recent_high=recent_high,
            recent_low=recent_low,
            reasons=["日内低点后出现修复", "价格仍处于昨收下方"],
        )

    if above_ratio >= 0.7 and latest_deviation >= 0.3 and (latest_vs_pre_close > 0 or latest_vs_open > 0):
        return IntradayContext(
            regime="strong_trend",
            confidence=68,
            open_range_high=open_range_high,
            open_range_low=open_range_low,
            recent_high=recent_high,
            recent_low=recent_low,
            reasons=["近端多数时间在 VWAP 上方", "价格相对开盘或昨收偏强"],
        )

    if below_ratio >= 0.7 and latest_deviation <= -0.3 and (latest_vs_pre_close < 0 or latest_vs_open < 0):
        return IntradayContext(
            regime="weak_trend",
            confidence=68,
            open_range_high=open_range_high,
            open_range_low=open_range_low,
            recent_high=recent_high,
            recent_low=recent_low,
            reasons=["近端多数时间在 VWAP 下方", "价格相对开盘或昨收偏弱"],
        )

    if avg_abs_deviation <= 0.45:
        return IntradayContext(
            regime="range_bound",
            confidence=62,
            open_range_high=open_range_high,
            open_range_low=open_range_low,
            recent_high=recent_high,
            recent_low=recent_low,
            reasons=["VWAP 上下偏离较小", "分时处于震荡区间"],
        )

    return IntradayContext(
        regime="range_bound",
        confidence=50,
        open_range_high=open_range_high,
        open_range_low=open_range_low,
        recent_high=recent_high,
        recent_low=recent_low,
        reasons=["暂未形成明确趋势结构"],
    )


def evaluate_bar(
    bar: MinuteBar,
    *,
    has_position: bool = True,
    opening_minutes: int = 5,
    high_sell_threshold: float = 1.2,
    low_buy_threshold: float = -1.2,
    watch_threshold: float = 0.6,
) -> Signal:
    reasons: list[str] = []
    risk_flags: list[str] = []

    if not has_position:
        return Signal(
            ts=bar.minute,
            code=bar.code,
            signal="forbidden",
            strength=100,
            action="无底仓，禁止做 T 建议",
            position_required=True,
            price=bar.close,
            reference_price=bar.vwap,
            stop_condition="确认有可卖底仓后再评估做 T 信号",
            reasons=["A 股普通账户做 T 必须基于已有底仓"],
            risk_flags=["无底仓"],
        )

    if not _is_trading_session(bar.minute):
        return Signal(
            ts=bar.minute,
            code=bar.code,
            signal="forbidden",
            strength=90,
            action="非交易时段，禁止交易",
            position_required=True,
            price=bar.close,
            reference_price=bar.vwap,
            stop_condition="进入 A 股连续竞价时段后再评估",
            reasons=["当前时间不在 09:30-11:30 或 13:00-15:00"],
            risk_flags=["非交易时段"],
        )

    if bar.vwap is None or bar.price_vs_vwap_pct is None:
        return Signal(
            ts=bar.minute,
            code=bar.code,
            signal="forbidden",
            strength=90,
            action="数据不足，禁止交易",
            position_required=True,
            price=bar.close,
            reference_price=bar.vwap,
            stop_condition="等待 VWAP 和成交数据恢复",
            reasons=["缺少 VWAP 或 VWAP 偏离率，无法判断价格位置"],
            risk_flags=["数据缺失"],
        )

    if _is_opening_risk(bar.minute, opening_minutes):
        return Signal(
            ts=bar.minute,
            code=bar.code,
            signal="forbidden",
            strength=80,
            action="开盘前几分钟波动大，先观察",
            position_required=True,
            price=bar.close,
            reference_price=bar.vwap,
            stop_condition="开盘风险窗口结束后再评估",
            reasons=[f"开盘后前 {opening_minutes} 分钟不输出交易建议"],
            risk_flags=["开盘波动"],
        )

    deviation = bar.price_vs_vwap_pct
    if deviation >= high_sell_threshold:
        reasons.append(f"价格高于 VWAP {deviation:.2f}%")
        if bar.day_high_so_far is not None and bar.close >= bar.day_high_so_far * 0.995:
            reasons.append("价格接近日内高点")
        return Signal(
            ts=bar.minute,
            code=bar.code,
            signal="high_sell",
            strength=_strength(deviation, 60),
            action="高抛部分底仓",
            position_required=True,
            price=bar.close,
            reference_price=bar.vwap,
            stop_condition="放量继续突破日内高点则取消高抛信号",
            reasons=reasons,
            risk_flags=risk_flags,
        )

    if deviation <= low_buy_threshold:
        reasons.append(f"价格低于 VWAP {abs(deviation):.2f}%")
        if bar.day_low_so_far is not None and bar.close <= bar.day_low_so_far * 1.005:
            reasons.append("价格接近日内低点")
        return Signal(
            ts=bar.minute,
            code=bar.code,
            signal="low_buy",
            strength=_strength(deviation, 60),
            action="低吸计划 T 仓",
            position_required=True,
            price=bar.close,
            reference_price=bar.vwap,
            stop_condition="放量跌破日内低点则取消低吸信号",
            reasons=reasons,
            risk_flags=risk_flags,
        )

    if abs(deviation) >= watch_threshold:
        direction = "高于" if deviation > 0 else "低于"
        return Signal(
            ts=bar.minute,
            code=bar.code,
            signal="watch",
            strength=_strength(deviation, 45),
            action="接近阈值，继续观察",
            position_required=True,
            price=bar.close,
            reference_price=bar.vwap,
            stop_condition="偏离扩大到交易阈值或回归 VWAP",
            reasons=[f"价格{direction} VWAP {abs(deviation):.2f}%"],
            risk_flags=risk_flags,
        )

    return Signal(
        ts=bar.minute,
        code=bar.code,
        signal="hold",
        strength=30,
        action="持有观望",
        position_required=True,
        price=bar.close,
        reference_price=bar.vwap,
        stop_condition="等待 VWAP 偏离或日内位置变化",
        reasons=[f"VWAP 偏离 {deviation:.2f}% 未达到观察阈值"],
        risk_flags=risk_flags,
    )


def _evaluate_open_t_leg(bar: MinuteBar, position: PositionContext, context: IntradayContext) -> Signal | None:
    state = position_state(position)
    if state == "sold_waiting_cover" and position.opened_price is not None:
        profit_pct = (position.opened_price - bar.close) / position.opened_price * 100
        if profit_pct >= 0.6:
            return _context_signal(
                bar=bar,
                signal="cover_back",
                strength=_strength(profit_pct, 62),
                action="回补已高抛 T 仓",
                position=position,
                context=context,
                strategy="cover_back_after_sell",
                stop_condition="价格重新站回高抛价附近则放弃回补等待",
                reasons=[f"较高抛价回落 {profit_pct:.2f}%", "倒 T 出现回补价差"],
            )
        return _context_signal(
            bar=bar,
            signal="watch",
            strength=_strength(profit_pct, 45),
            action="已高抛，等待回补机会",
            position=position,
            context=context,
            strategy="sold_waiting_cover",
            stop_condition="回落价差不足，不追高回补",
            reasons=[f"当前较高抛价回落 {profit_pct:.2f}%"],
        )

    if state == "bought_waiting_sell" and position.opened_price is not None:
        profit_pct = (bar.close - position.opened_price) / position.opened_price * 100
        if profit_pct >= 0.6:
            return _context_signal(
                bar=bar,
                signal="high_sell",
                strength=_strength(profit_pct, 62),
                action="卖出等量已有底仓完成正 T",
                position=position,
                context=context,
                strategy="sell_after_low_buy",
                stop_condition="价格跌回低吸价附近则暂停卖出",
                reasons=[f"较低吸价上涨 {profit_pct:.2f}%", "正 T 出现卖出价差"],
            )
        return _context_signal(
            bar=bar,
            signal="watch",
            strength=_strength(profit_pct, 45),
            action="已低吸，等待卖出机会",
            position=position,
            context=context,
            strategy="bought_waiting_sell",
            stop_condition="上涨价差不足，不急于卖出底仓",
            reasons=[f"当前较低吸价上涨 {profit_pct:.2f}%"],
        )

    return None


def _failed_second_high_sell(bars: list[MinuteBar], position: PositionContext, context: IntradayContext) -> Signal | None:
    if len(bars) < 6:
        return None

    latest = bars[-1]
    candidate_indexes = range(max(0, len(bars) - 5), len(bars))
    for second_high_index in sorted(candidate_indexes, key=lambda index: bars[index].high, reverse=True):
        second_high_bar = bars[second_high_index]
        prior_bars = bars[:second_high_index]
        if not prior_bars:
            continue

        prior_high_index = max(range(len(prior_bars)), key=lambda index: bars[index].high)
        prior_high_bar = bars[prior_high_index]
        pullback_bars = bars[prior_high_index + 1 : second_high_index]
        if prior_high_bar.high <= 0 or not pullback_bars:
            continue

        pullback_low = min(bar.low for bar in pullback_bars)
        near_prior_high = prior_high_bar.high * 0.995 <= second_high_bar.high <= prior_high_bar.high * 1.002
        pulled_back = pullback_low <= prior_high_bar.high * 0.992
        rebounded = second_high_bar.high >= pullback_low * 1.004
        rolled_over = latest.close <= second_high_bar.high * 0.996
        still_extended = latest.vwap is None or latest.close >= latest.vwap * 1.005
        weaker_volume = _volume_is_weaker(second_high_bar, prior_high_bar)
        if not (near_prior_high and pulled_back and rebounded and rolled_over and still_extended and weaker_volume):
            continue

        distance = (prior_high_bar.high - latest.close) / prior_high_bar.high * 100
        return _context_signal(
            bar=latest,
            signal="high_sell",
            strength=_strength(distance, 66),
            action="二次冲高不过，高抛部分底仓",
            position=position,
            context=context,
            strategy="failed_second_high_sell",
            stop_condition="放量突破前高并站稳则取消高抛信号",
            reasons=[
                "二次冲高未突破前高",
                "前高后回踩再上冲",
                "第二次冲高量能不强",
                f"最新价较前高回落 {distance:.2f}%",
            ],
        )
    return None


def _second_low_reversal_buy(bars: list[MinuteBar], position: PositionContext, context: IntradayContext) -> Signal | None:
    if len(bars) < 6:
        return None

    latest = bars[-1]
    early = bars[:-3]
    late = bars[-3:]
    prior_low_bar = min(early, key=lambda item: item.low)
    second_low_bar = min(late, key=lambda item: item.low)
    if prior_low_bar.low <= 0:
        return None

    held_prior_low = prior_low_bar.low * 0.998 <= second_low_bar.low <= prior_low_bar.low * 1.008
    repaired = latest.close >= second_low_bar.low * 1.006
    weaker_volume = _volume_is_weaker(second_low_bar, prior_low_bar)
    if held_prior_low and repaired and weaker_volume:
        repair_pct = (latest.close - second_low_bar.low) / second_low_bar.low * 100
        return _context_signal(
            bar=latest,
            signal="low_buy",
            strength=_strength(repair_pct, 64),
            action="二次下探不破，低吸计划 T 仓",
            position=position,
            context=context,
            strategy="second_low_reversal_buy",
            stop_condition="放量跌破二次低点则取消低吸信号",
            reasons=[
                "二次下探未破前低",
                "第二次下探量能不强",
                f"低点后修复 {repair_pct:.2f}%",
            ],
        )
    return None


def _vwap_pullback_low_buy(bars: list[MinuteBar], position: PositionContext, context: IntradayContext) -> Signal | None:
    if len(bars) < 5 or context.regime not in {"strong_trend", "opening_breakout"}:
        return None

    latest = bars[-1]
    previous = bars[-2]
    if latest.vwap in (None, 0) or previous.vwap in (None, 0):
        return None

    previous_deviation = _bar_deviation(previous)
    latest_deviation = _bar_deviation(latest)
    if previous_deviation is None or latest_deviation is None:
        return None

    pulled_back_near_vwap = -0.35 <= previous_deviation <= 0.45 or previous.low <= (previous.vwap or 0) * 1.003
    regained_vwap = latest.close >= latest.vwap and latest_deviation >= 0.3
    not_breakdown = latest.low >= latest.vwap * 0.992
    if pulled_back_near_vwap and regained_vwap and not_breakdown:
        return _context_signal(
            bar=latest,
            signal="low_buy",
            strength=_strength(latest_deviation, 62),
            action="VWAP 回踩确认，低吸计划 T 仓",
            position=position,
            context=context,
            strategy="vwap_pullback_low_buy",
            stop_condition="放量跌破 VWAP 且无法快速收回则取消低吸信号",
            reasons=[
                "VWAP 回踩后重新站回均价线",
                "日内状态偏强",
                f"价格高于 VWAP {latest_deviation:.2f}%",
            ],
        )
    return None


def evaluate_latest_bar(
    bars: list[MinuteBar],
    *,
    position: PositionContext | None = None,
    opening_minutes: int = 5,
) -> Signal:
    if not bars:
        raise ValueError("至少需要一根分钟 K 线")

    active_position = position or PositionContext()
    latest = bars[-1]
    state = position_state(active_position)

    if state == "no_base_position":
        return _context_signal(
            bar=latest,
            signal="forbidden",
            strength=100,
            action="无底仓，禁止做 T 建议",
            position=active_position,
            stop_condition="确认有可卖底仓后再评估做 T 信号",
            reasons=["A 股普通账户做 T 必须基于已有底仓"],
            risk_flags=["无底仓"],
        )

    if not _is_trading_session(latest.minute):
        return _context_signal(
            bar=latest,
            signal="forbidden",
            strength=90,
            action="非交易时段，禁止交易",
            position=active_position,
            stop_condition="进入 A 股连续竞价时段后再评估",
            reasons=["当前时间不在 09:30-11:30 或 13:00-15:00"],
            risk_flags=["非交易时段"],
        )

    if latest.vwap is None or _bar_deviation(latest) is None:
        return _context_signal(
            bar=latest,
            signal="forbidden",
            strength=90,
            action="数据不足，禁止交易",
            position=active_position,
            stop_condition="等待 VWAP 和成交数据恢复",
            reasons=["缺少 VWAP 或 VWAP 偏离率，无法判断价格位置"],
            risk_flags=["数据缺失"],
        )

    if _is_opening_risk(latest.minute, opening_minutes):
        return _context_signal(
            bar=latest,
            signal="forbidden",
            strength=80,
            action="开盘前几分钟波动大，先观察",
            position=active_position,
            stop_condition="开盘风险窗口结束后再评估",
            reasons=[f"开盘后前 {opening_minutes} 分钟不输出交易建议"],
            risk_flags=["开盘波动"],
        )

    if len(bars) < 5 and state == "base_available":
        signal = evaluate_bar(latest, has_position=True, opening_minutes=opening_minutes)
        signal.position_state = state
        return signal

    context = classify_intraday_context(bars)
    open_leg_signal = _evaluate_open_t_leg(latest, active_position, context)
    if open_leg_signal is not None:
        return open_leg_signal

    for strategy in (
        _failed_second_high_sell,
        _second_low_reversal_buy,
        _vwap_pullback_low_buy,
    ):
        signal = strategy(bars, active_position, context)
        if signal is not None:
            return signal

    deviation = _bar_deviation(latest) or 0.0
    if abs(deviation) >= 0.6:
        direction = "高于" if deviation > 0 else "低于"
        return _context_signal(
            bar=latest,
            signal="watch",
            strength=_strength(deviation, 48),
            action="接近结构条件，继续观察",
            position=active_position,
            context=context,
            strategy="structure_watch",
            stop_condition="等待结构确认或回归 VWAP",
            reasons=[f"价格{direction} VWAP {abs(deviation):.2f}%", *context.reasons],
        )

    return _context_signal(
        bar=latest,
        signal="hold",
        strength=30,
        action="持有观望",
        position=active_position,
        context=context,
        strategy="hold_without_structure",
        stop_condition="等待 VWAP 回踩、二冲不过或二探不破结构",
        reasons=[f"VWAP 偏离 {deviation:.2f}% 未形成结构信号", *context.reasons],
    )


def evaluate_bars(bars: list[MinuteBar], *, has_position: bool = True, opening_minutes: int = 5) -> list[Signal]:
    position = position_context_from_flags(has_position=has_position)
    return [
        evaluate_latest_bar(bars[: index + 1], position=position, opening_minutes=opening_minutes)
        for index in range(len(bars))
    ]


def generate_signals_for_code(
    base_dir: Path,
    code: str,
    day: str | None = None,
    *,
    has_position: bool = True,
    opening_minutes: int = 5,
) -> tuple[Path, list[Signal]]:
    rows = read_jsonl(minute_bar_path(base_dir, code, day))
    bars = [minute_bar_from_dict(row) for row in rows]
    signals = evaluate_bars(bars, has_position=has_position, opening_minutes=opening_minutes)
    output_path = SignalWriter(base_dir, day).write_all(code, signals)
    return output_path, signals


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="基于 1 分钟数据生成做 T 基础信号")
    parser.add_argument("--codes", required=True, help="股票代码，多个用逗号分隔，例如 002463,600941")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="数据根目录，默认 apps/intraday-t/data")
    parser.add_argument("--day", default=None, help="交易日目录，默认使用本地日期 YYYY-MM-DD")
    parser.add_argument("--no-position", action="store_true", help="标记为无底仓，只输出禁止交易信号")
    parser.add_argument("--opening-minutes", type=int, default=5, help="开盘后禁止交易分钟数，默认 5")
    return parser


def run(args: argparse.Namespace) -> int:
    codes = parse_codes(args.codes)
    for code in codes:
        path, signals = generate_signals_for_code(
            Path(args.data_dir),
            code,
            args.day,
            has_position=not args.no_position,
            opening_minutes=args.opening_minutes,
        )
        print(f"{code} 生成 {len(signals)} 条信号 -> {path}")
    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
