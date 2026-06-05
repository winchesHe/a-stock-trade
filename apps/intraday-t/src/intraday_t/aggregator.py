from __future__ import annotations

import argparse
from pathlib import Path

from .aggregate import aggregate_code
from .collector import DEFAULT_DATA_DIR
from .models import parse_codes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="将 raw JSONL 聚合为 1 分钟分时数据")
    parser.add_argument("--codes", required=True, help="股票代码，多个用逗号分隔，例如 002463,600941")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="数据根目录，默认 apps/intraday-t/data")
    parser.add_argument("--day", default=None, help="交易日目录，默认使用本地日期 YYYY-MM-DD")
    return parser


def run(args: argparse.Namespace) -> int:
    codes = parse_codes(args.codes)
    for code in codes:
        path, bars = aggregate_code(Path(args.data_dir), code, args.day)
        print(f"{code} 生成 {len(bars)} 条 1m 数据 -> {path}")
    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
