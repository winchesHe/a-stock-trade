from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterable
from datetime import datetime, timezone
from typing import Any

from .models import Snapshot, normalize_code

BAIDU_WS_URL = "wss://finance-ws.pae.baidu.com"
SOURCE = "baidu_ws"


def build_subscribe_message(codes: Iterable[str]) -> dict[str, Any]:
    return {
        "method": "subscribe",
        "source": "pc-web",
        "product": "snapshot",
        "items": [
            {"code": normalize_code(code), "market": "ab", "financeType": "stock"}
            for code in codes
        ],
    }


def decode_message(message: str | bytes) -> dict[str, Any] | None:
    if isinstance(message, bytes):
        message = message.decode("utf-8")
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _first_present(payload: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in payload and payload[key] not in ("", None):
            return payload[key]
    return None


def _to_float(value: Any) -> float | None:
    if value in ("", None, "--", "-"):
        return None
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def _normalize_pankouinfos(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, list):
        return {}

    result: dict[str, Any] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        key = item.get("ename")
        if not key:
            continue
        result[str(key)] = item.get("originValue", item.get("value"))
    return result


def _find_stock_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[Any] = [payload]
    for key in ("data", "result", "body", "item", "snapshot"):
        value = payload.get(key)
        if isinstance(value, dict):
            candidates.append(value)
        elif isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))

    for candidate in candidates:
        if _first_present(candidate, ("code", "securityCode", "symbol")):
            return candidate
        cur = candidate.get("cur")
        if isinstance(cur, dict) and _first_present(cur, ("code", "securityCode", "symbol")):
            merged = dict(candidate)
            merged.update(cur)
            return merged
    return None


def normalize_snapshot(payload: dict[str, Any], received_at: datetime | None = None) -> Snapshot | None:
    stock = _find_stock_payload(payload)
    if not stock:
        return None

    cur = stock.get("cur") if isinstance(stock.get("cur"), dict) else {}
    pankou = _normalize_pankouinfos(stock.get("pankouinfos"))
    merged = {**stock, **cur, **pankou}
    raw_code = _first_present(merged, ("code", "securityCode", "symbol"))
    if not raw_code:
        return None

    try:
        code = normalize_code(str(raw_code))
    except ValueError:
        return None

    timestamp = received_at or datetime.now(timezone.utc).astimezone()
    return Snapshot(
        ts=timestamp.isoformat(),
        source=SOURCE,
        code=code,
        name=_first_present(merged, ("name", "stockName", "shortName")),
        price=_to_float(_first_present(merged, ("price", "curPrice", "lastPrice"))),
        ratio=_to_float(_first_present(merged, ("ratio", "changeRatio", "pctChg"))),
        increase=_to_float(_first_present(merged, ("increase", "change", "diff"))),
        avg_price=_to_float(_first_present(merged, ("avgPrice", "avg_price", "averagePrice"))),
        open=_to_float(_first_present(merged, ("open", "openPrice"))),
        high=_to_float(_first_present(merged, ("high", "highPrice"))),
        low=_to_float(_first_present(merged, ("low", "lowPrice"))),
        pre_close=_to_float(_first_present(merged, ("preClose", "pre_close", "preClosePrice"))),
        amount=_to_float(_first_present(merged, ("amount", "turnover"))),
        volume=_to_float(_first_present(merged, ("volume", "vol"))),
        turnover_ratio=_to_float(_first_present(merged, ("turnoverRatio", "turnover_ratio"))),
        raw=payload,
    )


async def stream_snapshots(codes: Iterable[str], timeout: float | None = None) -> AsyncIterator[Snapshot]:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError("缺少 websockets 依赖，请先安装 intraday-t") from exc

    code_list = [normalize_code(code) for code in codes]
    headers = {"User-Agent": "Mozilla/5.0 intraday-t/0.1"}
    async with websockets.connect(BAIDU_WS_URL, additional_headers=headers) as websocket:
        await websocket.send(json.dumps(build_subscribe_message(code_list), ensure_ascii=False))
        while True:
            message = await asyncio.wait_for(websocket.recv(), timeout=timeout) if timeout else await websocket.recv()
            payload = decode_message(message)
            if not payload:
                continue
            snapshot = normalize_snapshot(payload)
            if snapshot and snapshot.code in code_list:
                yield snapshot
