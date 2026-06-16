import unittest

from intraday_t.live import format_collection_summary
from intraday_t.models import Snapshot


class LiveTest(unittest.TestCase):
    def test_format_collection_summary_prints_latest_snapshot(self) -> None:
        latest = {
            "605589": Snapshot(
                ts="2026-06-08T13:55:33+08:00",
                source="baidu_ws",
                code="605589",
                price=50.06,
                avg_price=51.05,
                ratio=-4.54,
            )
        }
        counts = {"605589": 8}

        output = format_collection_summary(["605589", "601208"], counts, latest)

        self.assertIn("605589 8条 最新50.06", output)
        self.assertIn("VWAP51.05", output)
        self.assertIn("601208 等待快照", output)


if __name__ == "__main__":
    unittest.main()
