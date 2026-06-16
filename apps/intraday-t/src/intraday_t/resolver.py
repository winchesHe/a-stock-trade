from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .collector import APP_ROOT
from .models import normalize_code

_CODE_RE = re.compile(r"\d{6}")
_HAS_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
_DEFAULT_NAME_TO_CODE = {
    "沪电股份": "002463",
    "京东方A": "000725",
    "京东方Ａ": "000725",
    "京东方": "000725",
    "中国移动": "600941",
}


@dataclass(slots=True)
class ResolvedStocks:
    codes: list[str]
    names_by_code: dict[str, str] = field(default_factory=dict)


class StockResolver:
    def __init__(
        self,
        *,
        name_to_code: dict[str, str] | None = None,
        code_to_name: dict[str, str] | None = None,
        cache_path: Path | None = None,
        allow_mootdx: bool = False,
    ) -> None:
        self.cache_path = cache_path or APP_ROOT / "data" / "stock_names.json"
        self.allow_mootdx = allow_mootdx
        self._cache_loaded = False
        self._name_to_code = {self._clean_name(name): normalize_code(code) for name, code in (name_to_code or {}).items()}
        self._code_to_name = {normalize_code(code): self._clean_name(name) for code, name in (code_to_name or {}).items()}
        for name, code in self._name_to_code.items():
            self._code_to_name.setdefault(code, name)

    @staticmethod
    def _clean_name(value: str) -> str:
        return str(value).replace("\x00", "").strip().replace(" ", "").replace("　", "")

    def resolve(self, value: str) -> tuple[str, str | None]:
        text = str(value).strip()
        if not text:
            raise ValueError("股票输入不能为空")
        if not _HAS_CHINESE_RE.search(text):
            code = normalize_code(text)
            return code, self._known_name_for_code(code)

        name = self._clean_name(text)
        name_to_code, code_to_name = self._maps()
        if name in name_to_code:
            code = name_to_code[name]
            return code, code_to_name.get(code, name)

        matches = {stock_name: code for stock_name, code in name_to_code.items() if name in stock_name}
        if len(matches) == 1:
            stock_name, code = next(iter(matches.items()))
            return code, stock_name
        if len(matches) > 1:
            examples = "，".join(f"{stock_name}({code})" for stock_name, code in list(matches.items())[:5])
            raise ValueError(f"'{text}' 匹配到多只股票：{examples}，请输入完整名称或代码")
        raise ValueError(f"找不到股票 '{text}'，请先输入 6 位代码采集一次，或确认 mootdx 可用")

    def name_for_code(self, code: str) -> str | None:
        safe_code = normalize_code(code)
        _, code_to_name = self._maps()
        return code_to_name.get(safe_code)

    def _known_name_for_code(self, code: str) -> str | None:
        safe_code = normalize_code(code)
        if safe_code in self._code_to_name:
            return self._code_to_name[safe_code]
        self._ensure_cache_maps()
        return self._code_to_name.get(safe_code)

    def _maps(self) -> tuple[dict[str, str], dict[str, str]]:
        if self._name_to_code and not self.allow_mootdx:
            return self._name_to_code, self._code_to_name

        self._ensure_cache_maps()
        if self._name_to_code and not self.allow_mootdx:
            return self._name_to_code, self._code_to_name

        if not self.allow_mootdx:
            return self._name_to_code, self._code_to_name

        try:
            self._load_mootdx()
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("名称解析暂不可用：mootdx 连接超时或服务器不可用；请先输入 6 位股票代码") from exc
        if self._name_to_code:
            self._write_cache()
        return self._name_to_code, self._code_to_name

    def _ensure_cache_maps(self) -> None:
        if self._cache_loaded:
            return
        self._load_cache()
        self._seed_default_names()
        self._cache_loaded = True

    def _seed_default_names(self) -> None:
        for name, code in _DEFAULT_NAME_TO_CODE.items():
            safe_code = normalize_code(code)
            clean_name = self._clean_name(name)
            self._name_to_code.setdefault(clean_name, safe_code)
            self._code_to_name.setdefault(safe_code, clean_name)

    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        name_to_code = payload.get("name_to_code") if isinstance(payload, dict) else None
        code_to_name = payload.get("code_to_name") if isinstance(payload, dict) else None
        if isinstance(name_to_code, dict):
            self._name_to_code.update({self._clean_name(name): normalize_code(code) for name, code in name_to_code.items()})
        if isinstance(code_to_name, dict):
            self._code_to_name.update({normalize_code(code): self._clean_name(name) for code, name in code_to_name.items()})
        for name, code in self._name_to_code.items():
            self._code_to_name.setdefault(code, name)
        for code, name in self._code_to_name.items():
            if name:
                self._name_to_code.setdefault(name, code)

    def _load_mootdx(self) -> None:
        try:
            from mootdx.quotes import Quotes
        except ImportError as exc:
            raise ValueError("名称解析需要 mootdx 或本地 stock_names.json 缓存；也可以直接输入 6 位股票代码") from exc

        try:
            client = Quotes.factory(market="std")
            for market in (0, 1):
                stocks = client.stocks(market=market)
                if stocks is None or getattr(stocks, "empty", False):
                    continue
                for _, row in stocks.iterrows():
                    code = str(row.get("code", "")).strip()
                    name = self._clean_name(str(row.get("name", "")))
                    if not name or not _CODE_RE.fullmatch(code):
                        continue
                    safe_code = normalize_code(code)
                    self._name_to_code[name] = safe_code
                    self._code_to_name[safe_code] = name
        except Exception as exc:
            raise ValueError("名称解析暂不可用：mootdx 连接超时或服务器不可用；请先输入 6 位股票代码") from exc

    def _write_cache(self) -> None:
        payload: dict[str, Any] = {"name_to_code": self._name_to_code, "code_to_name": self._code_to_name}
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        except OSError:
            return


def parse_stock_inputs(value: str, *, resolver: StockResolver | None = None) -> ResolvedStocks:
    stock_resolver = resolver or StockResolver()
    codes: list[str] = []
    names_by_code: dict[str, str] = {}
    for item in value.replace(";", ",").replace("，", ",").split(","):
        if not item.strip():
            continue
        code, name = stock_resolver.resolve(item)
        if code not in codes:
            codes.append(code)
        if name:
            names_by_code[code] = name
    if not codes:
        raise ValueError("至少需要提供一个股票代码或股票名称")
    return ResolvedStocks(codes=codes, names_by_code=names_by_code)
