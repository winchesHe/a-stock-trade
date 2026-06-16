import tempfile
import unittest
from pathlib import Path

from intraday_t.resolver import StockResolver, parse_stock_inputs


class ResolverTest(unittest.TestCase):
    def test_parse_stock_inputs_accepts_codes_and_names(self) -> None:
        resolver = StockResolver(name_to_code={"沪电股份": "002463", "中国移动": "600941"})

        resolved = parse_stock_inputs("沪电股份,600941,沪电", resolver=resolver)

        self.assertEqual(resolved.codes, ["002463", "600941"])
        self.assertEqual(resolved.names_by_code["002463"], "沪电股份")
        self.assertEqual(resolved.names_by_code["600941"], "中国移动")

    def test_parse_stock_inputs_reports_unknown_name(self) -> None:
        resolver = StockResolver(name_to_code={"沪电股份": "002463"})

        with self.assertRaisesRegex(ValueError, "找不到股票"):
            parse_stock_inputs("不存在股份", resolver=resolver)

    def test_parse_stock_inputs_reports_ambiguous_name(self) -> None:
        resolver = StockResolver(name_to_code={"中信证券": "600030", "中信银行": "601998"})

        with self.assertRaisesRegex(ValueError, "匹配到多只股票"):
            parse_stock_inputs("中信", resolver=resolver)

    def test_resolver_reads_local_cache_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "stock_names.json"
            cache_path.write_text('{"name_to_code":{"沪电股份":"002463"},"code_to_name":{"002463":"沪电股份"}}', encoding="utf-8")
            resolver = StockResolver(cache_path=cache_path)

            self.assertEqual(resolver.resolve("沪电股份"), ("002463", "沪电股份"))

    def test_resolver_builds_name_index_from_code_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "stock_names.json"
            cache_path.write_text('{"code_to_name":{"002463":"沪电股份\\u0000"}}', encoding="utf-8")
            resolver = StockResolver(cache_path=cache_path)

            self.assertEqual(resolver.resolve("沪电股份"), ("002463", "沪电股份"))

    def test_resolver_wraps_mootdx_errors(self) -> None:
        class BrokenResolver(StockResolver):
            def _load_mootdx(self) -> None:
                raise TimeoutError("timed out")

        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = BrokenResolver(cache_path=Path(temp_dir) / "missing.json", allow_mootdx=True)

            with self.assertRaisesRegex(ValueError, "名称解析暂不可用"):
                resolver.resolve("沪电股份")

    def test_default_resolver_uses_builtin_names_without_mootdx(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = StockResolver(cache_path=Path(temp_dir) / "missing.json")

            self.assertEqual(resolver.resolve("沪电股份"), ("002463", "沪电股份"))


if __name__ == "__main__":
    unittest.main()
