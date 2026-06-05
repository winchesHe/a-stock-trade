import json
import tempfile
import unittest
from pathlib import Path

from intraday_t.models import Snapshot, parse_codes
from intraday_t.storage import RawSnapshotWriter, raw_snapshot_path


class StorageTest(unittest.TestCase):
    def test_parse_codes_deduplicates_and_normalizes(self) -> None:
        self.assertEqual(parse_codes("002463, sz600941,002463"), ["002463", "600941"])


    def test_raw_snapshot_writer_appends_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            writer = RawSnapshotWriter(tmp_path, "2026-06-05")
            snapshot = Snapshot(ts="2026-06-05T09:31:02+08:00", source="baidu_ws", code="002463", price=133.22)

            path = writer.write(snapshot)

            self.assertEqual(path, raw_snapshot_path(tmp_path, "002463", "2026-06-05"))
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["price"], 133.22)


if __name__ == "__main__":
    unittest.main()
