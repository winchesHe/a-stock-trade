import json
import tempfile
import unittest
from pathlib import Path

from intraday_t.models import Signal
from intraday_t.monitor import format_signal, run_once
from intraday_t.storage import raw_snapshot_path, signal_path


class MonitorTest(unittest.TestCase):
    def test_format_signal_prints_trade_context(self) -> None:
        signal = Signal(
            ts="2026-06-05T10:12:00+08:00",
            code="605589",
            signal="low_buy",
            strength=74,
            action="低吸计划 T 仓",
            position_required=True,
            price=50.31,
            reference_price=51.051,
            stop_condition="放量跌破日内低点则取消低吸信号",
            reasons=["价格低于 VWAP 1.45%", "价格接近日内低点"],
            strategy="vwap_pullback_low_buy",
            regime="strong_trend",
            position_state="base_available",
        )

        output = format_signal(signal)

        self.assertIn("605589", output)
        self.assertIn("low_buy", output)
        self.assertIn("50.31", output)
        self.assertIn("VWAP 51.05", output)
        self.assertIn("低吸计划 T 仓", output)
        self.assertIn("价格低于 VWAP 1.45%", output)
        self.assertIn("vwap_pullback_low_buy/strong_trend/base_available", output)

    def test_run_once_aggregates_and_returns_latest_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            raw_path = raw_snapshot_path(base_dir, "002463", "2026-06-05")
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            rows = [
                {
                    "ts": "2026-06-05T10:12:02+08:00",
                    "source": "baidu_ws",
                    "code": "002463",
                    "price": 99.0,
                    "avg_price": 100.0,
                    "open": 101.0,
                    "pre_close": 102.0,
                    "amount": 1000.0,
                    "volume": 10.0,
                },
                {
                    "ts": "2026-06-05T10:12:45+08:00",
                    "source": "baidu_ws",
                    "code": "002463",
                    "price": 98.5,
                    "avg_price": 100.0,
                    "open": 101.0,
                    "pre_close": 102.0,
                    "amount": 1200.0,
                    "volume": 12.0,
                },
            ]
            raw_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

            lines = run_once(base_dir, ["002463"], "2026-06-05", has_position=True, opening_minutes=5)

            self.assertEqual(len(lines), 1)
            self.assertIn("002463", lines[0])
            self.assertIn("low_buy", lines[0])
            self.assertTrue(signal_path(base_dir, "002463", "2026-06-05").exists())


if __name__ == "__main__":
    unittest.main()
