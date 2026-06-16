import pandas as pd
from pathlib import Path

from libs.stock_data.reversal import find_reversal_signal, list_local_symbols, scan_reversal_signals
from libs.stock_data.store import write_dataframe


def test_find_reversal_signal_detects_stop_fall_breakout():
    rows = _build_reversal_rows("002475")

    signal = find_reversal_signal(pd.DataFrame(rows), "2026-04-28", params={"lookback": 90, "volume_ratio_min": 1.5})

    assert signal is not None
    assert signal["stop_fall_date"] == "2026-03-24"
    assert signal["signal_date"] == "2026-03-25"
    assert signal["ma_break_count"] >= 3


def test_scan_reversal_signals_uses_local_symbols(tmp_path: Path):
    root = tmp_path / "stock-data"
    rows = _build_reversal_rows("002475")
    symbol_dir = root / "by-symbol" / "002475"
    write_dataframe(symbol_dir / "daily_qfq.csv", pd.DataFrame(rows))
    write_dataframe(symbol_dir / "daily_raw.csv", pd.DataFrame(rows))

    result = scan_reversal_signals(None, "2026-04-28", data_dir=root, params={"lookback": 90, "volume_ratio_min": 1.5})

    assert list_local_symbols(root) == ["002475"]
    assert len(result) == 1
    assert result.iloc[0]["code"] == "002475"
    assert (root / "by-date" / "2026-04-28" / "reversal_signals.csv").exists()
    assert (root / "by-date" / "2026-04-28" / "reversal_confirmed.csv").exists()
    assert (root / "by-date" / "2026-04-28" / "reversal_errors.csv").exists()


def _build_reversal_rows(code: str):
    rows = []
    for i in range(45):
        rows.append({"trade_date": f"2026-01-{(i % 28) + 1:02d}", "code": code, "open": 10, "high": 10.2, "low": 9.8, "close": 10, "volume": 1000, "amount_yuan": 10000, "is_tradable": True, "is_suspended": False, "is_limit_up": False})
    rows.append({"trade_date": "2026-03-24", "code": code, "open": 9.8, "high": 10.1, "low": 8.8, "close": 9.9, "volume": 1000, "amount_yuan": 10000, "is_tradable": True, "is_suspended": False, "is_limit_up": False})
    rows.append({"trade_date": "2026-03-25", "code": code, "open": 10.0, "high": 11.5, "low": 9.9, "close": 11.3, "volume": 2500, "amount_yuan": 25000, "is_tradable": True, "is_suspended": False, "is_limit_up": False})
    for i in range(30):
        rows.append({"trade_date": f"2026-04-{(i % 28) + 1:02d}", "code": code, "open": 11.3 + i * 0.1, "high": 11.6 + i * 0.1, "low": 11 + i * 0.1, "close": 11.4 + i * 0.1, "volume": 1400, "amount_yuan": 14000, "is_tradable": True, "is_suspended": False, "is_limit_up": False})
    return rows
