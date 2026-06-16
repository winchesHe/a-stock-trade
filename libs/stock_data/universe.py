"""市场股票池与批量采集入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .collector import collect_stock_snapshot
from .paths import normalize_code, stock_data_dir
from .reversal import scan_reversal_signals
from .store import write_dataframe


DEFAULT_EXCLUDE_PREFIXES = ("30", "68")


def fetch_market_universe(
    *,
    exclude_prefixes: tuple[str, ...] = DEFAULT_EXCLUDE_PREFIXES,
    data_dir: str | Path | None = None,
) -> pd.DataFrame:
    """拉取 A 股股票池，并排除指定代码前缀。"""
    rows = _fetch_mootdx_universe()
    frame = pd.DataFrame(rows, columns=["code", "name", "market"])
    if frame.empty:
        return frame
    frame["code"] = frame["code"].astype(str).str.zfill(6)
    frame = frame[((frame["market"] == "sz") & frame["code"].str.startswith("00")) | ((frame["market"] == "sh") & frame["code"].str.startswith("60"))]
    frame = frame[~frame["code"].str.startswith(exclude_prefixes)]
    frame = frame.drop_duplicates("code").sort_values("code").reset_index(drop=True)
    frame["excluded_prefixes"] = ",".join(exclude_prefixes)
    path = stock_data_dir(data_dir) / "universe" / "market_universe_ex_30_68.csv"
    write_dataframe(path, frame)
    return frame


def collect_universe_daily_data(
    trade_date: str,
    *,
    start_date: str,
    codes: list[str] | None = None,
    exclude_prefixes: tuple[str, ...] = DEFAULT_EXCLUDE_PREFIXES,
    refresh: bool = False,
    limit: int | None = None,
    data_dir: str | Path | None = None,
) -> pd.DataFrame:
    """批量采集股票池半年日线数据，不拉东财事件。"""
    if codes is None:
        universe = fetch_market_universe(exclude_prefixes=exclude_prefixes, data_dir=data_dir)
        selected = universe["code"].astype(str).tolist()
    else:
        normalized = [normalize_code(code) for code in codes]
        selected = [code for code in normalized if not code.startswith(exclude_prefixes)]
    if limit is not None:
        selected = selected[:limit]

    rows: list[dict[str, Any]] = []
    for code in selected:
        try:
            snapshot = collect_stock_snapshot(
                code,
                trade_date,
                start_date=start_date,
                fields=["daily_raw", "daily_qfq", "features"],
                refresh=refresh,
                data_dir=data_dir,
            )
            rows.append({"code": code, "status": "ok", "errors": len(snapshot.get("errors", []))})
        except Exception as exc:
            rows.append({"code": code, "status": "error", "errors": 1, "error": str(exc)})

    result = pd.DataFrame(rows)
    output_dir = stock_data_dir(data_dir) / "by-date" / trade_date
    write_dataframe(output_dir / "batch_collect_results.csv", result)
    error_frame = result[result["status"] != "ok"] if not result.empty else pd.DataFrame(columns=["code", "status", "errors", "error"])
    write_dataframe(output_dir / "batch_collect_errors.csv", error_frame.reindex(columns=["code", "status", "errors", "error"]))
    return result


def run_market_reversal_scan(
    trade_date: str,
    *,
    start_date: str,
    exclude_prefixes: tuple[str, ...] = DEFAULT_EXCLUDE_PREFIXES,
    refresh: bool = False,
    limit: int | None = None,
    data_dir: str | Path | None = None,
) -> pd.DataFrame:
    """拉取排除 30/68 后的市场股票池，采集半年数据，再跑焚诀筛选回撤。"""
    universe = fetch_market_universe(exclude_prefixes=exclude_prefixes, data_dir=data_dir)
    codes = universe["code"].astype(str).tolist()
    if limit is not None:
        codes = codes[:limit]
    collect_universe_daily_data(
        trade_date,
        start_date=start_date,
        codes=codes,
        exclude_prefixes=exclude_prefixes,
        refresh=refresh,
        data_dir=data_dir,
    )
    return scan_reversal_signals(codes, trade_date, start_date=start_date, refresh=False, data_dir=data_dir)


def _fetch_mootdx_universe() -> list[dict[str, str]]:
    from mootdx.quotes import Quotes

    client = Quotes.factory(market="std")
    rows: list[dict[str, str]] = []
    for market, market_name in ((0, "sz"), (1, "sh")):
        stocks = client.stocks(market=market)
        if stocks is None or stocks.empty:
            continue
        for _, row in stocks.iterrows():
            code = str(row.get("code", "")).strip().zfill(6)
            name = str(row.get("name", "")).replace("\x00", "").strip()
            is_stock_code = (market_name == "sz" and code.startswith("00")) or (market_name == "sh" and code.startswith("60"))
            if code.isdigit() and len(code) == 6 and is_stock_code:
                rows.append({"code": code, "name": name, "market": market_name})
    return rows
