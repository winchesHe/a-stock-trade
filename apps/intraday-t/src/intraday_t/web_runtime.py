from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .baidu_ws import stream_snapshots
from .collector import APP_ROOT, DEFAULT_DATA_DIR
from .models import Snapshot, normalize_code
from .monitor import run_once
from .storage import minute_bar_path, raw_snapshot_path, read_jsonl, signal_path, RawSnapshotWriter

StreamFactory = Callable[[Iterable[str], float | None], AsyncIterator[Snapshot]]
ACTIONABLE_SIGNALS = {"high_sell", "low_buy", "cover_back"}
SIGNAL_LABELS = {"high_sell": "高抛", "low_buy": "低吸", "cover_back": "回补"}
DEFAULT_WEB_CONFIG_PATH = APP_ROOT / "data" / "web_config.json"


@dataclass(slots=True)
class WebUiConfig:
    stocks_text: str = "002463"
    day: str | None = None
    data_dir: str = str(DEFAULT_DATA_DIR)
    has_position: bool = True
    opening_minutes: int = 5
    timeout: float = 5.0
    limit: int = 200
    auto_refresh: bool = False
    refresh_interval: float = 10.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _coerce_config(payload: dict[str, Any]) -> WebUiConfig:
    defaults = WebUiConfig()
    return WebUiConfig(
        stocks_text=str(payload.get("stocks_text") or defaults.stocks_text),
        day=str(payload["day"]) if payload.get("day") else None,
        data_dir=str(payload.get("data_dir") or defaults.data_dir),
        has_position=bool(payload.get("has_position", defaults.has_position)),
        opening_minutes=int(payload.get("opening_minutes", defaults.opening_minutes)),
        timeout=float(payload.get("timeout", defaults.timeout)),
        limit=int(payload.get("limit", defaults.limit)),
        auto_refresh=bool(payload.get("auto_refresh", defaults.auto_refresh)),
        refresh_interval=float(payload.get("refresh_interval", defaults.refresh_interval)),
    )


def load_web_config(path: Path = DEFAULT_WEB_CONFIG_PATH) -> WebUiConfig:
    if not path.exists():
        return WebUiConfig()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return WebUiConfig()
    return _coerce_config(payload) if isinstance(payload, dict) else WebUiConfig()


def save_web_config(config: WebUiConfig, path: Path = DEFAULT_WEB_CONFIG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def reset_web_config(path: Path = DEFAULT_WEB_CONFIG_PATH) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


@dataclass(slots=True)
class CollectorStatus:
    running: bool
    codes: list[str]
    day: str | None
    started_at: str | None = None
    stopped_at: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    latest: dict[str, Snapshot] = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class DashboardCodeData:
    code: str
    raw_count: int
    minute_count: int
    signal_count: int
    latest_snapshot: dict[str, Any] | None
    latest_signal: dict[str, Any] | None
    minute_rows: list[dict[str, Any]]
    signal_rows: list[dict[str, Any]]


class WebCollectorSession:
    def __init__(self, stream_factory: StreamFactory = stream_snapshots) -> None:
        self._stream_factory = stream_factory
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._running = False
        self._codes: list[str] = []
        self._base_dir: Path | None = None
        self._day: str | None = None
        self._started_at: str | None = None
        self._stopped_at: str | None = None
        self._counts: dict[str, int] = {}
        self._latest: dict[str, Snapshot] = {}
        self._error: str | None = None

    def start(self, codes: list[str], base_dir: Path, day: str | None, timeout: float | None = 30.0) -> None:
        normalized_codes = [normalize_code(code) for code in codes]
        self.stop()
        with self._lock:
            self._codes = normalized_codes
            self._base_dir = base_dir
            self._day = day
            self._started_at = datetime.now().isoformat(timespec="seconds")
            self._stopped_at = None
            self._counts = {}
            self._latest = {}
            self._error = None
            self._running = True
            self._thread = threading.Thread(
                target=self._thread_main,
                args=(normalized_codes, base_dir, day, timeout),
                daemon=True,
                name="intraday-t-web-collector",
            )
            self._thread.start()

    def stop(self) -> None:
        thread: threading.Thread | None
        with self._lock:
            thread = self._thread
            loop = self._loop
            stop_event = self._stop_event
        if loop is not None and stop_event is not None and not loop.is_closed():
            loop.call_soon_threadsafe(stop_event.set)
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with self._lock:
            if self._thread is thread:
                self._thread = None
            if self._running:
                self._running = False
                self._stopped_at = datetime.now().isoformat(timespec="seconds")

    def status(self) -> CollectorStatus:
        with self._lock:
            return CollectorStatus(
                running=self._running,
                codes=list(self._codes),
                day=self._day,
                started_at=self._started_at,
                stopped_at=self._stopped_at,
                counts=dict(self._counts),
                latest=dict(self._latest),
                error=self._error,
            )

    def _thread_main(self, codes: list[str], base_dir: Path, day: str | None, timeout: float | None) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        stop_event = asyncio.Event()
        with self._lock:
            self._loop = loop
            self._stop_event = stop_event
        try:
            loop.run_until_complete(self._collect(codes, base_dir, day, timeout, stop_event))
        except Exception as exc:  # pragma: no cover - 守护后台线程，错误通过 status 暴露
            with self._lock:
                self._error = str(exc)
        finally:
            with self._lock:
                self._running = False
                self._stopped_at = datetime.now().isoformat(timespec="seconds")
                self._loop = None
                self._stop_event = None
            loop.close()

    async def _collect(
        self,
        codes: list[str],
        base_dir: Path,
        day: str | None,
        timeout: float | None,
        stop_event: asyncio.Event,
    ) -> None:
        writer = RawSnapshotWriter(base_dir, day)
        iterator = self._stream_factory(codes, timeout)
        try:
            while not stop_event.is_set():
                next_task = asyncio.create_task(anext(iterator))
                stop_task = asyncio.create_task(stop_event.wait())
                done, pending = await asyncio.wait({next_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
                if stop_task in done:
                    next_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                        await next_task
                    break

                stop_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stop_task
                try:
                    snapshot = next_task.result()
                except StopAsyncIteration:
                    break

                writer.write(snapshot)
                with self._lock:
                    self._counts[snapshot.code] = self._counts.get(snapshot.code, 0) + 1
                    self._latest[snapshot.code] = snapshot
        finally:
            close = getattr(iterator, "aclose", None)
            if close is not None:
                await close()


def refresh_signals(
    base_dir: Path,
    codes: list[str],
    day: str | None,
    *,
    has_position: bool,
    opening_minutes: int,
) -> list[str]:
    return run_once(base_dir, codes, day, has_position=has_position, opening_minutes=opening_minutes)


def _tail_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return rows
    return rows[-limit:]


def load_dashboard_data(base_dir: Path, codes: list[str], day: str | None, *, limit: int = 200) -> list[DashboardCodeData]:
    result: list[DashboardCodeData] = []
    for code in codes:
        safe_code = normalize_code(code)
        raw_rows = read_jsonl(raw_snapshot_path(base_dir, safe_code, day))
        minute_rows = read_jsonl(minute_bar_path(base_dir, safe_code, day))
        signal_rows = read_jsonl(signal_path(base_dir, safe_code, day))
        result.append(
            DashboardCodeData(
                code=safe_code,
                raw_count=len(raw_rows),
                minute_count=len(minute_rows),
                signal_count=len(signal_rows),
                latest_snapshot=raw_rows[-1] if raw_rows else None,
                latest_signal=signal_rows[-1] if signal_rows else None,
                minute_rows=_tail_rows(minute_rows, limit),
                signal_rows=_tail_rows(signal_rows, limit),
            )
        )
    return result


def latest_actionable_signals(rows: list[DashboardCodeData]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for row in rows:
        signal = row.latest_signal
        if not signal or signal.get("signal") not in ACTIONABLE_SIGNALS:
            continue
        item = dict(signal)
        item["code"] = row.code
        signals.append(item)
    return sorted(signals, key=lambda item: int(item.get("strength") or 0), reverse=True)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    return numerator / denominator * 100


def build_signal_board_rows(rows: list[DashboardCodeData], names_by_code: dict[str, str] | None = None) -> list[dict[str, Any]]:
    names = names_by_code or {}
    board_rows: list[dict[str, Any]] = []
    for row in rows:
        snapshot = row.latest_snapshot or {}
        signal = row.latest_signal or {}
        signal_name = str(signal.get("signal") or "no_signal")
        price = signal.get("price", snapshot.get("price"))
        reference_price = signal.get("reference_price", snapshot.get("avg_price"))
        price_value = _to_float(price)
        reference_value = _to_float(reference_price)
        deviation_pct = _pct(
            price_value - reference_value if price_value is not None and reference_value is not None else None,
            reference_value,
        )
        reasons = signal.get("reasons") if isinstance(signal.get("reasons"), list) else []
        board_rows.append(
            {
                "code": row.code,
                "名称": names.get(row.code) or snapshot.get("name") or "",
                "操作": SIGNAL_LABELS.get(signal_name, ""),
                "信号": signal_name,
                "强度": signal.get("strength"),
                "最新价": price,
                "涨跌幅%": snapshot.get("ratio"),
                "VWAP": snapshot.get("avg_price"),
                "参考价": reference_price,
                "偏离参考%": deviation_pct,
                "动作": signal.get("action", ""),
                "原因": "；".join(str(value) for value in reasons),
                "失效条件": signal.get("stop_condition", ""),
                "策略": signal.get("strategy", ""),
                "更新时间": signal.get("ts") or snapshot.get("ts") or "",
                "raw条数": row.raw_count,
                "信号数": row.signal_count,
            }
        )
    return sorted(
        board_rows,
        key=lambda item: (0 if item["操作"] else 1, -(int(item.get("强度") or 0))),
    )


def snapshot_to_dict(snapshot: Snapshot | None) -> dict[str, Any] | None:
    return asdict(snapshot) if snapshot is not None else None
