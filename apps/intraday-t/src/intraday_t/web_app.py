from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    src_dir = Path(__file__).resolve().parents[1]
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

from intraday_t.collector import DEFAULT_DATA_DIR
from intraday_t.resolver import ResolvedStocks, parse_stock_inputs
from intraday_t.storage import trading_day
from intraday_t.web_runtime import (
    WebCollectorSession,
    WebUiConfig,
    build_signal_board_rows,
    load_web_config,
    load_dashboard_data,
    refresh_signals,
    reset_web_config,
    save_web_config,
    snapshot_to_dict,
)


def _streamlit():
    import streamlit as st

    return st


def _format_price(value: Any) -> str:
    if value in (None, ""):
        return "N/A"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _format_ratio(value: Any) -> str:
    if value in (None, ""):
        return "N/A"
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _compact_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if isinstance(item.get("reasons"), list):
            item["reasons"] = "；".join(str(value) for value in item["reasons"])
        if isinstance(item.get("risk_flags"), list):
            item["risk_flags"] = "；".join(str(value) for value in item["risk_flags"])
        result.append(item)
    return result


def _highlight_signal_board(row):
    styles = ["" for _ in row.index]
    if row.get("操作"):
        styles = ["background-color: #3f1d1d; color: #ffdddd" for _ in row.index]
        for index, name in enumerate(row.index):
            if name in ("操作", "强度", "涨跌幅%", "偏离参考%", "动作"):
                styles[index] = "background-color: #7f1d1d; color: #ffffff; font-weight: 700"
    return styles


def _render_signal_board(rows: list[dict[str, Any]]) -> None:
    st = _streamlit()
    st.subheader("操作信号看板")
    if not rows:
        st.info("暂无看板数据。")
        return
    import pandas as pd

    column_order = [
        "code",
        "名称",
        "操作",
        "信号",
        "强度",
        "最新价",
        "涨跌幅%",
        "VWAP",
        "参考价",
        "偏离参考%",
        "动作",
        "原因",
        "失效条件",
        "更新时间",
    ]
    frame = pd.DataFrame(rows).reindex(columns=column_order)
    styled = frame.style.apply(_highlight_signal_board, axis=1).format(
        {
            "最新价": "{:.2f}",
            "涨跌幅%": "{:.2f}%",
            "VWAP": "{:.2f}",
            "参考价": "{:.2f}",
            "偏离参考%": "{:.2f}%",
        },
        na_rep="",
    )
    st.dataframe(
        styled,
        width="stretch",
        hide_index=True,
    )


def _ensure_session() -> WebCollectorSession:
    st = _streamlit()
    if "collector_session" not in st.session_state:
        st.session_state.collector_session = WebCollectorSession()
    return st.session_state.collector_session


def _parse_stocks_or_show_error(value: str) -> ResolvedStocks | None:
    st = _streamlit()
    try:
        return parse_stock_inputs(value)
    except ValueError as exc:
        st.error(str(exc))
        return None


def _current_config(
    *,
    stocks_text: str,
    day: str,
    data_dir: Path,
    has_position: bool,
    opening_minutes: int,
    timeout: float,
    limit: int,
    auto_refresh: bool,
    refresh_interval: float,
) -> WebUiConfig:
    return WebUiConfig(
        stocks_text=stocks_text,
        day=day or None,
        data_dir=str(data_dir),
        has_position=has_position,
        opening_minutes=int(opening_minutes),
        timeout=float(timeout),
        limit=int(limit),
        auto_refresh=auto_refresh,
        refresh_interval=float(refresh_interval),
    )


def render_app() -> None:
    st = _streamlit()
    st.set_page_config(page_title="实时做 T 工作台", layout="wide")
    st.title("实时做 T 工作台")
    st.warning("仅供人工辅助看盘，不构成交易建议，不接券商接口，不自动交易。")

    session = _ensure_session()
    config = load_web_config()

    with st.sidebar:
        st.header("运行参数")
        codes_text = st.text_input("股票代码或名称", value=config.stocks_text, help="多个用逗号分隔，例如 002463,沪电股份,中国移动")
        day = st.text_input("交易日", value=config.day or trading_day(), help="格式 YYYY-MM-DD，可填历史样例日期")
        data_dir = Path(st.text_input("数据目录", value=config.data_dir))
        has_position = st.checkbox("有底仓", value=config.has_position, help="关闭后只输出无底仓风险提示")
        opening_minutes = st.number_input("开盘禁交易分钟", min_value=0, max_value=60, value=config.opening_minutes, step=1)
        timeout = st.number_input("采集超时秒数", min_value=1.0, max_value=120.0, value=config.timeout, step=1.0)
        limit = st.number_input("表格最多行数", min_value=20, max_value=1000, value=config.limit, step=20)
        auto_refresh = st.checkbox("自动刷新页面", value=config.auto_refresh)
        refresh_interval = st.number_input("自动刷新间隔秒", min_value=3.0, max_value=120.0, value=config.refresh_interval, step=1.0)
        apply_col, reset_col = st.columns(2)
        with apply_col:
            if st.button("应用配置", width="stretch"):
                save_web_config(
                    _current_config(
                        stocks_text=codes_text,
                        day=day,
                        data_dir=data_dir,
                        has_position=has_position,
                        opening_minutes=int(opening_minutes),
                        timeout=float(timeout),
                        limit=int(limit),
                        auto_refresh=auto_refresh,
                        refresh_interval=float(refresh_interval),
                    )
                )
                st.success("配置已保存，下次打开会自动复用。")
        with reset_col:
            if st.button("重置配置", width="stretch"):
                reset_web_config()
                st.success("配置已重置，请刷新页面查看默认值。")

    resolved = _parse_stocks_or_show_error(codes_text)
    if resolved is None:
        return
    codes = resolved.codes
    names_by_code = resolved.names_by_code

    start_col, stop_col, refresh_col = st.columns(3)
    with start_col:
        if st.button("启动实时采集", type="primary", width="stretch"):
            session.start(codes, data_dir, day or None, timeout=float(timeout))
            st.success("采集已启动")
    with stop_col:
        if st.button("停止实时采集", width="stretch"):
            session.stop()
            st.info("采集已停止")
    with refresh_col:
        manual_refresh = st.button("刷新信号", width="stretch")

    if manual_refresh:
        lines = refresh_signals(
            data_dir,
            codes,
            day or None,
            has_position=has_position,
            opening_minutes=int(opening_minutes),
        )
        st.session_state.latest_signal_lines = lines
        st.success("信号已刷新")

    dashboard_rows = load_dashboard_data(data_dir, codes, day or None, limit=int(limit))
    _render_signal_board(build_signal_board_rows(dashboard_rows, names_by_code=names_by_code))

    status = session.status()
    with st.expander("采集状态和调试信息", expanded=False):
        status_cols = st.columns(4)
        status_cols[0].metric("运行状态", "运行中" if status.running else "已停止")
        status_cols[1].metric("订阅股票", ",".join(status.codes) if status.codes else "无")
        status_cols[2].metric("启动时间", status.started_at or "N/A")
        status_cols[3].metric("停止时间", status.stopped_at or "N/A")
        if status.error:
            st.error(f"采集错误：{status.error}")

        latest_status_rows: list[dict[str, Any]] = []
        for code in codes:
            snapshot = snapshot_to_dict(status.latest.get(code)) if status.latest else None
            latest_status_rows.append(
                {
                    "code": code,
                    "name": names_by_code.get(code, ""),
                    "count": status.counts.get(code, 0),
                    "price": _format_price(snapshot.get("price") if snapshot else None),
                    "vwap": _format_price(snapshot.get("avg_price") if snapshot else None),
                    "ratio": _format_ratio(snapshot.get("ratio") if snapshot else None),
                    "ts": snapshot.get("ts") if snapshot else "等待快照",
                }
            )
        st.dataframe(latest_status_rows, width="stretch", hide_index=True)

    if st.session_state.get("latest_signal_lines"):
        st.subheader("最近刷新结果")
        for line in st.session_state.latest_signal_lines:
            st.code(line, language="text")

    st.subheader("数据看板")
    tabs = st.tabs([f"{names_by_code.get(row.code, '')} {row.code}".strip() for row in dashboard_rows])
    for tab, row in zip(tabs, dashboard_rows):
        with tab:
            metric_cols = st.columns(3)
            metric_cols[0].metric("原始快照", row.raw_count)
            metric_cols[1].metric("分钟线", row.minute_count)
            metric_cols[2].metric("信号数", row.signal_count)

            if row.latest_snapshot:
                st.markdown("**最新快照**")
                st.dataframe([row.latest_snapshot], width="stretch", hide_index=True)
            else:
                st.caption("暂无原始快照数据")

            if row.latest_signal:
                signal = row.latest_signal
                signal_cols = st.columns(4)
                signal_cols[0].metric("信号", signal.get("signal", "N/A"))
                signal_cols[1].metric("强度", signal.get("strength", "N/A"))
                signal_cols[2].metric("价格", _format_price(signal.get("price")))
                signal_cols[3].metric("参考价", _format_price(signal.get("reference_price")))
                st.info(f"动作：{signal.get('action', 'N/A')} | 失效：{signal.get('stop_condition') or '无'}")
                if signal.get("reasons"):
                    st.write("原因：" + "；".join(str(value) for value in signal["reasons"]))
            else:
                st.caption("暂无信号数据，可点击刷新信号")

            st.markdown("**信号历史**")
            st.dataframe(_compact_rows(row.signal_rows), width="stretch", hide_index=True)
            st.markdown("**分钟线**")
            st.dataframe(row.minute_rows, width="stretch", hide_index=True)

    if auto_refresh:
        time.sleep(float(refresh_interval))
        st.rerun()


def main() -> None:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except ImportError:
        get_script_run_ctx = None

    if get_script_run_ctx is None or get_script_run_ctx() is None:
        app_path = Path(__file__).resolve()
        raise SystemExit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(app_path)]))

    render_app()


if __name__ == "__main__":
    main()
