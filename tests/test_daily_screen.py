from pathlib import Path

import pandas as pd

from libs.stock_data.daily_screen import run_daily_screen
from libs.stock_data.store import write_dataframe


def _seed_candidate(root: Path, code: str = "002463"):
    symbol_dir = root / "by-symbol" / code
    raw = pd.DataFrame(
        [
            {"trade_date": "2026-06-02", "code": code, "open": 10, "high": 11, "low": 9.8, "close": 11, "is_tradable": True, "is_suspended": False, "is_st": False, "is_limit_down": False},
        ]
    )
    features = pd.DataFrame(
        [
            {"trade_date": "2026-06-02", "code": code, "ma5": 10, "ma10": 9.8, "ma20": 9.5, "return_5d": 5, "drawdown_20d": -4, "volume_ratio_20d": 1.5},
        ]
    )
    write_dataframe(symbol_dir / "daily_raw.csv", raw)
    write_dataframe(symbol_dir / "features.csv", features)


def test_run_daily_screen_uses_local_data_without_events(tmp_path: Path):
    root = tmp_path / "stock-data"
    _seed_candidate(root)

    result = run_daily_screen("2026-06-02", codes=["002463"], data_dir=root)

    assert len(result) == 1
    assert "event_source_error_count" not in result.columns
    assert (root / "by-date" / "2026-06-02" / "screen_results.csv").exists()
    assert (root / "by-date" / "2026-06-02" / "errors.csv").exists()
    assert not (root / "by-symbol" / "002463" / "events.jsonl").exists()


def test_run_daily_screen_enriches_events_only_for_candidates(tmp_path: Path, monkeypatch):
    root = tmp_path / "stock-data"
    _seed_candidate(root)

    def fake_collect(code, trade_date, *, fields=None, refresh=False, data_dir=None):
        if fields == ["events"]:
            events_path = root / "by-symbol" / code / "events.jsonl"
            events_path.parent.mkdir(parents=True, exist_ok=True)
            events_path.write_text(
                '{"code":"002463","event_type":"dragon_tiger","effective_date":"2026-06-01"}\n',
                encoding="utf-8",
            )
        return {"code": code, "trade_date": trade_date, "fields": fields or []}

    monkeypatch.setattr("libs.stock_data.daily_screen.collect_stock_snapshot", fake_collect)

    result = run_daily_screen("2026-06-02", codes=["002463"], data_dir=root, enrich_events=True)

    assert len(result) == 1
    assert result.iloc[0]["dragon_tiger_count_30d"] == 1
    assert result.iloc[0]["event_source_error_count"] == 0


def test_run_daily_screen_respects_limit(tmp_path: Path):
    root = tmp_path / "stock-data"
    _seed_candidate(root, "002463")
    _seed_candidate(root, "300750")

    result = run_daily_screen("2026-06-02", codes=["002463", "300750"], limit=1, data_dir=root)

    assert len(result) == 1
    assert result.iloc[0]["code"] == "002463"
