from pathlib import Path

import pandas as pd

from libs.stock_data.universe import collect_universe_daily_data, fetch_market_universe


def test_fetch_market_universe_excludes_30_and_68(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "libs.stock_data.universe._fetch_mootdx_universe",
        lambda: [
            {"code": "000001", "name": "平安银行", "market": "sz"},
            {"code": "000003", "name": "B股指数", "market": "sh"},
            {"code": "300750", "name": "宁德时代", "market": "sz"},
            {"code": "600519", "name": "贵州茅台", "market": "sh"},
            {"code": "688001", "name": "科创样例", "market": "sh"},
        ],
    )

    result = fetch_market_universe(data_dir=tmp_path / "stock-data")

    assert result["code"].tolist() == ["000001", "600519"]
    assert (tmp_path / "stock-data" / "universe" / "market_universe_ex_30_68.csv").exists()


def test_collect_universe_daily_data_skips_events(tmp_path: Path, monkeypatch):
    calls = []

    def fake_collect(code, trade_date, *, start_date=None, fields=None, refresh=False, data_dir=None):
        calls.append({"code": code, "fields": fields})
        return {"code": code, "errors": []}

    monkeypatch.setattr("libs.stock_data.universe.collect_stock_snapshot", fake_collect)

    result = collect_universe_daily_data(
        "2026-06-05",
        start_date="2025-12-01",
        codes=["000001", "300750", "688001", "600519"],
        data_dir=tmp_path / "stock-data",
    )

    assert result["code"].tolist() == ["000001", "600519"]
    assert all(call["fields"] == ["daily_raw", "daily_qfq", "features"] for call in calls)
    assert (tmp_path / "stock-data" / "by-date" / "2026-06-05" / "batch_collect_results.csv").exists()
    assert (tmp_path / "stock-data" / "by-date" / "2026-06-05" / "batch_collect_errors.csv").exists()
