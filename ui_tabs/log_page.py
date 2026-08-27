"""
pages/log_page.py
==================
操作日志审计页面 —— 倒序展示历次删除批次，支持过滤、详情展开、JSON 导出

数据源：db.query_operation_logs / db.count_operation_logs
每条日志的 detail_json 由 core.nasDeleter.execute_batch 写入，包含：
  batch_id, dry_run, force, started_at, finished_at, summary{...}, items[{...}]
"""
import os
import sys
import json
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import query_operation_logs, count_operation_logs
from utility import st_dataframe_safe

LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "app.log"
)


def _render_runtime_log_panel(max_lines=200):
    """ 展示 /app/data/app.log 末尾 N 行，方便定位 getImage/网络/权限等问题。 """
    st.markdown("### 🐞 运行日志（末尾）")
    col_a, col_b, col_c = st.columns([1, 1, 2])
    show_n = col_a.slider("显示行数", min_value=20, max_value=1000, value=max_lines, step=20)
    auto_refresh = col_b.checkbox("每 10 秒自动刷新", value=True)
    if col_c.button("🔄 刷新日志", use_container_width=True if False else False):
        pass

    if not os.path.exists(LOG_FILE):
        st.info(f"日志文件暂未生成：`{LOG_FILE}`。\n\n"
                "在 Docker 中也可执行：`docker logs --tail 200 immich-duplicate-finder`")
        return

    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        tail = lines[-show_n:] if len(lines) > show_n else lines
        text = "".join(tail)
        if not text.strip():
            st.info("日志为空")
        else:
            st.code(text, language=None)
            st.caption(f"共 {len(lines)} 行，当前显示后 {len(tail)} 行。日志文件：`{LOG_FILE}`")
    except Exception as e:
        st.error(f"读取日志失败：{e}")

    if auto_refresh:
        import time as _t
        try:
            _t.sleep(10)
            st.rerun()
        except Exception:
            pass


def _render_summary_pills(summary: dict) -> str:
    """ 用 HTML pills 渲染一行汇总指标 """
    if not isinstance(summary, dict):
        return ""
    total = summary.get("total", 0)
    deleted = summary.get("deleted_unlink", 0)
    skipped = summary.get("skip_non_external", 0)
    errors = summary.get("errors_disk", 0)
    return (
        f'<span style="background:#6c757d;color:#fff;border-radius:4px;'
        f'padding:2px 6px;font-size:11px;margin-right:4px;">总数 {total}</span>'
        f'<span style="background:#28a745;color:#fff;border-radius:4px;'
        f'padding:2px 6px;font-size:11px;margin-right:4px;">磁盘删除 {deleted}</span>'
        f'<span style="background:#ffc107;color:#000;border-radius:4px;'
        f'padding:2px 6px;font-size:11px;margin-right:4px;">跳过 {skipped}</span>'
        f'<span style="background:#dc3545;color:#fff;border-radius:4px;'
        f'padding:2px 6px;font-size:11px;">错误 {errors}</span>'
    )


def render_log_page():
    tab_ops, tab_runtime = st.tabs(["📜 操作日志（删除审计）", "🐞 运行日志（调试）"])

    with tab_ops:
        _render_operation_logs_tab()

    with tab_runtime:
        _render_runtime_log_panel()


def _render_operation_logs_tab():
    st.header("操作日志")
    st.caption("删除操作审计记录，按时间倒序展示，支持过滤与导出。")

    # ---------- 过滤器 ----------
    cols = st.columns([2, 2, 2, 2, 1])
    limit = cols[0].number_input(
        "每页条数", min_value=5, max_value=500, value=50, step=5, key="log_limit"
    )
    page = cols[1].number_input(
        "页码", min_value=1, value=1, step=1, key="log_page"
    )
    batch_id_filter = cols[2].text_input(
        "Batch ID 搜索", value="", key="log_batch_filter"
    )
    dry_run_filter = cols[3].selectbox(
        "DryRun", ["全部", "仅 DryRun", "仅真实删除"], index=0, key="log_dryrun_filter"
    )

    # 转换过滤值为 db 接口可识别的形式
    dry_run_arg = None
    if dry_run_filter == "仅 DryRun":
        dry_run_arg = 1
    elif dry_run_filter == "仅真实删除":
        dry_run_arg = 0

    offset = (int(page) - 1) * int(limit)

    # ---------- 计数 + 列表 ----------
    total_count = count_operation_logs(
        batch_id=batch_id_filter or None,
        dry_run=dry_run_arg,
    )
    rows = query_operation_logs(
        limit=int(limit),
        offset=offset,
        batch_id=batch_id_filter or None,
        dry_run=dry_run_arg,
    )

    st.caption(f"共 {total_count} 条记录，当前显示 {len(rows)} 条")

    if not rows:
        st.info("暂无操作日志记录。")
        return

    # ---------- 导出当前页 ----------
    if st.button("📥 导出当前页 JSON", key="export_log_json"):
        export_payload = json.dumps(rows, ensure_ascii=False, indent=2)
        st.download_button(
            label="下载 log_export.json",
            data=export_payload,
            file_name=f"operation_logs_page{page}.json",
            mime="application/json",
        )

    st.markdown("---")

    # ---------- 逐条渲染 ----------
    for r in rows:
        detail = r.get("detail_json", {})
        summary = detail.get("summary", {}) if isinstance(detail, dict) else {}
        items = detail.get("items", []) if isinstance(detail, dict) else []
        started = detail.get("started_at", "") if isinstance(detail, dict) else ""
        finished = detail.get("finished_at", "") if isinstance(detail, dict) else ""

        with st.expander(
            f"[{r['id']}] {r['timestamp']}  |  {r['batch_id']}  "
            f"|  {'DryRun' if r['dry_run'] else '真实删除'}  "
            f"|  {'永久' if r['force'] else '回收站'}"
        ):
            cols = st.columns([2, 2, 4])
            cols[0].markdown(f"**开始**: {started}")
            cols[1].markdown(f"**结束**: {finished}")
            cols[2].markdown(
                f"**汇总**: {_render_summary_pills(summary)}",
                unsafe_allow_html=True,
            )

            # API 调用状态
            if isinstance(summary, dict) and summary.get("api_called"):
                st.markdown(
                    f"Immich API 调用：HTTP `{summary.get('api_status_code', '?')}`"
                )

            # 详细 items 表
            if items:
                st.markdown("**逐条资产详情**")
                table_data = []
                for it in items:
                    table_data.append({
                        "asset_id": it.get("asset_id", ""),
                        "role": it.get("role", ""),
                        "is_external": "✅" if it.get("is_external") else "—",
                        "container_path": it.get("container_path", ""),
                        "nas_path": it.get("nas_path", "") or "—",
                        "disk_action": it.get("disk_action", ""),
                        "api_result": it.get("api_result", ""),
                    })
                st_dataframe_safe(table_data, width="stretch", hide_index=True)
            else:
                st.warning("detail_json 缺失或 items 为空")

            # 完整 JSON 折叠
            with st.expander("查看完整 JSON"):
                st.json(detail, expanded=False)
