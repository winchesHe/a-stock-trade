from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

from .aggregate import aggregate_code
from .collector import DEFAULT_DATA_DIR
from .models import Signal, parse_codes
from .signals import generate_signals_for_code
from .storage import signal_path


def _fmt_price(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"


def format_signal(signal: Signal) -> str:
    """Format one signal as a compact terminal line."""
    reason = "；".join(signal.reasons) if signal.reasons else "无理由"
    stop = signal.stop_condition or "无"
    reference = f"VWAP {_fmt_price(signal.reference_price)}"
    context_parts = [item for item in (signal.strategy, signal.regime, signal.position_state) if item]
    context = f" [{'/'.join(context_parts)}]" if context_parts else ""
    return (
        f"{signal.ts} {signal.code} {signal.signal}{context} 强度{signal.strength} "
        f"价{_fmt_price(signal.price)} / {reference} | {signal.action} | "
        f"原因：{reason} | 失效：{stop}"
    )


def _empty_signal_line(code: str, path: Path) -> str:
    return f"{datetime.now().isoformat(timespec='seconds')} {code} no_signal | 暂无信号数据 | 文件：{path}"


def run_once(
    base_dir: Path,
    codes: list[str],
    day: str | None,
    *,
    has_position: bool = True,
    opening_minutes: int = 5,
) -> list[str]:
    lines: list[str] = []
    for code in codes:
        aggregate_code(base_dir, code, day)
        path, signals = generate_signals_for_code(
            base_dir,
            code,
            day,
            has_position=has_position,
            opening_minutes=opening_minutes,
        )
        if signals:
            lines.append(format_signal(signals[-1]))
        else:
            lines.append(_empty_signal_line(code, path or signal_path(base_dir, code, day)))
    return lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="循环刷新并在终端展示做 T 最新信号")
    parser.add_argument("--codes", required=True, help="股票代码，多个用逗号分隔，例如 605589,601208")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="数据根目录，默认 apps/intraday-t/data")
    parser.add_argument("--day", default=None, help="交易日目录，默认使用本地日期 YYYY-MM-DD")
    parser.add_argument("--interval", type=float, default=20.0, help="刷新间隔秒数，默认 20")
    parser.add_argument("--once", action="store_true", help="只刷新并展示一次")
    parser.add_argument("--no-position", action="store_true", help="标记为无底仓，只输出禁止交易信号")
    parser.add_argument("--opening-minutes", type=int, default=5, help="开盘后禁止交易分钟数，默认 5")
    return parser


def run(args: argparse.Namespace) -> int:
    codes = parse_codes(args.codes)
    base_dir = Path(args.data_dir)
    has_position = not args.no_position

    while True:
        print(f"---- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ----", flush=True)
        for line in run_once(
            base_dir,
            codes,
            args.day,
            has_position=has_position,
            opening_minutes=args.opening_minutes,
        ):
            print(line, flush=True)
        if args.once:
            return 0
        time.sleep(args.interval)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
