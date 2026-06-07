"""Unified stock data collection entry point."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .paths import normalize_code, snapshot_path, stock_data_dir, symbol_data_dir
from .providers import StockDataProvider, default_provider
from .schemas import DEFAULT_FIELDS, DAILY_QFQ_COLUMNS, DAILY_RAW_COLUMNS, FEATURE_COLUMNS, SCHEMA_VERSION
from .store import read_json, replace_events, write_dataframe, write_json


def collect_stock_snapshot(
    code: str,
    trade_date: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    fields: list[str] | None = None,
    refresh: bool = False,
    strict: bool = False,
    data_dir: str | Path | None = None,
    provider: StockDataProvider | None = None,
) -> dict[str, Any]:
    """Collect and persist one stock snapshot under ``data/stock-data``.

    Existing snapshots are reused unless ``refresh`` is true. External data
    failures are collected in ``errors`` unless ``strict`` is true.
    """
    code = normalize_code(code)
    end_date = end_date or trade_date
    selected_fields = fields or list(DEFAULT_FIELDS)
    snapshot_file = snapshot_path(code, trade_date, data_dir)
    if snapshot_file.exists() and not refresh:
        return read_json(snapshot_file)

    provider = provider or default_provider()
    root = stock_data_dir(data_dir)
    symbol_dir = symbol_data_dir(code, data_dir)
    symbol_dir.mkdir(parents=True, exist_ok=True)
    (symbol_dir / "snapshots").mkdir(parents=True, exist_ok=True)

    errors: list[dict[str, str]] = []
    latest: dict[str, Any] = {}
    files = {
        "daily_raw": "daily_raw.csv",
        "daily_qfq": "daily_qfq.csv",
        "features": "features.csv",
        "events": "events.jsonl",
    }

    quote = _collect_value("quote", selected_fields, errors, strict, lambda: provider.quote(code))
    if quote is not None:
        latest["quote"] = quote

    daily_raw = _collect_frame(
        "daily_raw",
        selected_fields,
        errors,
        strict,
        lambda: provider.daily_raw(code, start_date, end_date),
    )
    if daily_raw is not None:
        daily_raw = enrich_daily_raw(daily_raw, code, trade_date, quote)
        write_dataframe(symbol_dir / files["daily_raw"], daily_raw)
        latest["raw_bar"] = _latest_row(daily_raw)

    daily_qfq = _collect_frame(
        "daily_qfq",
        selected_fields,
        errors,
        strict,
        lambda: provider.daily_qfq(code, start_date, end_date),
    )
    if daily_qfq is not None:
        daily_qfq = _normalize_qfq_frame(daily_qfq, code)
        write_dataframe(symbol_dir / files["daily_qfq"], daily_qfq)
        latest["qfq_bar"] = _latest_row(daily_qfq)

    fundamentals = _collect_value(
        "fundamentals",
        selected_fields,
        errors,
        strict,
        lambda: provider.fundamentals(code),
    )
    if fundamentals is not None:
        latest["fundamentals"] = fundamentals

    if "features" in selected_fields:
        features = _build_features(daily_qfq, quote, code, trade_date)
        write_dataframe(symbol_dir / files["features"], features)
        latest["features"] = _latest_row(features)

    events = _collect_value("events", selected_fields, errors, strict, lambda: provider.events(code, trade_date))
    if events is not None:
        replace_events(symbol_dir / files["events"], events)
        latest["events_count"] = len(events)

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "code": code,
        "trade_date": trade_date,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "data_root": str(root),
        "symbol_dir": str(symbol_dir),
        "fields": selected_fields,
        "files": files,
        "latest": latest,
        "sources": _sources_from_latest(latest),
        "errors": errors,
    }
    write_json(snapshot_file, snapshot)
    _write_metadata(symbol_dir, snapshot)
    return snapshot


def _collect_frame(field: str, selected: list[str], errors: list[dict[str, str]], strict: bool, fn) -> pd.DataFrame | None:
    if field not in selected:
        return None
    try:
        return fn()
    except Exception as exc:
        _record_error(field, exc, errors, strict)
        return None


def _collect_value(field: str, selected: list[str], errors: list[dict[str, str]], strict: bool, fn):
    if field not in selected:
        return None
    try:
        return fn()
    except Exception as exc:
        _record_error(field, exc, errors, strict)
        return None


def _record_error(field: str, exc: Exception, errors: list[dict[str, str]], strict: bool) -> None:
    if strict:
        raise exc
    errors.append({"field": field, "error": str(exc)})


def _normalize_raw_frame(frame: pd.DataFrame, code: str) -> pd.DataFrame:
    frame = frame.copy()
    frame["code"] = frame.get("code", code)
    if "trade_date" not in frame and "Date" in frame:
        frame["trade_date"] = pd.to_datetime(frame["Date"]).dt.strftime("%Y-%m-%d")
    if "fetched_at" not in frame:
        frame["fetched_at"] = datetime.now().isoformat(timespec="seconds")
    if "source" not in frame:
        frame["source"] = "unknown"
    frame = frame.sort_values("trade_date") if "trade_date" in frame else frame
    if "pre_close" not in frame and "close" in frame:
        frame["pre_close"] = frame["close"].shift(1)
    if "change" not in frame and {"close", "pre_close"}.issubset(frame.columns):
        frame["change"] = frame["close"] - frame["pre_close"]
    if "change_pct" not in frame and {"change", "pre_close"}.issubset(frame.columns):
        frame["change_pct"] = frame["change"] / frame["pre_close"] * 100
    if "amplitude_pct" not in frame and {"high", "low", "pre_close"}.issubset(frame.columns):
        frame["amplitude_pct"] = (frame["high"] - frame["low"]) / frame["pre_close"] * 100
    if "board_type" not in frame:
        frame["board_type"] = _board_type(code)
    if "price_limit_pct" not in frame:
        frame["price_limit_pct"] = _price_limit_pct(code, bool(frame.get("is_st", False).any()) if "is_st" in frame else False)
    if "limit_up" not in frame and {"pre_close", "price_limit_pct"}.issubset(frame.columns):
        frame["limit_up"] = (frame["pre_close"] * (1 + frame["price_limit_pct"] / 100)).round(2)
    if "limit_down" not in frame and {"pre_close", "price_limit_pct"}.issubset(frame.columns):
        frame["limit_down"] = (frame["pre_close"] * (1 - frame["price_limit_pct"] / 100)).round(2)
    if "limit_up" in frame and "close" in frame and "is_limit_up" not in frame:
        frame["is_limit_up"] = frame["close"] >= frame["limit_up"] - 0.01
    if "limit_down" in frame and "close" in frame and "is_limit_down" not in frame:
        frame["is_limit_down"] = frame["close"] <= frame["limit_down"] + 0.01
    for column, default in {
        "is_tradable": True,
        "is_suspended": False,
        "is_st": False,
    }.items():
        if column not in frame:
            frame[column] = default
    return frame


def enrich_daily_raw(
    frame: pd.DataFrame,
    code: str,
    trade_date: str,
    quote: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Normalize and enrich raw daily bars for backtest-safe use.

    Real-time quote fields are applied only when ``quote_date == trade_date``.
    Historical rows keep their original/derived values to avoid look-ahead bias.
    """
    enriched = _normalize_raw_frame(frame, code)
    quote = quote or {}
    if quote.get("quote_date") == trade_date and "trade_date" in enriched:
        mask = enriched["trade_date"] == trade_date
        if mask.any():
            _set_from_quote(enriched, mask, "name", quote.get("name"))
            _set_from_quote(enriched, mask, "turnover_rate_pct", quote.get("turnover_rate_pct"))
            _set_from_quote(enriched, mask, "limit_up", quote.get("limit_up"))
            _set_from_quote(enriched, mask, "limit_down", quote.get("limit_down"))
            _set_from_quote(enriched, mask, "amplitude_pct", quote.get("amplitude_pct"))
            _set_from_quote(enriched, mask, "source", _merge_source(enriched.loc[mask, "source"].iloc[-1], quote.get("source")))
            if quote.get("limit_up") is not None:
                enriched.loc[mask, "is_limit_up"] = enriched.loc[mask, "close"] >= float(quote["limit_up"]) - 0.01
            if quote.get("limit_down") is not None:
                enriched.loc[mask, "is_limit_down"] = enriched.loc[mask, "close"] <= float(quote["limit_down"]) + 0.01

    return enriched.reindex(columns=DAILY_RAW_COLUMNS)


def _set_from_quote(frame: pd.DataFrame, mask: pd.Series, column: str, value: Any) -> None:
    if value is not None:
        frame.loc[mask, column] = value


def _merge_source(existing: Any, quote_source: Any) -> str:
    if quote_source:
        return f"{existing}; {quote_source}"
    return str(existing)


def _board_type(code: str) -> str:
    if code.startswith("688"):
        return "kcb"
    if code.startswith(("300", "301")):
        return "cyb"
    if code.startswith(("8", "920")):
        return "bj"
    return "main"


def _price_limit_pct(code: str, is_st: bool) -> int:
    if is_st:
        return 5
    if _board_type(code) in {"kcb", "cyb"}:
        return 20
    if _board_type(code) == "bj":
        return 30
    return 10


def _normalize_qfq_frame(frame: pd.DataFrame, code: str) -> pd.DataFrame:
    frame = frame.copy()
    frame["code"] = frame.get("code", code)
    if "trade_date" not in frame and "Date" in frame:
        frame["trade_date"] = pd.to_datetime(frame["Date"]).dt.strftime("%Y-%m-%d")
    if "fetched_at" not in frame:
        frame["fetched_at"] = datetime.now().isoformat(timespec="seconds")
    if "source" not in frame:
        frame["source"] = "unknown"
    if "adjustment" not in frame:
        frame["adjustment"] = "qfq"
    return frame.reindex(columns=DAILY_QFQ_COLUMNS)


def _build_features(
    daily_qfq: pd.DataFrame | None,
    quote: dict[str, Any] | None,
    code: str,
    trade_date: str,
) -> pd.DataFrame:
    if daily_qfq is None or daily_qfq.empty:
        return pd.DataFrame(columns=FEATURE_COLUMNS)

    frame = daily_qfq.copy()
    frame = frame.sort_values("trade_date")
    close = frame["close"]
    volume = frame["volume"] if "volume" in frame else pd.Series(dtype="float64")

    features = pd.DataFrame({"trade_date": frame["trade_date"], "code": code})
    features["as_of_date"] = features["trade_date"]
    features["usable_from"] = pd.to_datetime(features["trade_date"]).apply(
        lambda value: (value + timedelta(days=1)).strftime("%Y-%m-%d")
    )
    for window in (5, 10, 20, 30, 60, 120):
        features[f"ma{window}"] = close.rolling(window).mean()
    features["volume_ratio_20d"] = volume / volume.rolling(20).mean() if not volume.empty else pd.NA
    for window in (5, 10, 20, 60):
        features[f"return_{window}d"] = close.pct_change(window) * 100
    for window in (20, 60):
        rolling_high = close.rolling(window).max()
        rolling_low = close.rolling(window).min()
        features[f"drawdown_{window}d"] = (close / rolling_high - 1) * 100
        features[f"high_{window}d"] = rolling_high
        features[f"low_{window}d"] = rolling_low
    features["rsi"] = _rsi(close)
    macd, signal, hist = _macd(close)
    features["macd"] = macd
    features["macd_signal"] = signal
    features["macd_hist"] = hist
    features["atr"] = pd.NA

    quote = quote or {}
    if quote.get("quote_date") == trade_date:
        features.loc[features["trade_date"] == trade_date, "pe_ttm"] = quote.get("pe_ttm")
        features.loc[features["trade_date"] == trade_date, "pe_static"] = quote.get("pe_static")
        features.loc[features["trade_date"] == trade_date, "pb"] = quote.get("pb")
        features.loc[features["trade_date"] == trade_date, "market_cap_yuan"] = quote.get("market_cap_yuan")
        features.loc[features["trade_date"] == trade_date, "float_market_cap_yuan"] = quote.get("float_market_cap_yuan")
    else:
        features["pe_ttm"] = pd.NA
        features["pe_static"] = pd.NA
        features["pb"] = pd.NA
        features["market_cap_yuan"] = pd.NA
        features["float_market_cap_yuan"] = pd.NA
    features["feature_version"] = "1"
    features["generated_at"] = datetime.now().isoformat(timespec="seconds")

    features = features[features["trade_date"] <= trade_date]
    return features.reindex(columns=FEATURE_COLUMNS)


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    diff = close.diff()
    gain = diff.clip(lower=0).rolling(window).mean()
    loss = (-diff.clip(upper=0)).rolling(window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return macd, signal, hist


def _latest_row(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}
    row = frame.iloc[-1].where(pd.notnull(frame.iloc[-1]), None)
    return row.to_dict()


def _sources_from_latest(latest: dict[str, Any]) -> dict[str, Any]:
    sources = {}
    for key, value in latest.items():
        if isinstance(value, dict) and value.get("source"):
            sources[key] = value["source"]
    return sources


def _write_metadata(symbol_dir: Path, snapshot: dict[str, Any]) -> None:
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "code": snapshot["code"],
        "updated_at": snapshot["created_at"],
        "latest_trade_date": snapshot["trade_date"],
        "files": snapshot["files"],
    }
    write_json(symbol_dir / "metadata.json", metadata)
