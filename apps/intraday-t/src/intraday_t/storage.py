from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .models import MinuteBar, Snapshot, normalize_code


def trading_day(value: date | None = None) -> str:
    return (value or date.today()).isoformat()


def raw_snapshot_path(base_dir: Path, code: str, day: str | None = None) -> Path:
    safe_code = normalize_code(code)
    session_day = day or trading_day()
    return base_dir / "intraday" / session_day / "raw" / f"{safe_code}.jsonl"


def minute_bar_path(base_dir: Path, code: str, day: str | None = None) -> Path:
    safe_code = normalize_code(code)
    session_day = day or trading_day()
    return base_dir / "intraday" / session_day / "minute" / f"{safe_code}_1m.jsonl"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            file.write("\n")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        file.write("\n")


class RawSnapshotWriter:
    def __init__(self, base_dir: Path, day: str | None = None) -> None:
        self.base_dir = base_dir
        self.day = day

    def write(self, snapshot: Snapshot) -> Path:
        path = raw_snapshot_path(self.base_dir, snapshot.code, self.day)
        append_jsonl(path, snapshot.to_dict())
        return path


class MinuteBarWriter:
    def __init__(self, base_dir: Path, day: str | None = None) -> None:
        self.base_dir = base_dir
        self.day = day

    def write_all(self, code: str, bars: list[MinuteBar]) -> Path:
        path = minute_bar_path(self.base_dir, code, self.day)
        write_jsonl(path, [bar.to_dict() for bar in bars])
        return path
