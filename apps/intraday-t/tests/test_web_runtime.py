import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path

from intraday_t.models import Snapshot
from intraday_t.storage import raw_snapshot_path, signal_path
from intraday_t.web_runtime import (
    DashboardCodeData,
    WebCollectorSession,
    WebUiConfig,
    build_signal_board_rows,
    load_web_config,
    latest_actionable_signals,
    load_dashboard_data,
    refresh_signals,
    reset_web_config,
    save_web_config,
)


class WebRuntimeTest(unittest.TestCase):
    def write_raw_rows(self, base_dir: Path, code: str = "002463") -> None:
        path = raw_snapshot_path(base_dir, code, "2026-06-05")
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {
                "ts": "2026-06-05T10:12:02+08:00",
                "source": "baidu_ws",
                "code": code,
                "name": "沪电股份",
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
                "code": code,
                "name": "沪电股份",
                "price": 98.5,
                "avg_price": 100.0,
                "open": 101.0,
                "pre_close": 102.0,
                "amount": 1200.0,
                "volume": 12.0,
            },
        ]
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    def test_load_dashboard_data_reads_existing_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            self.write_raw_rows(base_dir)
            refresh_signals(base_dir, ["002463"], "2026-06-05", has_position=True, opening_minutes=5)

            rows = load_dashboard_data(base_dir, ["002463"], "2026-06-05")

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].code, "002463")
            self.assertEqual(rows[0].raw_count, 2)
            self.assertEqual(rows[0].minute_count, 1)
            self.assertEqual(rows[0].signal_count, 1)
            self.assertEqual(rows[0].latest_snapshot["price"], 98.5)
            self.assertEqual(rows[0].latest_signal["signal"], "low_buy")

    def test_refresh_signals_writes_signal_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            self.write_raw_rows(base_dir)

            lines = refresh_signals(base_dir, ["002463"], "2026-06-05", has_position=True, opening_minutes=5)

            self.assertEqual(len(lines), 1)
            self.assertIn("002463", lines[0])
            self.assertTrue(signal_path(base_dir, "002463", "2026-06-05").exists())

    def test_collector_session_records_snapshots_and_stops(self) -> None:
        async def fake_stream(codes, timeout=None):
            for index in range(3):
                await asyncio.sleep(0.01)
                yield Snapshot(
                    ts=f"2026-06-05T10:12:0{index}+08:00",
                    source="fake",
                    code=list(codes)[0],
                    price=99.0 + index,
                    avg_price=100.0,
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            session = WebCollectorSession(stream_factory=fake_stream)
            session.start(["002463"], Path(temp_dir), "2026-06-05", timeout=0.1)
            time.sleep(0.08)
            session.stop()

            status = session.status()
            self.assertFalse(status.running)
            self.assertEqual(status.codes, ["002463"])
            self.assertGreaterEqual(status.counts.get("002463", 0), 1)
            self.assertIsNone(status.error)
            self.assertTrue(raw_snapshot_path(Path(temp_dir), "002463", "2026-06-05").exists())

    def test_collector_session_records_stream_errors(self) -> None:
        async def broken_stream(codes, timeout=None):
            raise RuntimeError("ws failed")
            yield

        with tempfile.TemporaryDirectory() as temp_dir:
            session = WebCollectorSession(stream_factory=broken_stream)
            session.start(["002463"], Path(temp_dir), "2026-06-05", timeout=0.1)
            time.sleep(0.05)

            status = session.status()
            self.assertFalse(status.running)
            self.assertIn("ws failed", status.error or "")

    def test_latest_actionable_signals_filters_and_sorts_latest_signals(self) -> None:
        rows = [
            DashboardCodeData(
                code="002463",
                raw_count=0,
                minute_count=0,
                signal_count=1,
                latest_snapshot=None,
                latest_signal={"signal": "hold", "strength": 90},
                minute_rows=[],
                signal_rows=[],
            ),
            DashboardCodeData(
                code="600941",
                raw_count=0,
                minute_count=0,
                signal_count=1,
                latest_snapshot=None,
                latest_signal={"signal": "low_buy", "strength": 70, "action": "低吸计划 T 仓"},
                minute_rows=[],
                signal_rows=[],
            ),
            DashboardCodeData(
                code="603986",
                raw_count=0,
                minute_count=0,
                signal_count=1,
                latest_snapshot=None,
                latest_signal={"signal": "high_sell", "strength": 86, "action": "高抛部分底仓"},
                minute_rows=[],
                signal_rows=[],
            ),
        ]

        signals = latest_actionable_signals(rows)

        self.assertEqual([item["code"] for item in signals], ["603986", "600941"])
        self.assertEqual([item["signal"] for item in signals], ["high_sell", "low_buy"])

    def test_build_signal_board_rows_merges_action_and_rate_fields(self) -> None:
        rows = [
            DashboardCodeData(
                code="002463",
                raw_count=3,
                minute_count=2,
                signal_count=1,
                latest_snapshot={"price": 140.64, "avg_price": 139.2, "ratio": 5.14, "ts": "2026-06-16T10:00:00+08:00"},
                latest_signal={
                    "ts": "2026-06-16T10:00:00+08:00",
                    "signal": "high_sell",
                    "strength": 86,
                    "price": 140.64,
                    "reference_price": 139.2,
                    "action": "高抛部分底仓",
                    "reasons": ["冲高不过前高"],
                    "stop_condition": "放量突破前高则取消",
                },
                minute_rows=[],
                signal_rows=[],
            ),
            DashboardCodeData(
                code="600941",
                raw_count=1,
                minute_count=1,
                signal_count=1,
                latest_snapshot={"price": 99.0, "avg_price": 100.0, "ratio": -1.2},
                latest_signal={"signal": "hold", "strength": 90, "price": 99.0, "reference_price": 100.0},
                minute_rows=[],
                signal_rows=[],
            ),
        ]

        board_rows = build_signal_board_rows(rows, names_by_code={"002463": "沪电股份"})

        self.assertEqual(board_rows[0]["code"], "002463")
        self.assertEqual(board_rows[0]["名称"], "沪电股份")
        self.assertEqual(board_rows[0]["操作"], "高抛")
        self.assertEqual(board_rows[0]["涨跌幅%"], 5.14)
        self.assertAlmostEqual(board_rows[0]["偏离参考%"], 1.034482758620682)
        self.assertEqual(board_rows[0]["动作"], "高抛部分底仓")
        self.assertEqual(board_rows[1]["操作"], "")

    def test_web_config_save_load_and_reset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "web_config.json"
            config = WebUiConfig(
                stocks_text="沪电股份,中国移动",
                day="2026-06-16",
                data_dir="/tmp/intraday",
                has_position=False,
                opening_minutes=8,
                timeout=12.0,
                limit=120,
                auto_refresh=True,
                refresh_interval=9.0,
            )

            save_web_config(config, path)
            loaded = load_web_config(path)

            self.assertEqual(loaded.stocks_text, "沪电股份,中国移动")
            self.assertEqual(loaded.opening_minutes, 8)
            self.assertTrue(loaded.auto_refresh)
            self.assertTrue(path.exists())

            reset_web_config(path)
            self.assertFalse(path.exists())

    def test_web_config_ignores_bad_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "web_config.json"
            path.write_text("not json", encoding="utf-8")

            config = load_web_config(path)

            self.assertEqual(config.stocks_text, "002463")


if __name__ == "__main__":
    unittest.main()
