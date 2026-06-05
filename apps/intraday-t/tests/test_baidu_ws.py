from datetime import datetime, timezone
import unittest

from intraday_t.baidu_ws import build_subscribe_message, normalize_snapshot


class BaiduWsTest(unittest.TestCase):
    def test_build_subscribe_message_supports_multiple_codes(self) -> None:
        message = build_subscribe_message(["002463", "600941"])

        self.assertEqual(message["method"], "subscribe")
        self.assertEqual(message["product"], "snapshot")
        self.assertEqual(
            message["items"],
            [
                {"code": "002463", "market": "ab", "financeType": "stock"},
                {"code": "600941", "market": "ab", "financeType": "stock"},
            ],
        )


    def test_normalize_snapshot_reads_baidu_shape(self) -> None:
        payload = {
            "data": {
                "code": "002463",
                "name": "沪电股份",
                "cur": {"price": "133.22", "ratio": "-5.40", "increase": "-7.60", "avgPrice": "136.45"},
                "pankouinfos": {
                    "open": "137.10",
                    "high": "141.28",
                    "low": "131.81",
                    "preClose": "140.82",
                    "amount": "13031904560",
                    "volume": "95505600",
                    "turnoverRatio": "4.97",
                },
            }
        }

        snapshot = normalize_snapshot(payload, datetime(2026, 6, 5, 1, 31, 2, tzinfo=timezone.utc))

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.code, "002463")
        self.assertEqual(snapshot.name, "沪电股份")
        self.assertEqual(snapshot.price, 133.22)
        self.assertEqual(snapshot.avg_price, 136.45)
        self.assertEqual(snapshot.pre_close, 140.82)
        self.assertEqual(snapshot.turnover_ratio, 4.97)

    def test_normalize_snapshot_reads_real_pankou_list_shape(self) -> None:
        payload = {
            "data": {
                "financeType": "stock",
                "code": "600941",
                "market": "ab",
                "cur": {"avgPrice": "97.66", "ratio": "-0.64%", "increase": "-0.63", "price": "97.33"},
                "pankouinfos": [
                    {"ename": "open", "value": "98.11", "originValue": 98.11},
                    {"ename": "high", "value": "98.48", "originValue": 98.48},
                    {"ename": "volume", "value": "7.61万手", "originValue": 7609022},
                    {"ename": "preClose", "value": "97.96", "originValue": 97.96},
                    {"ename": "low", "value": "97.00", "originValue": 97},
                    {"ename": "amount", "value": "7.43亿", "originValue": 743118455},
                    {"ename": "turnoverRatio", "value": "0.84%", "originValue": 0.84},
                ],
            }
        }

        snapshot = normalize_snapshot(payload)

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.ratio, -0.64)
        self.assertEqual(snapshot.open, 98.11)
        self.assertEqual(snapshot.volume, 7609022)
        self.assertEqual(snapshot.amount, 743118455)


if __name__ == "__main__":
    unittest.main()
