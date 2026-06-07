"""Path helpers for stock data stored inside the repository."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """Return the repository root by walking up from this file."""
    return Path(__file__).resolve().parents[2]


def stock_data_dir(data_dir: str | Path | None = None) -> Path:
    """Return the root directory for stock data assets.

    The default is always inside the current repository: ``data/stock-data``.
    """
    root = Path(data_dir) if data_dir is not None else repo_root() / "data" / "stock-data"
    return root.expanduser().resolve()


def symbol_data_dir(code: str, data_dir: str | Path | None = None) -> Path:
    """Return ``by-symbol/<code>`` under the stock data root."""
    clean_code = normalize_code(code)
    return stock_data_dir(data_dir) / "by-symbol" / clean_code


def snapshot_path(code: str, trade_date: str, data_dir: str | Path | None = None) -> Path:
    """Return the snapshot path for ``code`` and ``trade_date``."""
    return symbol_data_dir(code, data_dir) / "snapshots" / f"{trade_date}.json"


def normalize_code(code: str) -> str:
    """Normalize supported A-share code formats to a pure 6-digit code."""
    clean = str(code).strip().upper()
    for suffix in (".SH", ".SZ", ".BJ"):
        if clean.endswith(suffix):
            clean = clean[: -len(suffix)]
            break
    for prefix in ("SH", "SZ", "BJ"):
        if clean.startswith(prefix):
            clean = clean[len(prefix) :]
            break
    if not (clean.isdigit() and len(clean) == 6):
        raise ValueError(f"股票代码必须是 6 位数字: {code}")
    return clean
