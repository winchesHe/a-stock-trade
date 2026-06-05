from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .collector import DEFAULT_DATA_DIR
from .models import MinuteBar, Signal, normalize_code, parse_codes
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


def _is_opening_risk(minute: str, opening_minutes: int) -> bool:
    hhmm = minute[11:16]
    if not hhmm.startswith("09:"):
        return False
    return int(hhmm[-2:]) < 30 + opening_minutes


def _is_trading_session(minute: str) -> bool:
    hhmm = minute[11:16]
    return "09:30" <= hhmm <= "11:30" or "13:00" <= hhmm <= "15:00"


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


def evaluate_bars(bars: list[MinuteBar], *, has_position: bool = True, opening_minutes: int = 5) -> list[Signal]:
    return [evaluate_bar(bar, has_position=has_position, opening_minutes=opening_minutes) for bar in bars]


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
