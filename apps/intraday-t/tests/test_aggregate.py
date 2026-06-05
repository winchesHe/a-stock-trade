import json
import tempfile
import unittest
from pathlib import Path

from intraday_t.aggregate import aggregate_code, aggregate_snapshots
from intraday_t.models import Snapshot
from intraday_t.storage import raw_snapshot_path


class AggregateTest(unittest.TestCase):
    def test_aggregate_snapshots_generates_minute_bars(self) -> None:
        snapshots = [
            Snapshot(
                ts="2026-06-05T09:31:02+08:00",
                source="baidu_ws",
                code="002463",
                price=100.0,
                avg_price=99.0,
                open=98.0,
                pre_close=97.0,
                amount=1000.0,
                volume=10.0,
                turnover_ratio=0.1,
            ),
            Snapshot(
                ts="2026-06-05T09:31:45+08:00",
                source="baidu_ws",
                code="002463",
                price=102.0,
                avg_price=100.0,
                open=98.0,
                pre_close=97.0,
                amount=1300.0,
                volume=13.0,
                turnover_ratio=0.13,
            ),
            Snapshot(
                ts="2026-06-05T09:32:01+08:00",
                source="baidu_ws",
                code="002463",
                price=101.0,
                avg_price=100.5,
                open=98.0,
                pre_close=97.0,
                amount=1500.0,
                volume=15.0,
                turnover_ratio=0.15,
            ),
        ]

        bars = aggregate_snapshots(snapshots)

        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].minute, "2026-06-05T09:31:00+08:00")
        self.assertEqual(bars[0].open, 100.0)
        self.assertEqual(bars[0].high, 102.0)
        self.assertEqual(bars[0].low, 100.0)
        self.assertEqual(bars[0].close, 102.0)
        self.assertEqual(bars[0].amount_delta, 1300.0)
        self.assertEqual(bars[1].amount_delta, 200.0)
        self.assertEqual(bars[1].volume_delta, 2.0)
        self.assertEqual(bars[1].day_high_so_far, 102.0)
        self.assertEqual(bars[1].day_low_so_far, 100.0)

    def test_aggregate_code_writes_minute_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            raw_path = raw_snapshot_path(base_dir, "002463", "2026-06-05")
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            rows = [
                {"ts": "2026-06-05T09:31:02+08:00", "source": "baidu_ws", "code": "002463", "price": 100.0, "amount": 1000.0, "volume": 10.0},
                {"ts": "2026-06-05T09:31:32+08:00", "source": "baidu_ws", "code": "002463", "price": 101.0, "amount": 1200.0, "volume": 12.0},
            ]
            raw_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

            output_path, bars = aggregate_code(base_dir, "002463", "2026-06-05")

            self.assertEqual(len(bars), 1)
            self.assertTrue(output_path.exists())
            line = output_path.read_text(encoding="utf-8").strip()
            self.assertEqual(json.loads(line)["close"], 101.0)


if __name__ == "__main__":
    unittest.main()
