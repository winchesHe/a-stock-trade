"""Read/write helpers for repository stock data assets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from .paths import snapshot_path, symbol_data_dir


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_dataframe(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")


def append_events(path: Path, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        for event in events:
            fp.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def replace_events(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for event in events:
            fp.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def load_stock_snapshot(
    code: str,
    trade_date: str,
    *,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Load a saved stock snapshot."""
    return read_json(snapshot_path(code, trade_date, data_dir))


def load_daily_bars(
    code: str,
    *,
    adjustment: Literal["raw", "qfq"] = "qfq",
    data_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Load raw or qfq daily bars for one symbol."""
    if adjustment not in {"raw", "qfq"}:
        raise ValueError("adjustment 只能是 raw 或 qfq")
    path = symbol_data_dir(code, data_dir) / f"daily_{adjustment}.csv"
    return pd.read_csv(path, dtype={"code": str, "trade_date": str})


def load_events(
    code: str,
    *,
    event_type: str | None = None,
    data_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Load events for one symbol, optionally filtered by event type."""
    path = symbol_data_dir(code, data_dir) / "events.jsonl"
    if not path.exists():
        return []

    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event_type is None or event.get("event_type") == event_type:
            events.append(event)
    return events
