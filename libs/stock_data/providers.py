"""Provider adapters for the stock data collector.

The collector depends on this small interface so tests can inject fake providers
and production code can reuse existing A-stock data functions without moving app
code into the repository-level storage layer.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
import hashlib
import json
import os
import sys
import urllib.request

import pandas as pd

from .paths import stock_data_dir


class StockDataProvider(Protocol):
    def daily_raw(self, code: str, start_date: str | None, end_date: str) -> pd.DataFrame:
        ...

    def daily_qfq(self, code: str, start_date: str | None, end_date: str) -> pd.DataFrame:
        ...

    def quote(self, code: str) -> dict[str, Any]:
        ...

    def fundamentals(self, code: str) -> dict[str, Any]:
        ...

    def events(self, code: str, trade_date: str) -> list[dict[str, Any]]:
        ...


class TradingAgentsAStockProvider:
    """Default A-stock provider for repository-local data assets.

    This adapter intentionally does not call the existing TradingAgents cached
    OHLCV helper because that helper writes to ``~/.tradingagents/cache``.
    """

    def daily_raw(self, code: str, start_date: str | None, end_date: str) -> pd.DataFrame:
        frame = _daily_from_easy_tdx(code, start_date, end_date, adjustment="raw")
        if frame.empty:
            frame = _daily_from_mootdx(code, start_date, end_date, adjustment="raw")
        if frame.empty:
            frame = _daily_from_sina(code, start_date, end_date, adjustment="raw")
        return frame

    def daily_qfq(self, code: str, start_date: str | None, end_date: str) -> pd.DataFrame:
        frame = _daily_from_easy_tdx(code, start_date, end_date, adjustment="qfq")
        if frame.empty:
            frame = self.daily_raw(code, start_date, end_date)
            if not frame.empty:
                frame = frame.copy()
                frame["adjustment"] = "raw_fallback"
                frame["source"] = frame["source"].astype(str) + " (qfq unavailable)"
        return frame

    def quote(self, code: str) -> dict[str, Any]:
        quote = _tencent_quote([code]).get(code, {})
        return _quote_to_snapshot(quote)

    def fundamentals(self, code: str) -> dict[str, Any]:
        quote = self.quote(code)
        return {
            "pe_ttm": quote.get("pe_ttm"),
            "pe_static": quote.get("pe_static"),
            "pb": quote.get("pb"),
            "market_cap_yuan": _yi_to_yuan(quote.get("mcap_yi")),
            "float_market_cap_yuan": _yi_to_yuan(quote.get("float_mcap_yi")),
            "source": quote.get("source"),
            "fetched_at": quote.get("fetched_at"),
        }

    def events(self, code: str, trade_date: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for loader in (_dragon_tiger_events, _lockup_expiry_events, _fund_flow_events):
            try:
                events.extend(loader(code, trade_date))
            except Exception as exc:
                events.append(_event_source_error(code, trade_date, loader.__name__, exc))
        return sorted(events, key=lambda item: (item.get("effective_date") or "", item.get("event_type") or ""))


def default_provider() -> StockDataProvider:
    return TradingAgentsAStockProvider()


def _import_astock_module():
    app_root = Path(__file__).resolve().parents[2] / "apps" / "TradingAgents-astock"
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))
    from tradingagents.dataflows import a_stock

    return a_stock


def _daily_from_easy_tdx(
    code: str,
    start_date: str | None,
    end_date: str,
    *,
    adjustment: str,
) -> pd.DataFrame:
    """Fetch daily bars from easy_tdx while keeping its config repo-local."""
    os.environ.setdefault(
        "EASY_TDX_CONFIG_DIR",
        str(stock_data_dir() / "provider-cache" / "easy_tdx"),
    )
    try:
        _patch_easy_tdx_config_dir(Path(os.environ["EASY_TDX_CONFIG_DIR"]))
        from easy_tdx.mac.enums import Adjust, Period
        from easy_tdx.unified import UnifiedTdxClient
    except Exception:
        return pd.DataFrame()

    market = _tdx_market(code)
    adjust = Adjust.QFQ if adjustment == "qfq" else Adjust.NONE
    try:
        with UnifiedTdxClient() as client:
            data = client.get_stock_kline(market, code, Period.DAILY, count=800, adjust=adjust)
    except Exception:
        return pd.DataFrame()
    return _normalize_daily_source_frame(
        data,
        code,
        start_date,
        end_date,
        adjustment=adjustment,
        source=f"easy_tdx {adjustment}",
    )


def _patch_easy_tdx_config_dir(config_dir: Path) -> None:
    """Keep easy_tdx config writes inside ``data/stock-data`` even if preloaded."""
    try:
        import easy_tdx.config as easy_config
    except Exception:
        return
    easy_config._CONFIG_DIR = config_dir
    easy_config._CONFIG_FILE = config_dir / "config.json"


def _daily_from_mootdx(
    code: str,
    start_date: str | None,
    end_date: str,
    *,
    adjustment: str,
) -> pd.DataFrame:
    try:
        from mootdx.quotes import Quotes

        client = Quotes.factory(market="std")
        data = client.bars(symbol=code, category=4, offset=800)
    except Exception:
        return pd.DataFrame()
    return _normalize_daily_source_frame(
        data,
        code,
        start_date,
        end_date,
        adjustment=adjustment,
        source=f"mootdx {adjustment}",
    )


def _daily_from_sina(
    code: str,
    start_date: str | None,
    end_date: str,
    *,
    adjustment: str,
) -> pd.DataFrame:
    try:
        a_stock = _import_astock_module()
        data = a_stock._sina_kline_fallback(code, start_date, end_date)
    except Exception:
        return pd.DataFrame()
    return _normalize_daily_source_frame(
        data,
        code,
        start_date,
        end_date,
        adjustment=adjustment,
        source=f"sina HTTP {adjustment}",
    )


def _normalize_daily_source_frame(
    data: pd.DataFrame,
    code: str,
    start_date: str | None,
    end_date: str,
    *,
    adjustment: str,
    source: str,
) -> pd.DataFrame:
    if data is None or data.empty:
        return pd.DataFrame()

    data = data.copy()
    data = data.loc[:, ~data.columns.duplicated()]
    data = data.drop(columns=["year", "month", "day", "hour", "minute"], errors="ignore")
    if "Date" not in data.columns and "datetime" not in data.columns:
        data = data.reset_index()

    rename_map = {
        "datetime": "Date",
        "date": "Date",
        "index": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
        "vol": "Volume",
        "amount": "Amount",
    }
    data = data.rename(columns=rename_map)
    data = data.loc[:, ~data.columns.duplicated()]
    required = {"Date", "Open", "High", "Low", "Close"}
    if not required.issubset(data.columns):
        return pd.DataFrame()

    data["Date"] = pd.to_datetime(data["Date"])
    if start_date:
        data = data[data["Date"] >= pd.to_datetime(start_date)]
    data = data[data["Date"] <= pd.to_datetime(end_date)]
    if data.empty:
        return pd.DataFrame()

    fetched_at = datetime.now().isoformat(timespec="seconds")
    frame = pd.DataFrame(
        {
            "trade_date": data["Date"].dt.strftime("%Y-%m-%d"),
            "code": code,
            "open": data["Open"],
            "high": data["High"],
            "low": data["Low"],
            "close": data["Close"],
            "volume": data["Volume"] if "Volume" in data else pd.NA,
            "amount_yuan": data.get("Amount", pd.NA),
            "source": source,
            "fetched_at": fetched_at,
        }
    )
    frame["adjustment"] = adjustment
    return frame


def _tencent_quote(codes: list[str]) -> dict[str, dict[str, Any]]:
    prefixed = [f"{_market_prefix(code)}{code}" for code in codes]
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    try:
        raw = urllib.request.urlopen(req, timeout=10).read().decode("gbk")
    except Exception:
        return {}

    result: dict[str, dict[str, Any]] = {}
    for line in raw.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]
        result[code] = {
            "name": vals[1],
            "price": _float_or_none(vals[3]),
            "last_close": _float_or_none(vals[4]),
            "open": _float_or_none(vals[5]),
            "quote_time": vals[30] if len(vals) > 30 else None,
            "quote_date": _quote_date(vals[30] if len(vals) > 30 else None),
            "change_amt": _float_or_none(vals[31]),
            "change_pct": _float_or_none(vals[32]),
            "high": _float_or_none(vals[33]),
            "low": _float_or_none(vals[34]),
            "amount_wan": _float_or_none(vals[37]),
            "turnover_rate_pct": _float_or_none(vals[38]),
            "pe_ttm": _float_or_none(vals[39]),
            "amplitude_pct": _float_or_none(vals[43]),
            "mcap_yi": _float_or_none(vals[44]),
            "float_mcap_yi": _float_or_none(vals[45]),
            "pb": _float_or_none(vals[46]),
            "limit_up": _float_or_none(vals[47]),
            "limit_down": _float_or_none(vals[48]),
            "vol_ratio": _float_or_none(vals[49]),
            "pe_static": _float_or_none(vals[52]),
        }
    return result


def _tdx_market(code: str) -> int:
    return 1 if code.startswith(("6", "9")) else 0


def _market_prefix(code: str) -> str:
    if code.startswith(("6", "9")):
        return "sh"
    if code.startswith("8"):
        return "bj"
    return "sz"


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quote_date(value: Any) -> str | None:
    text = str(value or "")
    if len(text) < 8 or not text[:8].isdigit():
        return None
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def _quote_to_snapshot(quote: dict[str, Any]) -> dict[str, Any]:
    fetched_at = datetime.now().isoformat(timespec="seconds")
    result = dict(quote)
    result["market_cap_yuan"] = _yi_to_yuan(quote.get("mcap_yi"))
    result["float_market_cap_yuan"] = _yi_to_yuan(quote.get("float_mcap_yi"))
    result["source"] = "腾讯财经 qt.gtimg.cn"
    result["fetched_at"] = fetched_at
    return result


def _yi_to_yuan(value: Any) -> Any:
    if value is None or value == "":
        return None
    try:
        return float(value) * 100_000_000
    except (TypeError, ValueError):
        return None


def _dragon_tiger_events(code: str, trade_date: str, look_back_days: int = 30) -> list[dict[str, Any]]:
    a_stock = _import_astock_module()
    start_date = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=look_back_days)).strftime("%Y-%m-%d")
    rows = a_stock._eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=(
            f"(TRADE_DATE>='{start_date}')"
            f"(TRADE_DATE<='{trade_date}')"
            f"(SECURITY_CODE=\"{code}\")"
        ),
        page_size=50,
        sort_columns="TRADE_DATE",
        sort_types="-1",
    )
    return [_dragon_tiger_event(code, row) for row in rows]


def _dragon_tiger_event(code: str, row: dict[str, Any]) -> dict[str, Any]:
    event_date = _date_prefix(row.get("TRADE_DATE"))
    reason = row.get("EXPLANATION") or "龙虎榜"
    net_buy_yuan = _float_or_none(row.get("BILLBOARD_NET_AMT"))
    turnover_pct = _float_or_none(row.get("TURNOVERRATE"))
    return {
        "event_id": _event_id(code, "dragon_tiger", event_date, row),
        "code": code,
        "event_type": "dragon_tiger",
        "announce_date": event_date,
        "effective_date": event_date,
        "trade_date": event_date,
        "usable_from": _next_day(event_date),
        "title": reason,
        "summary": f"龙虎榜上榜，净买入 {net_buy_yuan or 0:.0f} 元，换手率 {turnover_pct or 0:.2f}%",
        "value": net_buy_yuan,
        "value_unit": "yuan",
        "source": "东方财富 datacenter RPT_DAILYBILLBOARD_DETAILSNEW",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "raw": row,
    }


def _lockup_expiry_events(code: str, trade_date: str, forward_days: int = 90) -> list[dict[str, Any]]:
    a_stock = _import_astock_module()
    end_date = (datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=forward_days)).strftime("%Y-%m-%d")
    rows = a_stock._eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=(
            f"(SECURITY_CODE=\"{code}\")"
            f"(FREE_DATE>='{trade_date}')"
            f"(FREE_DATE<='{end_date}')"
        ),
        page_size=50,
        sort_columns="FREE_DATE",
        sort_types="1",
    )
    return [_lockup_expiry_event(code, row, trade_date) for row in rows]


def _lockup_expiry_event(code: str, row: dict[str, Any], snapshot_trade_date: str) -> dict[str, Any]:
    effective_date = _date_prefix(row.get("FREE_DATE"))
    announce_date = (
        _date_prefix(row.get("NOTICE_DATE"))
        or _date_prefix(row.get("ANNOUNCE_DATE"))
        or _date_prefix(row.get("DECLAREDATE"))
        or datetime.now().strftime("%Y-%m-%d")
    )
    shares = _float_or_none(row.get("FREE_SHARES_NUM"))
    ratio = _float_or_none(row.get("FREE_RATIO"))
    lockup_type = row.get("LIMITED_STOCK_TYPE") or "限售解禁"
    return {
        "event_id": _event_id(code, "lockup_expiry", effective_date, row),
        "code": code,
        "event_type": "lockup_expiry",
        "announce_date": announce_date,
        "effective_date": effective_date,
        "trade_date": snapshot_trade_date,
        "usable_from": announce_date,
        "title": lockup_type,
        "summary": f"{effective_date} 解禁，类型：{lockup_type}，数量：{shares or 0:.0f}，占比：{ratio if ratio is not None else 'N/A'}",
        "value": ratio,
        "value_unit": "pct",
        "source": "东方财富 datacenter RPT_LIFT_STAGE",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "raw": row,
    }


def _fund_flow_events(code: str, trade_date: str, limit: int = 20) -> list[dict[str, Any]]:
    a_stock = _import_astock_module()
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": secid,
        "lmt": limit,
        "klt": 101,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    response = a_stock._em_get(url, params=params, timeout=10)
    rows = response.json().get("data", {}).get("klines", [])
    events = []
    for line in rows:
        event = _fund_flow_event(code, line)
        if event.get("trade_date") and event["trade_date"] <= trade_date:
            events.append(event)
    return events


def _fund_flow_event(code: str, line: str) -> dict[str, Any]:
    parts = str(line).split(",")
    event_date = parts[0] if parts else None
    main_net = _float_or_none(parts[1] if len(parts) > 1 else None)
    small_net = _float_or_none(parts[2] if len(parts) > 2 else None)
    mid_net = _float_or_none(parts[3] if len(parts) > 3 else None)
    large_net = _float_or_none(parts[4] if len(parts) > 4 else None)
    super_net = _float_or_none(parts[5] if len(parts) > 5 else None)
    raw = {
        "line": line,
        "main_net_yuan": main_net,
        "small_net_yuan": small_net,
        "mid_net_yuan": mid_net,
        "large_net_yuan": large_net,
        "super_net_yuan": super_net,
    }
    return {
        "event_id": _event_id(code, "fund_flow", event_date, raw),
        "code": code,
        "event_type": "fund_flow",
        "announce_date": event_date,
        "effective_date": event_date,
        "trade_date": event_date,
        "usable_from": _next_day(event_date),
        "title": "个股资金流",
        "summary": f"主力净流入 {main_net or 0:.0f} 元，大单 {large_net or 0:.0f} 元，超大单 {super_net or 0:.0f} 元",
        "value": main_net,
        "value_unit": "yuan",
        "source": "东方财富 push2his fflow daykline",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "raw": raw,
    }


def _date_prefix(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)[:10]
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None
    return text


def _next_day(date_value: str | None) -> str | None:
    if not date_value:
        return None
    try:
        return (datetime.strptime(date_value, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        return date_value


def _event_id(code: str, event_type: str, event_date: str | None, raw: dict[str, Any]) -> str:
    raw_text = json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha1(raw_text.encode("utf-8")).hexdigest()[:12]
    return f"{code}:{event_type}:{event_date or 'unknown'}:{digest}"


def _event_source_error(code: str, trade_date: str, source_name: str, exc: Exception) -> dict[str, Any]:
    raw = {"source_name": source_name, "error": str(exc)}
    return {
        "event_id": _event_id(code, "event_source_error", trade_date, raw),
        "code": code,
        "event_type": "event_source_error",
        "announce_date": trade_date,
        "effective_date": trade_date,
        "trade_date": trade_date,
        "usable_from": trade_date,
        "title": f"事件源失败：{source_name}",
        "summary": str(exc),
        "value": None,
        "value_unit": "error",
        "source": source_name,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "raw": raw,
    }
