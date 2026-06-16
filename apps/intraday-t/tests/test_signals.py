import json
import tempfile
import unittest
from pathlib import Path

from intraday_t.models import MinuteBar, PositionContext
from intraday_t.signals import (
    classify_intraday_context,
    evaluate_bar,
    evaluate_latest_bar,
    generate_signals_for_code,
    position_context_from_flags,
    position_state,
)
from intraday_t.storage import minute_bar_path


class SignalsTest(unittest.TestCase):
    def make_bar(
        self,
        deviation: float | None,
        minute: str = "2026-06-05T10:00:00+08:00",
        *,
        close: float | None = None,
        high: float | None = None,
        low: float | None = None,
        vwap: float | None = 100.0,
        amount_delta: float | None = 1000.0,
        volume_delta: float | None = 10.0,
        price_vs_open_pct: float | None = 0.0,
        price_vs_pre_close_pct: float | None = 0.0,
    ) -> MinuteBar:
        if deviation is None:
            effective_vwap = None
            effective_close = close if close is not None else 102.0
        else:
            effective_vwap = vwap
            effective_close = close if close is not None else (102.0 if deviation >= 0 else 98.0)
        return MinuteBar(
            minute=minute,
            code="002463",
            open=100.0,
            high=high if high is not None else max(103.0, effective_close),
            low=low if low is not None else min(98.0, effective_close),
            close=effective_close,
            vwap=effective_vwap,
            amount_delta=amount_delta,
            volume_delta=volume_delta,
            price_vs_vwap_pct=deviation,
            price_vs_open_pct=price_vs_open_pct,
            price_vs_pre_close_pct=price_vs_pre_close_pct,
            day_high_so_far=high if high is not None else max(103.0, effective_close),
            day_low_so_far=low if low is not None else min(98.0, effective_close),
        )

    def make_series(self, closes: list[float], *, start_minute: int = 0, vwap: float = 100.0) -> list[MinuteBar]:
        bars: list[MinuteBar] = []
        day_high = max(closes[0], vwap)
        day_low = min(closes[0], vwap)
        for index, close in enumerate(closes):
            day_high = max(day_high, close)
            day_low = min(day_low, close)
            deviation = (close - vwap) / vwap * 100
            bars.append(
                self.make_bar(
                    deviation,
                    f"2026-06-05T10:{start_minute + index:02d}:00+08:00",
                    close=close,
                    high=max(close, day_high),
                    low=min(close, day_low),
                    vwap=vwap,
                    amount_delta=1000.0 - index * 30,
                    volume_delta=10.0 - index * 0.2,
                    price_vs_open_pct=close - 100.0,
                    price_vs_pre_close_pct=close - 100.0,
                )
            )
        return bars

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

    def test_position_context_states(self) -> None:
        self.assertEqual(position_state(position_context_from_flags(has_position=False)), "no_base_position")
        self.assertEqual(position_state(position_context_from_flags(has_position=True)), "base_available")
        self.assertEqual(position_state(PositionContext(opened_side="sold", opened_price=102.0)), "sold_waiting_cover")
        self.assertEqual(position_state(PositionContext(opened_side="bought", opened_price=98.0)), "bought_waiting_sell")

    def test_latest_signal_respects_position_state(self) -> None:
        no_position = evaluate_latest_bar(self.make_series([100.0, 101.0, 102.0]), position=PositionContext(has_base_position=False))
        self.assertEqual(no_position.signal, "forbidden")
        self.assertEqual(no_position.position_state, "no_base_position")

        cover = evaluate_latest_bar(
            self.make_series([102.0, 101.0, 100.5]),
            position=PositionContext(opened_side="sold", opened_price=102.0),
        )
        self.assertEqual(cover.signal, "cover_back")
        self.assertEqual(cover.position_state, "sold_waiting_cover")

        sell = evaluate_latest_bar(
            self.make_series([98.0, 99.0, 99.2]),
            position=PositionContext(opened_side="bought", opened_price=98.0),
        )
        self.assertEqual(sell.signal, "high_sell")
        self.assertEqual(sell.position_state, "bought_waiting_sell")

    def test_classify_intraday_context_core_regimes(self) -> None:
        strong = classify_intraday_context(self.make_series([100.4, 101.0, 101.5, 102.0, 102.4, 102.8]))
        self.assertEqual(strong.regime, "strong_trend")

        weak = classify_intraday_context(self.make_series([99.6, 99.0, 98.5, 98.0, 97.6, 97.2]))
        self.assertEqual(weak.regime, "weak_trend")

        range_bound = classify_intraday_context(self.make_series([100.1, 99.9, 100.2, 99.8, 100.1, 100.0]))
        self.assertEqual(range_bound.regime, "range_bound")

    def test_classify_opening_failed_breakout(self) -> None:
        bars = [
            self.make_bar(0.1, "2026-06-05T09:30:00+08:00", close=100.1, high=100.2, low=99.8),
            self.make_bar(0.2, "2026-06-05T09:31:00+08:00", close=100.2, high=100.3, low=99.9),
            self.make_bar(1.4, "2026-06-05T09:32:00+08:00", close=101.4, high=101.6, low=100.5),
            self.make_bar(-0.3, "2026-06-05T09:33:00+08:00", close=99.7, high=100.2, low=99.5),
        ]

        context = classify_intraday_context(bars, opening_range_minutes=2)

        self.assertEqual(context.regime, "opening_failed_breakout")
        self.assertIn("开盘区间突破失败", "；".join(context.reasons))

    def test_vwap_pullback_low_buy_strategy(self) -> None:
        bars = self.make_series([101.0, 102.0, 102.8, 100.2, 100.9])

        signal = evaluate_latest_bar(bars, position=PositionContext())

        self.assertEqual(signal.signal, "low_buy")
        self.assertEqual(signal.strategy, "vwap_pullback_low_buy")
        self.assertEqual(signal.regime, "strong_trend")
        self.assertIn("VWAP 回踩", "；".join(signal.reasons))

    def test_failed_second_high_sell_strategy(self) -> None:
        bars = self.make_series([101.0, 103.0, 105.0, 103.4, 104.7, 104.0])

        signal = evaluate_latest_bar(bars, position=PositionContext())

        self.assertEqual(signal.signal, "high_sell")
        self.assertEqual(signal.strategy, "failed_second_high_sell")
        self.assertIn("二次冲高未突破前高", "；".join(signal.reasons))

    def test_second_low_reversal_buy_strategy(self) -> None:
        bars = self.make_series([99.0, 97.0, 95.0, 96.3, 95.3, 96.1])

        signal = evaluate_latest_bar(bars, position=PositionContext())

        self.assertEqual(signal.signal, "low_buy")
        self.assertEqual(signal.strategy, "second_low_reversal_buy")
        self.assertIn("二次下探未破前低", "；".join(signal.reasons))

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
            saved_rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
            self.assertIn("strategy", saved_rows[-1])
            self.assertIn("regime", saved_rows[-1])
            self.assertIn("position_state", saved_rows[-1])


if __name__ == "__main__":
    unittest.main()
