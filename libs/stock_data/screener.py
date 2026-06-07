"""Stock screening helpers built on repository-local stock data assets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .collector import collect_stock_snapshot
from .paths import normalize_code, symbol_data_dir
from .store import load_daily_bars, load_events


DEFAULT_SCREEN_RULES = {
    "require_tradable": True,
    "exclude_st": True,
    "exclude_limit_down": True,
    "above_ma": [5, 10, 20],
    "min_return_5d": 0,
    "min_drawdown_20d": -15,
    "min_volume_ratio_20d": 1.2,
    "use_events": True,
}

SCREEN_RESULT_COLUMNS = [
    "code",
    "trade_date",
    "close",
    "ma5",
    "ma10",
    "ma20",
    "return_5d",
    "drawdown_20d",
    "volume_ratio_20d",
    "is_limit_down",
    "is_st",
    "dragon_tiger_count_30d",
    "score",
    "reasons",
]


def screen_stocks(
    codes: list[str],
    trade_date: str,
    *,
    rules: dict[str, Any] | None = None,
    refresh: bool = False,
    data_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Screen stocks using saved bars/features/events.

    Missing local data is collected on demand through ``collect_stock_snapshot``.
    """
    active_rules = {**DEFAULT_SCREEN_RULES, **(rules or {})}
    rows = []
    for raw_code in codes:
        code = normalize_code(raw_code)
        _ensure_screen_data(code, trade_date, refresh, data_dir)
        candidate = _screen_one(code, trade_date, active_rules, data_dir)
        if candidate:
            rows.append(candidate)
    if not rows:
        return pd.DataFrame(columns=SCREEN_RESULT_COLUMNS)
    return pd.DataFrame(rows).reindex(columns=SCREEN_RESULT_COLUMNS).sort_values("score", ascending=False).reset_index(drop=True)


def _screen_one(code: str, trade_date: str, rules: dict[str, Any], data_dir: str | Path | None) -> dict[str, Any] | None:
    raw = load_daily_bars(code, adjustment="raw", data_dir=data_dir)
    features = _load_features(code, data_dir)
    raw_row = _row_on_or_before(raw, trade_date)
    feature_row = _row_on_or_before(features, trade_date)
    if raw_row is None or feature_row is None:
        return None

    reject_reasons = []
    pass_reasons = []
    close = _num(raw_row.get("close"))

    if rules.get("require_tradable") and not bool(raw_row.get("is_tradable", True)):
        reject_reasons.append("不可交易")
    if rules.get("exclude_st") and bool(raw_row.get("is_st", False)):
        reject_reasons.append("ST")
    if rules.get("exclude_limit_down") and bool(raw_row.get("is_limit_down", False)):
        reject_reasons.append("跌停")

    for window in rules.get("above_ma", []):
        ma_value = _num(feature_row.get(f"ma{window}"))
        if pd.isna(ma_value) or pd.isna(close) or close <= ma_value:
            reject_reasons.append(f"未站上 MA{window}")
        else:
            pass_reasons.append(f"站上 MA{window}")

    return_5d = _num(feature_row.get("return_5d"))
    if not pd.isna(return_5d) and return_5d > rules.get("min_return_5d", 0):
        pass_reasons.append("5日收益为正")
    else:
        reject_reasons.append("5日收益不足")

    drawdown_20d = _num(feature_row.get("drawdown_20d"))
    if not pd.isna(drawdown_20d) and drawdown_20d > rules.get("min_drawdown_20d", -15):
        pass_reasons.append("20日回撤可控")
    else:
        reject_reasons.append("20日回撤过大或不足")

    volume_ratio_20d = _num(feature_row.get("volume_ratio_20d"))
    if not pd.isna(volume_ratio_20d) and volume_ratio_20d > rules.get("min_volume_ratio_20d", 1.2):
        pass_reasons.append("放量")
    else:
        reject_reasons.append("未放量")

    if reject_reasons:
        return None

    dragon_count = _count_recent_events(code, "dragon_tiger", trade_date, data_dir, days=30) if rules.get("use_events", True) else 0
    score = len(pass_reasons) + dragon_count
    if dragon_count:
        pass_reasons.append(f"近30日龙虎榜 {dragon_count} 次")

    return {
        "code": code,
        "trade_date": trade_date,
        "close": close,
        "ma5": _num(feature_row.get("ma5")),
        "ma10": _num(feature_row.get("ma10")),
        "ma20": _num(feature_row.get("ma20")),
        "return_5d": return_5d,
        "drawdown_20d": drawdown_20d,
        "volume_ratio_20d": volume_ratio_20d,
        "is_limit_down": bool(raw_row.get("is_limit_down", False)),
        "is_st": bool(raw_row.get("is_st", False)),
        "dragon_tiger_count_30d": dragon_count,
        "score": score,
        "reasons": "; ".join(pass_reasons),
    }


def _load_features(code: str, data_dir: str | Path | None) -> pd.DataFrame:
    return pd.read_csv(symbol_data_dir(code, data_dir) / "features.csv", dtype={"code": str, "trade_date": str})


def _ensure_screen_data(code: str, trade_date: str, refresh: bool, data_dir: str | Path | None) -> None:
    symbol_dir = symbol_data_dir(code, data_dir)
    required = [symbol_dir / "daily_raw.csv", symbol_dir / "features.csv"]
    if refresh or not all(path.exists() for path in required):
        collect_stock_snapshot(code, trade_date, refresh=refresh, data_dir=data_dir)


def _row_on_or_before(frame: pd.DataFrame, trade_date: str) -> pd.Series | None:
    if frame.empty or "trade_date" not in frame:
        return None
    eligible = frame[frame["trade_date"] <= trade_date].sort_values("trade_date")
    if eligible.empty:
        return None
    return eligible.iloc[-1]


def _count_recent_events(code: str, event_type: str, trade_date: str, data_dir: str | Path | None, *, days: int) -> int:
    start = pd.to_datetime(trade_date) - pd.Timedelta(days=days)
    end = pd.to_datetime(trade_date)
    count = 0
    for event in load_events(code, event_type=event_type, data_dir=data_dir):
        event_date = pd.to_datetime(event.get("effective_date"), errors="coerce")
        if pd.notna(event_date) and start <= event_date <= end:
            count += 1
    return count


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")
