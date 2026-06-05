import json
import tempfile
import unittest
from pathlib import Path

from intraday_t.models import MinuteBar
from intraday_t.signals import evaluate_bar, generate_signals_for_code
from intraday_t.storage import minute_bar_path


class SignalsTest(unittest.TestCase):
    def make_bar(self, deviation: float | None, minute: str = "2026-06-05T10:00:00+08:00") -> MinuteBar:
        return MinuteBar(
            minute=minute,
            code="002463",
            open=100.0,
            high=103.0,
            low=98.0,
            close=102.0 if deviation is None or deviation >= 0 else 98.0,
            vwap=100.0 if deviation is not None else None,
            price_vs_vwap_pct=deviation,
            day_high_so_far=103.0,
            day_low_so_far=98.0,
        )

    def test_no_position_is_forbidden(self) -> None:
        signal = evaluate_bar(self.make_bar(2.0), has_position=False)

        self.assertEqual(signal.signal, "forbidden")
        self.assertIn("无底仓", signal.risk_flags)

    def test_missing_vwap_is_forbidden(self) -> None:
        signal = evaluate_bar(self.make_bar(None))

        self.assertEqual(signal.signal, "forbidden")
        self.assertIn("数据缺失", signal.risk_flags)

    def test_opening_window_is_forbidden(self) -> None:
        signal = evaluate_bar(self.make_bar(2.0, "2026-06-05T09:32:00+08:00"), opening_minutes=5)

        self.assertEqual(signal.signal, "forbidden")
        self.assertIn("开盘波动", signal.risk_flags)

    def test_outside_trading_session_is_forbidden(self) -> None:
        signal = evaluate_bar(self.make_bar(2.0, "2026-06-05T20:05:00+08:00"))

        self.assertEqual(signal.signal, "forbidden")
        self.assertIn("非交易时段", signal.risk_flags)

    def test_high_sell_low_buy_watch_and_hold(self) -> None:
        self.assertEqual(evaluate_bar(self.make_bar(1.5)).signal, "high_sell")
        self.assertEqual(evaluate_bar(self.make_bar(-1.5)).signal, "low_buy")
        self.assertEqual(evaluate_bar(self.make_bar(0.8)).signal, "watch")
        self.assertEqual(evaluate_bar(self.make_bar(0.2)).signal, "hold")

    def test_generate_signals_for_code_writes_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            path = minute_bar_path(base_dir, "002463", "2026-06-05")
            path.parent.mkdir(parents=True, exist_ok=True)
            rows = [self.make_bar(1.5).to_dict(), self.make_bar(0.2).to_dict()]
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

            output_path, signals = generate_signals_for_code(base_dir, "002463", "2026-06-05")

            self.assertEqual([item.signal for item in signals], ["high_sell", "hold"])
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
