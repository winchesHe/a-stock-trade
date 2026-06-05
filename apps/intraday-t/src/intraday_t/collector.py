from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .baidu_ws import stream_snapshots
from .models import parse_codes
from .storage import RawSnapshotWriter

APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = APP_ROOT / "data"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="采集百度财经 WebSocket A 股实时快照")
    parser.add_argument("--codes", required=True, help="股票代码，多个用逗号分隔，例如 002463,600941")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="数据根目录，默认 apps/intraday-t/data")
    parser.add_argument("--day", default=None, help="交易日目录，默认使用本地日期 YYYY-MM-DD")
    parser.add_argument("--timeout", type=float, default=30.0, help="接收超时时间，单位秒")
    parser.add_argument("--once", action="store_true", help="每只股票收到第一条有效快照后退出")
    return parser


async def run(args: argparse.Namespace) -> int:
    codes = parse_codes(args.codes)
    writer = RawSnapshotWriter(Path(args.data_dir), args.day)
    seen: set[str] = set()

    try:
        async for snapshot in stream_snapshots(codes, timeout=args.timeout):
            path = writer.write(snapshot)
            print(f"{snapshot.ts} {snapshot.code} {snapshot.name or ''} {snapshot.price} -> {path}")
            seen.add(snapshot.code)
            if args.once and seen == set(codes):
                return 0
    except asyncio.TimeoutError:
        missing = sorted(set(codes) - seen)
        if missing:
            print(f"超时未收到快照: {','.join(missing)}")
        return 1
    except KeyboardInterrupt:
        print("已停止采集")
        return 130
    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
