"""Daily batch screening workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .collector import collect_stock_snapshot
from .paths import normalize_code, stock_data_dir, symbol_data_dir
from .screener import screen_stocks
from .store import load_events, write_dataframe


def run_daily_screen(
    trade_date: str,
    *,
    codes: list[str] | None = None,
    limit: int | None = 100,
    refresh: bool = False,
    enrich_events: bool = False,
    data_dir: str | Path | None = None,
    rules: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Run daily low-risk screening and save by-date results.

    Default mode does not collect Eastmoney event data. Event enrichment is
    applied only to coarse-screened candidates when ``enrich_events`` is true.
    """
    selected_codes = [normalize_code(code) for code in (codes or [])]
    if limit is not None:
        selected_codes = selected_codes[:limit]

    root = stock_data_dir(data_dir)
    output_dir = root / "by-date" / trade_date
    output_dir.mkdir(parents=True, exist_ok=True)

    errors = []
    coarse_fields = ["daily_raw", "daily_qfq", "features"]
    for code in selected_codes:
        try:
            if refresh or not _has_coarse_data(code, data_dir):
                collect_stock_snapshot(
                    code,
                    trade_date,
                    fields=coarse_fields,
                    refresh=refresh,
                    data_dir=data_dir,
                )
        except Exception as exc:
            errors.append({"code": code, "stage": "collect", "error": str(exc)})

    result = screen_stocks(
        selected_codes,
        trade_date,
        rules={**(rules or {}), "use_events": False},
        refresh=False,
        data_dir=data_dir,
    )

    if enrich_events and not result.empty:
        result = _enrich_candidate_events(result, trade_date, refresh, data_dir, errors)

    write_dataframe(output_dir / "screen_results.csv", result)
    write_dataframe(output_dir / "errors.csv", pd.DataFrame(errors, columns=["code", "stage", "error"]))
    return result


def _enrich_candidate_events(
    result: pd.DataFrame,
    trade_date: str,
    refresh: bool,
    data_dir: str | Path | None,
    errors: list[dict[str, str]],
) -> pd.DataFrame:
    enriched = result.copy()
    dragon_counts = []
    source_error_counts = []
    for code in enriched["code"].astype(str):
        try:
            collect_stock_snapshot(
                code,
                trade_date,
                fields=["events"],
                refresh=refresh,
                data_dir=data_dir,
            )
            dragon_counts.append(_count_events(code, "dragon_tiger", data_dir))
            source_error_counts.append(_count_events(code, "event_source_error", data_dir))
        except Exception as exc:
            errors.append({"code": code, "stage": "events", "error": str(exc)})
            dragon_counts.append(0)
            source_error_counts.append(1)
    enriched["dragon_tiger_count_30d"] = dragon_counts
    enriched["event_source_error_count"] = source_error_counts
    enriched["score"] = enriched["score"] + enriched["dragon_tiger_count_30d"]
    return enriched.sort_values("score", ascending=False).reset_index(drop=True)


def _has_coarse_data(code: str, data_dir: str | Path | None) -> bool:
    symbol_dir = symbol_data_dir(code, data_dir)
    return (symbol_dir / "daily_raw.csv").exists() and (symbol_dir / "features.csv").exists()


def _count_events(code: str, event_type: str, data_dir: str | Path | None) -> int:
    return len(load_events(code, event_type=event_type, data_dir=data_dir))
