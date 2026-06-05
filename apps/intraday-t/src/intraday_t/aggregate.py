from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import MinuteBar, Snapshot, normalize_code
from .storage import MinuteBarWriter, raw_snapshot_path, read_jsonl


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _minute_iso(value: str) -> str:
    ts = _parse_ts(value)
    return ts.replace(second=0, microsecond=0).isoformat()


def _safe_delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    delta = current - previous
    return delta if delta >= 0 else 0.0


def _pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator * 100


def snapshot_from_dict(payload: dict[str, Any]) -> Snapshot:
    return Snapshot(
        ts=str(payload["ts"]),
        source=str(payload.get("source") or ""),
        code=normalize_code(str(payload["code"])),
        name=payload.get("name"),
        price=payload.get("price"),
        ratio=payload.get("ratio"),
        increase=payload.get("increase"),
        avg_price=payload.get("avg_price"),
        open=payload.get("open"),
        high=payload.get("high"),
        low=payload.get("low"),
        pre_close=payload.get("pre_close"),
        amount=payload.get("amount"),
        volume=payload.get("volume"),
        turnover_ratio=payload.get("turnover_ratio"),
        raw=payload.get("raw") if isinstance(payload.get("raw"), dict) else {},
    )


def aggregate_snapshots(snapshots: list[Snapshot]) -> list[MinuteBar]:
    valid = sorted((item for item in snapshots if item.price is not None), key=lambda item: item.ts)
    if not valid:
        return []

    groups: OrderedDict[str, list[Snapshot]] = OrderedDict()
    for snapshot in valid:
        groups.setdefault(_minute_iso(snapshot.ts), []).append(snapshot)

    bars: list[MinuteBar] = []
    previous_amount: float | None = None
    previous_volume: float | None = None
    day_high: float | None = None
    day_low: float | None = None

    for minute, items in groups.items():
        prices = [item.price for item in items if item.price is not None]
        if not prices:
            continue

        first = items[0]
        last = items[-1]
        amount_delta = _safe_delta(last.amount, previous_amount)
        volume_delta = _safe_delta(last.volume, previous_volume)
        if previous_amount is None and last.amount is not None:
            amount_delta = last.amount
        if previous_volume is None and last.volume is not None:
            volume_delta = last.volume

        previous_amount = last.amount if last.amount is not None else previous_amount
        previous_volume = last.volume if last.volume is not None else previous_volume
        high = max(prices)
        low = min(prices)
        day_high = high if day_high is None else max(day_high, high)
        day_low = low if day_low is None else min(day_low, low)
        vwap = last.avg_price
        if vwap is None and last.amount is not None and last.volume not in (None, 0):
            vwap = last.amount / last.volume

        bars.append(
            MinuteBar(
                minute=minute,
                code=last.code,
                open=first.price or prices[0],
                high=high,
                low=low,
                close=last.price or prices[-1],
                vwap=vwap,
                amount_delta=amount_delta,
                volume_delta=volume_delta,
                turnover_ratio=last.turnover_ratio,
                price_vs_vwap_pct=_pct((last.price - vwap) if last.price is not None and vwap is not None else None, vwap),
                price_vs_open_pct=_pct((last.price - last.open) if last.price is not None and last.open is not None else None, last.open),
                price_vs_pre_close_pct=_pct(
                    (last.price - last.pre_close) if last.price is not None and last.pre_close is not None else None,
                    last.pre_close,
                ),
                day_high_so_far=day_high,
                day_low_so_far=day_low,
            )
        )

    return bars


def aggregate_raw_file(path: Path) -> list[MinuteBar]:
    return aggregate_snapshots([snapshot_from_dict(row) for row in read_jsonl(path)])


def aggregate_code(base_dir: Path, code: str, day: str | None = None) -> tuple[Path, list[MinuteBar]]:
    raw_path = raw_snapshot_path(base_dir, code, day)
    bars = aggregate_raw_file(raw_path)
    output_path = MinuteBarWriter(base_dir, day).write_all(code, bars)
    return output_path, bars
