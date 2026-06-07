from pathlib import Path

import pandas as pd

from libs.stock_data import collect_stock_snapshot
from libs.stock_data.paths import stock_data_dir, symbol_data_dir
from libs.stock_data.providers import _event_source_error, _float_or_none
from libs.stock_data.store import load_daily_bars, load_events, load_stock_snapshot


class FakeProvider:
    def __init__(self):
        self.calls = 0

    def daily_raw(self, code, start_date, end_date):
        self.calls += 1
        return pd.DataFrame(
            [
                {
                    "trade_date": "2026-06-01",
                    "code": code,
                    "name": "测试股",
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.8,
                    "close": 10.5,
                    "pre_close": 10.0,
                    "change": 0.5,
                    "change_pct": 5.0,
                    "volume": 1000,
                    "amount_yuan": 10500,
                    "turnover_rate_pct": 1.2,
                    "amplitude_pct": 12.0,
                    "limit_up": 11.0,
                    "limit_down": 9.0,
                    "is_limit_up": False,
                    "is_limit_down": False,
                    "is_tradable": True,
                    "is_suspended": False,
                    "is_st": False,
                    "board_type": "main",
                    "price_limit_pct": 10,
                    "source": "fake_raw",
                    "fetched_at": "2026-06-01T15:00:00",
                }
            ]
        )

    def daily_qfq(self, code, start_date, end_date):
        self.calls += 1
        return pd.DataFrame(
            [
                {
                    "trade_date": "2026-06-01",
                    "code": code,
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.8,
                    "close": 10.5,
                    "volume": 1000,
                    "amount_yuan": 10500,
                    "adjustment": "qfq",
                    "source": "fake_qfq",
                    "fetched_at": "2026-06-01T15:00:00",
                }
            ]
        )

    def quote(self, code):
        self.calls += 1
        return {
            "name": "测试股实时",
            "price": 10.5,
            "pe_ttm": 20,
            "pe_static": 18,
            "pb": 2.5,
            "quote_date": "2026-06-01",
            "turnover_rate_pct": 3.4,
            "limit_up": 12.0,
            "limit_down": 8.0,
            "market_cap_yuan": 1000000000,
            "float_market_cap_yuan": 800000000,
            "source": "fake_quote",
            "fetched_at": "2026-06-01T15:00:00",
        }

    def fundamentals(self, code):
        self.calls += 1
        return {"pe_ttm": 20, "source": "fake_fundamentals"}

    def events(self, code, trade_date):
        self.calls += 1
        return [
            {
                "event_id": f"{code}-{trade_date}-dragon",
                "code": code,
                "event_type": "dragon_tiger",
                "announce_date": trade_date,
                "effective_date": trade_date,
                "trade_date": trade_date,
                "usable_from": trade_date,
                "title": "龙虎榜测试",
                "summary": "测试事件",
                "value": 1,
                "value_unit": "count",
                "source": "fake_events",
                "fetched_at": "2026-06-01T15:00:00",
                "raw": {},
            }
        ]


def test_default_stock_data_dir_is_repo_local():
    path = stock_data_dir()
    assert path.name == "stock-data"
    assert path.parent.name == "data"
    assert ".tradingagents" not in str(path)


def test_collect_snapshot_writes_repo_local_files(tmp_path: Path):
    provider = FakeProvider()
    snapshot = collect_stock_snapshot(
        "002463",
        "2026-06-01",
        data_dir=tmp_path / "stock-data",
        provider=provider,
    )

    symbol_dir = symbol_data_dir("002463", tmp_path / "stock-data")
    assert snapshot["schema_version"] == 1
    assert snapshot["symbol_dir"] == str(symbol_dir)
    assert (symbol_dir / "daily_raw.csv").exists()
    assert (symbol_dir / "daily_qfq.csv").exists()
    assert (symbol_dir / "features.csv").exists()
    assert (symbol_dir / "events.jsonl").exists()
    assert (symbol_dir / "snapshots" / "2026-06-01.json").exists()
    assert (symbol_dir / "metadata.json").exists()
    assert ".tradingagents" not in snapshot["data_root"]

    loaded = load_stock_snapshot("002463", "2026-06-01", data_dir=tmp_path / "stock-data")
    assert loaded["latest"]["quote"]["price"] == 10.5
    raw = load_daily_bars("002463", adjustment="raw", data_dir=tmp_path / "stock-data")
    assert raw.iloc[0]["code"] == "002463"
    assert list(raw.columns)[:4] == ["trade_date", "code", "name", "open"]
    assert load_daily_bars("002463", adjustment="qfq", data_dir=tmp_path / "stock-data").iloc[0]["adjustment"] == "qfq"
    events = load_events("002463", event_type="dragon_tiger", data_dir=tmp_path / "stock-data")
    assert events
    assert events[0]["announce_date"] == "2026-06-01"
    assert events[0]["effective_date"] == "2026-06-01"
    assert events[0]["usable_from"] == "2026-06-01"


def test_collect_snapshot_uses_cache_unless_refresh(tmp_path: Path):
    provider = FakeProvider()
    collect_stock_snapshot("002463", "2026-06-01", data_dir=tmp_path / "stock-data", provider=provider)
    first_calls = provider.calls

    collect_stock_snapshot("002463", "2026-06-01", data_dir=tmp_path / "stock-data", provider=provider)
    assert provider.calls == first_calls

    collect_stock_snapshot(
        "002463",
        "2026-06-01",
        data_dir=tmp_path / "stock-data",
        provider=provider,
        refresh=True,
    )
    assert provider.calls > first_calls


def test_collect_snapshot_normalizes_prefixed_code(tmp_path: Path):
    provider = FakeProvider()
    snapshot = collect_stock_snapshot(
        "SZ002463",
        "2026-06-01",
        data_dir=tmp_path / "stock-data",
        provider=provider,
    )

    assert snapshot["code"] == "002463"
    assert "SZ002463" not in snapshot["symbol_dir"]


def test_daily_raw_uses_quote_only_for_matching_trade_date(tmp_path: Path):
    provider = FakeProvider()
    collect_stock_snapshot(
        "002463",
        "2026-06-01",
        data_dir=tmp_path / "current-stock-data",
        provider=provider,
    )
    current_raw = load_daily_bars("002463", adjustment="raw", data_dir=tmp_path / "current-stock-data")
    current_row = current_raw.iloc[0]
    assert current_row["name"] == "测试股实时"
    assert current_row["turnover_rate_pct"] == 3.4
    assert current_row["limit_up"] == 12.0
    assert current_row["limit_down"] == 8.0

    collect_stock_snapshot(
        "002463",
        "2026-06-02",
        data_dir=tmp_path / "history-stock-data",
        provider=provider,
    )
    history_raw = load_daily_bars("002463", adjustment="raw", data_dir=tmp_path / "history-stock-data")
    history_row = history_raw.iloc[0]
    assert history_row["name"] == "测试股"
    assert history_row["turnover_rate_pct"] == 1.2
    assert history_row["limit_up"] == 11.0
    assert history_row["limit_down"] == 9.0


def test_float_or_none_parses_numeric_text():
    assert _float_or_none("12.34") == 12.34
    assert _float_or_none("-") is None


def test_event_source_error_has_standard_event_shape():
    event = _event_source_error("002463", "2026-06-01", "fund_flow", RuntimeError("boom"))
    assert event["event_type"] == "event_source_error"
    assert event["announce_date"] == "2026-06-01"
    assert event["effective_date"] == "2026-06-01"
    assert event["usable_from"] == "2026-06-01"
    assert event["value_unit"] == "error"
