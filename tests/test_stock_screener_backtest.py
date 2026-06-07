from pathlib import Path

import pandas as pd

from libs.stock_data.backtest import backtest_signal
from libs.stock_data.screener import screen_stocks
from libs.stock_data.store import replace_events, write_dataframe


def _seed_symbol(root: Path, code: str = "002463"):
    symbol_dir = root / "by-symbol" / code
    raw = pd.DataFrame(
        [
            {"trade_date": "2026-06-01", "code": code, "open": 10, "high": 11, "low": 9.8, "close": 10, "is_tradable": True, "is_suspended": False, "is_st": False, "is_limit_down": False, "is_limit_up": False},
            {"trade_date": "2026-06-02", "code": code, "open": 10.2, "high": 11.5, "low": 10, "close": 11, "is_tradable": True, "is_suspended": False, "is_st": False, "is_limit_down": False, "is_limit_up": False},
            {"trade_date": "2026-06-03", "code": code, "open": 11.2, "high": 12, "low": 10.8, "close": 11.8, "is_tradable": True, "is_suspended": False, "is_st": False, "is_limit_down": False, "is_limit_up": False},
            {"trade_date": "2026-06-04", "code": code, "open": 11.9, "high": 12.2, "low": 11.2, "close": 12, "is_tradable": True, "is_suspended": False, "is_st": False, "is_limit_down": False, "is_limit_up": False},
        ]
    )
    features = pd.DataFrame(
        [
            {"trade_date": "2026-06-02", "code": code, "ma5": 10, "ma10": 9.8, "ma20": 9.5, "return_5d": 5, "drawdown_20d": -4, "volume_ratio_20d": 1.5},
        ]
    )
    write_dataframe(symbol_dir / "daily_raw.csv", raw)
    write_dataframe(symbol_dir / "daily_qfq.csv", raw)
    write_dataframe(symbol_dir / "features.csv", features)
    replace_events(
        symbol_dir / "events.jsonl",
        [{"code": code, "event_type": "dragon_tiger", "effective_date": "2026-05-26"}],
    )


def test_screen_stocks_scores_matching_candidate(tmp_path: Path):
    root = tmp_path / "stock-data"
    _seed_symbol(root)

    result = screen_stocks(["002463"], "2026-06-02", data_dir=root)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["code"] == "002463"
    assert row["dragon_tiger_count_30d"] == 1
    assert "站上 MA5" in row["reasons"]


def test_screen_stocks_filters_failed_candidate(tmp_path: Path):
    root = tmp_path / "stock-data"
    _seed_symbol(root)
    features_path = root / "by-symbol" / "002463" / "features.csv"
    features = pd.read_csv(features_path, dtype={"code": str})
    features.loc[0, "ma5"] = 99
    write_dataframe(features_path, features)

    result = screen_stocks(["002463"], "2026-06-02", data_dir=root)

    assert result.empty


def test_backtest_signal_computes_return_and_drawdown(tmp_path: Path):
    root = tmp_path / "stock-data"
    _seed_symbol(root)

    result = backtest_signal("002463", "2026-06-01", holding_days=2, data_dir=root)

    assert result["blocked"] is False
    assert result["entry_date"] == "2026-06-02"
    assert round(result["return_pct"], 2) == round((11.8 / 10.2 - 1) * 100, 2)
    assert result["max_drawdown_pct"] <= 0


def test_backtest_signal_blocks_limit_up_entry(tmp_path: Path):
    root = tmp_path / "stock-data"
    _seed_symbol(root)
    raw_path = root / "by-symbol" / "002463" / "daily_raw.csv"
    raw = pd.read_csv(raw_path, dtype={"code": str})
    raw.loc[1, "is_limit_up"] = True
    write_dataframe(raw_path, raw)

    result = backtest_signal("002463", "2026-06-01", data_dir=root)

    assert result["blocked"] is True
    assert "涨停" in result["block_reason"]
