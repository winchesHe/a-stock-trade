from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Snapshot:
    ts: str
    source: str
    code: str
    name: str | None = None
    price: float | None = None
    ratio: float | None = None
    increase: float | None = None
    avg_price: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    pre_close: float | None = None
    amount: float | None = None
    volume: float | None = None
    turnover_ratio: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MinuteBar:
    minute: str
    code: str
    open: float
    high: float
    low: float
    close: float
    vwap: float | None = None
    amount_delta: float | None = None
    volume_delta: float | None = None
    turnover_ratio: float | None = None
    price_vs_vwap_pct: float | None = None
    price_vs_open_pct: float | None = None
    price_vs_pre_close_pct: float | None = None
    day_high_so_far: float | None = None
    day_low_so_far: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PositionContext:
    has_base_position: bool = True
    base_shares: int | None = None
    planned_t_shares: int | None = None
    opened_side: str | None = None
    opened_price: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class IntradayContext:
    regime: str
    confidence: int
    open_range_high: float | None = None
    open_range_low: float | None = None
    recent_high: float | None = None
    recent_low: float | None = None
    reasons: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Signal:
    ts: str
    code: str
    signal: str
    strength: int
    action: str
    position_required: bool
    price: float
    reference_price: float | None = None
    stop_condition: str | None = None
    reasons: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    strategy: str | None = None
    regime: str | None = None
    position_state: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_code(code: str) -> str:
    digits = "".join(ch for ch in str(code).strip() if ch.isdigit())
    if len(digits) != 6:
        raise ValueError(f"股票代码必须是 6 位数字: {code!r}")
    return digits


def parse_codes(value: str) -> list[str]:
    codes = [normalize_code(item) for item in value.replace(";", ",").split(",") if item.strip()]
    if not codes:
        raise ValueError("至少需要提供一个股票代码")
    return list(dict.fromkeys(codes))


def ensure_iso_ts(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return value
