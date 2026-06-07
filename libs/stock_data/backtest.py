"""Basic signal backtest helpers for saved stock data assets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .collector import collect_stock_snapshot
from .paths import normalize_code
from .store import load_daily_bars


def backtest_signal(
    code: str,
    signal_date: str,
    *,
    holding_days: int = 5,
    refresh: bool = False,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Backtest buying next tradable open after ``signal_date`` and holding N bars."""
    code = normalize_code(code)
    _ensure_backtest_data(code, signal_date, refresh, data_dir)
    raw = load_daily_bars(code, adjustment="raw", data_dir=data_dir).sort_values("trade_date").reset_index(drop=True)
    signal_idx = raw.index[raw["trade_date"] <= signal_date]
    if len(signal_idx) == 0:
        return _empty_result(code, signal_date, "信号日前无日线数据")

    entry_idx = int(signal_idx[-1]) + 1
    if entry_idx >= len(raw):
        return _empty_result(code, signal_date, "信号日后无可买入日线")

    entry = raw.iloc[entry_idx]
    if bool(entry.get("is_suspended", False)) or not bool(entry.get("is_tradable", True)):
        return _empty_result(code, signal_date, "买入日不可交易")
    if bool(entry.get("is_limit_up", False)):
        return _empty_result(code, signal_date, "买入日涨停，按无法买入处理")

    exit_idx = min(entry_idx + holding_days - 1, len(raw) - 1)
    window = raw.iloc[entry_idx : exit_idx + 1].copy()
    exit_row = window.iloc[-1]
    entry_price = float(entry["open"])
    exit_price = float(exit_row["close"])
    max_drawdown = _max_drawdown_pct(window, entry_price)
    return_pct = (exit_price / entry_price - 1) * 100
    return {
        "code": code,
        "signal_date": signal_date,
        "entry_date": entry["trade_date"],
        "entry_price": entry_price,
        "exit_date": exit_row["trade_date"],
        "exit_price": exit_price,
        "holding_days": len(window),
        "return_pct": return_pct,
        "max_drawdown_pct": max_drawdown,
        "blocked": False,
        "block_reason": "",
    }


def _max_drawdown_pct(window: pd.DataFrame, entry_price: float) -> float:
    equity = window["close"].astype(float) / entry_price
    running_max = equity.cummax()
    drawdown = (equity / running_max - 1) * 100
    intraday_entry_drawdown = (window["low"].astype(float).min() / entry_price - 1) * 100
    return float(min(drawdown.min(), intraday_entry_drawdown))


def _ensure_backtest_data(code: str, signal_date: str, refresh: bool, data_dir: str | Path | None) -> None:
    from .paths import symbol_data_dir

    raw_path = symbol_data_dir(code, data_dir) / "daily_raw.csv"
    if refresh or not raw_path.exists():
        collect_stock_snapshot(code, signal_date, refresh=refresh, data_dir=data_dir)


def _empty_result(code: str, signal_date: str, reason: str) -> dict[str, Any]:
    return {
        "code": code,
        "signal_date": signal_date,
        "entry_date": None,
        "entry_price": None,
        "exit_date": None,
        "exit_price": None,
        "holding_days": 0,
        "return_pct": None,
        "max_drawdown_pct": None,
        "blocked": True,
        "block_reason": reason,
    }
