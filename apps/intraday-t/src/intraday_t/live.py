from __future__ import annotations

import argparse
import asyncio
import contextlib
from datetime import datetime
from pathlib import Path

from .baidu_ws import stream_snapshots
from .collector import DEFAULT_DATA_DIR
from .models import Snapshot, parse_codes
from .monitor import run_once
from .storage import RawSnapshotWriter


def _fmt_price(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"


def _fmt_snapshot(snapshot: Snapshot) -> str:
    ratio = "N/A" if snapshot.ratio is None else f"{snapshot.ratio:.2f}%"
    return (
        f"{snapshot.code} 最新{_fmt_price(snapshot.price)} "
        f"VWAP{_fmt_price(snapshot.avg_price)} 涨跌{ratio} "
        f"@{snapshot.ts[11:19]}"
    )


def format_collection_summary(
    codes: list[str],
    counts: dict[str, int],
    latest: dict[str, Snapshot],
) -> str:
    parts: list[str] = []
    for code in codes:
        snapshot = latest.get(code)
        if snapshot is None:
            parts.append(f"{code} 等待快照")
            continue
        parts.append(f"{code} {counts.get(code, 0)}条 {_fmt_snapshot(snapshot).split(' ', 1)[1]}")
    return "采集：" + " | ".join(parts)


async def _collect_loop(
    codes: list[str],
    writer: RawSnapshotWriter,
    timeout: float,
    counts: dict[str, int],
    latest: dict[str, Snapshot],
    *,
    show_snapshots: bool = False,
) -> None:
    async for snapshot in stream_snapshots(codes, timeout=timeout):
        path = writer.write(snapshot)
        counts[snapshot.code] = counts.get(snapshot.code, 0) + 1
        latest[snapshot.code] = snapshot
        if show_snapshots:
            print(f"{snapshot.ts} {_fmt_snapshot(snapshot)} -> {path}", flush=True)


async def _run_live(args: argparse.Namespace) -> int:
    codes = parse_codes(args.codes)
    base_dir = Path(args.data_dir)
    writer = RawSnapshotWriter(base_dir, args.day)
    counts: dict[str, int] = {}
    latest: dict[str, Snapshot] = {}
    has_position = not args.no_position

    collector_task = asyncio.create_task(
        _collect_loop(
            codes,
            writer,
            args.timeout,
            counts,
            latest,
            show_snapshots=args.show_snapshots,
        )
    )

    try:
        print("实时采集 + 信号展示已启动，按 Ctrl+C 停止。", flush=True)
        if args.warmup > 0:
            await asyncio.sleep(args.warmup)

        while True:
            if collector_task.done():
                with contextlib.suppress(asyncio.CancelledError):
                    exc = collector_task.exception()
                    if exc is not None:
                        print(f"采集已停止：{exc}", flush=True)
                        return 1
                print("采集已停止。", flush=True)
                return 0

            print(f"---- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ----", flush=True)
            print(format_collection_summary(codes, counts, latest), flush=True)
            lines = await asyncio.to_thread(
                run_once,
                base_dir,
                codes,
                args.day,
                has_position=has_position,
                opening_minutes=args.opening_minutes,
            )
            for line in lines:
                print(line, flush=True)

            if args.once:
                return 0
            await asyncio.sleep(args.interval)
    finally:
        collector_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await collector_task


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="一个终端内同时采集实时快照并展示做 T 信号")
    parser.add_argument("--codes", required=True, help="股票代码，多个用逗号分隔，例如 605589,601208")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="数据根目录，默认 apps/intraday-t/data")
    parser.add_argument("--day", default=None, help="交易日目录，默认使用本地日期 YYYY-MM-DD")
    parser.add_argument("--interval", type=float, default=20.0, help="信号刷新间隔秒数，默认 20")
    parser.add_argument("--timeout", type=float, default=600.0, help="WebSocket 接收超时时间，默认 600 秒")
    parser.add_argument("--warmup", type=float, default=3.0, help="启动后等待采集首批快照的秒数，默认 3")
    parser.add_argument("--once", action="store_true", help="采集预热后只展示一次信号")
    parser.add_argument("--show-snapshots", action="store_true", help="打印每条实时快照")
    parser.add_argument("--no-position", action="store_true", help="标记为无底仓，只输出禁止交易信号")
    parser.add_argument("--opening-minutes", type=int, default=5, help="开盘后禁止交易分钟数，默认 5")
    return parser


def run(args: argparse.Namespace) -> int:
    try:
        return asyncio.run(_run_live(args))
    except KeyboardInterrupt:
        print("已停止实时采集和信号展示")
        return 130


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
