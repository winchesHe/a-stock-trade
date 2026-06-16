"""止跌下影线 + 放量突破均线 + 右侧确认战法。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .backtest import backtest_signal
from .collector import collect_stock_snapshot
from .paths import normalize_code, stock_data_dir
from .store import load_daily_bars, write_dataframe, write_json


DEFAULT_REVERSAL_PARAMS = {
    "lookback": 120,
    "box_window": 40,
    "shadow_ratio_min": 0.45,
    "close_position_min": 0.5,
    "near_low_pct": 0.08,
    "confirm_days": 3,
    "volume_ratio_min": 1.5,
    "ma_windows": [5, 10, 20, 30],
    "right_side_days": 20,
    "right_side_ma": 60,
}

REVERSAL_RESULT_COLUMNS = [
    "code",
    "stop_fall_date",
    "signal_date",
    "signal_type",
    "stop_low",
    "signal_close",
    "volume_ratio20",
    "ma_break_count",
    "right_side_confirmed",
    "backtest_entry_date",
    "backtest_entry_price",
    "backtest_exit_date",
    "backtest_exit_price",
    "backtest_holding_days",
    "backtest_return_pct",
    "backtest_max_drawdown_pct",
    "backtest_blocked",
    "backtest_block_reason",
]


def scan_reversal_signals(
    codes: list[str] | None,
    trade_date: str,
    *,
    start_date: str | None = None,
    refresh: bool = False,
    data_dir: str | Path | None = None,
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """扫描止跌下影线后的放量突破候选。"""
    active = {**DEFAULT_REVERSAL_PARAMS, **(params or {})}
    rows = []
    errors = []
    selected_codes = [normalize_code(code) for code in codes] if codes is not None else list_local_symbols(data_dir)
    for code in selected_codes:
        try:
            if refresh or not _has_reversal_data(code, data_dir):
                collect_stock_snapshot(
                    code,
                    trade_date,
                    start_date=start_date,
                    fields=["daily_raw", "daily_qfq", "features"],
                    refresh=refresh,
                    data_dir=data_dir,
                )
            bars = load_daily_bars(code, adjustment="qfq", data_dir=data_dir)
            signal = find_reversal_signal(bars, trade_date, active)
            if signal:
                bt = backtest_signal(code, signal["signal_date"], holding_days=active["right_side_days"], data_dir=data_dir)
                rows.append({**signal, **_prefix_backtest(bt)})
        except Exception as exc:
            errors.append({"code": code, "stage": "reversal_scan", "error": str(exc)})

    result = pd.DataFrame(rows).reindex(columns=REVERSAL_RESULT_COLUMNS)
    output_dir = stock_data_dir(data_dir) / "by-date" / trade_date
    output_dir.mkdir(parents=True, exist_ok=True)
    write_dataframe(output_dir / "reversal_signals.csv", result)
    confirmed = result[(result["right_side_confirmed"] == True) & (result["backtest_blocked"] == False)] if not result.empty else result
    write_dataframe(output_dir / "reversal_confirmed.csv", confirmed.reindex(columns=REVERSAL_RESULT_COLUMNS))
    write_dataframe(output_dir / "reversal_errors.csv", pd.DataFrame(errors, columns=["code", "stage", "error"]))
    write_json(output_dir / "reversal_params.json", active)
    return result


def list_local_symbols(data_dir: str | Path | None = None) -> list[str]:
    """列出本地 `by-symbol` 下已采集的 6 位股票代码。"""
    root = stock_data_dir(data_dir) / "by-symbol"
    if not root.exists():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir() and path.name.isdigit() and len(path.name) == 6)


def _has_reversal_data(code: str, data_dir: str | Path | None) -> bool:
    symbol_dir = stock_data_dir(data_dir) / "by-symbol" / normalize_code(code)
    return (symbol_dir / "daily_raw.csv").exists() and (symbol_dir / "daily_qfq.csv").exists()


def find_reversal_signal(bars: pd.DataFrame, trade_date: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """在单股日线中寻找最近一次有效趋势反转信号。"""
    active = {**DEFAULT_REVERSAL_PARAMS, **(params or {})}
    if bars.empty:
        return None
    df = bars.copy().sort_values("trade_date").reset_index(drop=True)
    df = df[df["trade_date"] <= trade_date].tail(active["lookback"]).reset_index(drop=True)
    if len(df) < max(active["box_window"], max(active["ma_windows"])) + active["confirm_days"]:
        return None

    _add_indicators(df, active)
    candidates = []
    for idx in range(active["box_window"], len(df) - active["confirm_days"]):
        if not _is_stop_fall_bar(df, idx, active):
            continue
        confirm = _find_breakout(df, idx, active)
        if confirm is not None:
            candidates.append(_build_signal(df, idx, confirm, active))
    return candidates[-1] if candidates else None


def _add_indicators(df: pd.DataFrame, params: dict[str, Any]) -> None:
    for window in sorted(set(params["ma_windows"] + [params["right_side_ma"]])):
        df[f"ma{window}"] = df["close"].rolling(window).mean()
    df["volume_ma20"] = df["volume"].rolling(20).mean()
    df["box_low"] = df["low"].rolling(params["box_window"]).min()


def _is_stop_fall_bar(df: pd.DataFrame, idx: int, params: dict[str, Any]) -> bool:
    row = df.iloc[idx]
    day_range = row["high"] - row["low"]
    if pd.isna(day_range) or day_range <= 0:
        return False
    lower_shadow = min(row["open"], row["close"]) - row["low"]
    close_position = (row["close"] - row["low"]) / day_range
    near_box_low = row["low"] <= row["box_low"] * (1 + params["near_low_pct"])
    return (
        lower_shadow / day_range >= params["shadow_ratio_min"]
        and close_position >= params["close_position_min"]
        and bool(near_box_low)
    )


def _find_breakout(df: pd.DataFrame, stop_idx: int, params: dict[str, Any]) -> int | None:
    for idx in range(stop_idx + 1, min(stop_idx + params["confirm_days"] + 1, len(df))):
        row = df.iloc[idx]
        ma_ok = sum(row["close"] > row[f"ma{window}"] for window in params["ma_windows"] if pd.notna(row[f"ma{window}"]))
        vol_ratio = row["volume"] / row["volume_ma20"] if row["volume_ma20"] else float("nan")
        close_strong = row["close"] >= row["low"] + (row["high"] - row["low"]) * 0.65
        if ma_ok >= 3 and vol_ratio >= params["volume_ratio_min"] and close_strong:
            return idx
    return None


def _build_signal(df: pd.DataFrame, stop_idx: int, confirm_idx: int, params: dict[str, Any]) -> dict[str, Any]:
    stop = df.iloc[stop_idx]
    confirm = df.iloc[confirm_idx]
    right_window = df.iloc[confirm_idx : min(confirm_idx + params["right_side_days"], len(df))]
    right_side_confirmed = bool(
        not right_window.empty
        and right_window["close"].max() > confirm["close"]
        and right_window["close"].iloc[-1] > right_window[f"ma{params['right_side_ma']}"].iloc[-1]
        if pd.notna(right_window[f"ma{params['right_side_ma']}"].iloc[-1])
        else False
    )
    return {
        "code": str(confirm["code"]),
        "stop_fall_date": stop["trade_date"],
        "signal_date": confirm["trade_date"],
        "signal_type": "止跌下影线+放量突破均线",
        "stop_low": stop["low"],
        "signal_close": confirm["close"],
        "volume_ratio20": confirm["volume"] / confirm["volume_ma20"] if confirm["volume_ma20"] else None,
        "ma_break_count": sum(confirm["close"] > confirm[f"ma{window}"] for window in params["ma_windows"] if pd.notna(confirm[f"ma{window}"])),
        "right_side_confirmed": right_side_confirmed,
    }


def _prefix_backtest(result: dict[str, Any]) -> dict[str, Any]:
    return {f"backtest_{key}": value for key, value in result.items() if key not in {"code", "signal_date"}}
