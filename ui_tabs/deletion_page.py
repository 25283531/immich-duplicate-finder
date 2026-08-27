"""
pages/deletion_page.py
=======================
批量删除管理 Tab —— 最终执行闸门

工作流（Step 1 → Step 2 → Step 3）：
  Step 1 Review：从 session_state.selected_asset_ids_to_delete 读取候选清单；
                 逐条解析 container→nas + role + isExternal，给出可勾选表格。
  Step 2 DryRun：调用 nasDeleter.execute_batch(dry_run=True) 模拟执行，
                 展示每条 disk_action + 预估统计；不真删。
  Step 3 Final Execute：必须勾选「我已确认备份」+ 输入 DELETE 字符串；
                 永久删除模式还需输入 FORCE；点击「立即执行删除」按钮触发真实执行。

session_state 约定（由 imageDuplicate 批量面板写入）：
  - selected_asset_ids_to_delete: List[Dict]   # 每项含 asset_id, originalPath, asset, detail
  - dry_run / force_delete / batch_size         # 由 startup 侧边栏写入
"""
import os
import sys
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import load_path_mappings, remove_pending_candidates, count_pending_candidates, list_pending_candidates
from api import getAssetDetail
from core.pathMapper import container_to_nas
from core.nasDeleter import execute_batch
from utility import st_dataframe_safe


def _enrich_items(items, mapping, immich_server_url, api_key, timeout):
    """ 对每个候选项预计算 nas_path + role + detail（含 isExternal）。
        失败的项会带 path_error 字段。 """
    enriched = []
    for it in items:
        asset_id = str(it.get("asset_id", ""))
        cp = it.get("originalPath") or it.get("container_path") or ""

        # 若上层已传 detail，直接复用；否则按需调用 API
        detail = it.get("detail")
        if detail is None and immich_server_url and api_key:
            detail = getAssetDetail(immich_server_url, api_key, asset_id, timeout=30)
        if detail is None:
            detail = {}

        nas_path, role, path_err = container_to_nas(cp, mapping)
        enriched.append({
            "asset_id": asset_id,
            "originalPath": cp,
            "nas_path": nas_path or "",
            "role": role or "",
            "path_error": path_err or "",
            "asset": it.get("asset", {}),
            "detail": detail,
        })
    return enriched


def render_deletion_page(immich_server_url: str, api_key: str, timeout: int):
    st.header("批量删除管理")
    st.caption(
        "⚠️ 最后执行闸门。建议先 DryRun 模拟 → 验证日志 → 二次确认后再真实执行。"
    )

    # ---------- 读取候选清单（优先 session_state，再从数据库恢复） ----------
    items = st.session_state.get("selected_asset_ids_to_delete", [])
    if not items:
        try:
            items = list_pending_candidates(limit=50000)
            if items:
                st.session_state["selected_asset_ids_to_delete"] = items
                st.info(f"💾 从数据库恢复了 {len(items)} 个待删候选。")
        except Exception:
            pass

    # 显示数据库中未处理候选总数
    try:
        db_count = count_pending_candidates()
        if db_count > 0:
            st.caption(f"📦 数据库中尚有 {db_count} 个未处理的候选（当前加载 {len(items)} 个）")
    except Exception:
        pass

    if not items:
        st.info(
            "暂无待删候选资产。请先到「重复检测」Tab 执行批量智能选择，"
            "或从重复对卡片中勾选加入待删列表。"
        )
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("📥 从数据库加载候选", key="load_pending_btn"):
                try:
                    items = list_pending_candidates(limit=50000)
                    st.session_state["selected_asset_ids_to_delete"] = items
                    st.rerun()
                except Exception as e:
                    st.error(f"加载失败: {e}")
        with col_b:
            if st.button("🗑 清空数据库所有候选", key="clear_db_pending_btn"):
                from db import clear_pending_candidates
                n = clear_pending_candidates()
                st.session_state["selected_asset_ids_to_delete"] = []
                st.success(f"已清空 {n} 条候选")
                st.rerun()
        return

    # ---------- 读取开关 ----------
    dry_run = st.session_state.get("dry_run", True)
    force = st.session_state.get("force_delete", False)
    batch_size = int(st.session_state.get("batch_size", 100))
    first_run_locked = st.session_state.get("first_run_locked", False)

    st.markdown(
        f"- 当前模式：**{'DryRun 模拟' if dry_run else '真实删除'}** "
        f"| **{'永久删除' if force else '回收站'}**\n"
        f"- 批次大小：**{batch_size}**\n"
        f"- 候选资产数：**{len(items)}**"
    )
    if first_run_locked:
        st.warning("⚠️ 首次运行锁定：必须至少跑过一次 DryRun 才能真实删除。")

    # ---------- 步骤 1: 待删清单审核 ----------
    st.subheader("步骤 1：待删清单审核")
    mapping = load_path_mappings()
    if not mapping:
        st.error("路径映射表为空！请先到「路径映射配置」Tab 添加映射。")
        return

    enriched = _enrich_items(items, mapping, immich_server_url, api_key, timeout)

    # 渲染可勾选表格
    keep_flags = []
    table_data = []
    for it in enriched:
        # 默认全部勾选；有 path_error 默认取消勾选
        default_checked = not bool(it["path_error"])
        col_a, col_b, col_c, col_d, col_e = st.columns([1, 2, 2, 2, 3])
        keep = col_a.checkbox(
            "删",
            value=default_checked,
            key=f"del_check_{it['asset_id']}",
            help="勾选表示参与本次删除",
        )
        keep_flags.append(keep)
        col_b.markdown(f"**ID**: `{it['asset_id']}`")
        col_c.markdown(f"**容器路径**: `{it['originalPath']}`")
        # detail 可能是 dict (getAssetDetail 返回的资产详情) 或 str (备注文本)
        # 当 detail 是字符串时，用 role 推断 isExternal
        _d = it.get("detail") or {}
        is_external = False
        if isinstance(_d, dict):
            is_external = bool(_d.get("isExternal") or _d.get("is_external"))
        else:
            is_external = (it.get("role") == "外部媒体库")
        col_d.markdown(
            f"**角色**: `{it['role'] or '—'}` | "
            f"**外部**: {'✅' if is_external else '—'}"
        )
        if it["path_error"]:
            col_e.error(f"❌ {it['path_error']}")
        else:
            col_e.markdown(f"**NAS**: `{it['nas_path']}`")
        table_data.append(it)

    # 筛选真正要执行的项
    pending = [
        it for it, keep in zip(enriched, keep_flags) if keep
    ]
    if not pending:
        st.warning("未勾选任何资产，无可执行项。")
        return

    st.success(f"已勾选 {len(pending)} / {len(enriched)} 个资产参与本次操作。")

    # ---------- 步骤 2: DryRun 模拟 ----------
    st.markdown("---")
    st.subheader("步骤 2：DryRun 模拟执行")
    if st.button("🟡 执行 DryRun 模拟", key="dryrun_btn"):
        with st.spinner("DryRun 模拟中..."):
            report, log_id = execute_batch(
                immich_server_url=immich_server_url,
                api_key=api_key,
                items=pending,
                mapping=mapping,
                dry_run=True,
                force=force,
            )
        st.session_state["last_dryrun_report"] = report
        st.success(f"DryRun 完成，已写入日志（log_id={log_id}）。")
        _render_report_summary(report)

    last_dry = st.session_state.get("last_dryrun_report")
    if last_dry:
        with st.expander("查看上次 DryRun 报告", expanded=False):
            _render_report_summary(last_dry)

    # ---------- 步骤 3: 真实执行 ----------
    st.markdown("---")
    st.subheader("步骤 3：真实执行（危险操作）")

    if dry_run:
        st.info("当前是 DryRun 模式，不会真实删除。要执行真实删除请到侧边栏关闭 DryRun 开关。")
        return

    if first_run_locked:
        st.error("❌ 首次运行锁定，必须先跑一次 DryRun 模拟（见 Step 2）。")
        return

    st.warning("⚠️ 即将真实执行磁盘 unlink + Immich API 删除，操作不可逆！")

    confirm_backup = st.checkbox("我已确认备份重要数据", key="confirm_backup")
    confirm_text = st.text_input(
        '请输入 "DELETE" 以确认真实删除',
        value="",
        key="confirm_delete_text",
    )
    if force:
        force_text = st.text_input(
            '永久删除模式：请额外输入 "FORCE" 确认',
            value="",
            key="confirm_force_text",
        )
    else:
        force_text = "ok"

    can_execute = (
        confirm_backup
        and confirm_text.strip() == "DELETE"
        and (not force or force_text.strip() == "FORCE")
    )

    if st.button(
        "🚀 立即执行删除",
        key="final_execute_btn",
        disabled=not can_execute,
        type="primary",
    ):
        if not can_execute:
            st.error("请先完成所有确认步骤。")
            return
        with st.spinner("真实执行删除中..."):
            progress = st.progress(0.0)
            # 分批执行（按 batch_size 切片）
            total = len(pending)
            aggregated_reports = []
            for i in range(0, total, batch_size):
                chunk = pending[i:i + batch_size]
                report, log_id = execute_batch(
                    immich_server_url=immich_server_url,
                    api_key=api_key,
                    items=chunk,
                    mapping=mapping,
                    dry_run=False,
                    force=force,
                    batch_id=f"final-{i}-{i+len(chunk)}",
                )
                aggregated_reports.append((report, log_id))
                progress.progress(min((i + len(chunk)) / total, 1.0))
            progress.progress(1.0)

        # 汇总展示
        st.success(f"执行完成，共 {len(aggregated_reports)} 个批次。")
        for r, lid in aggregated_reports:
            st.markdown(f"**批次 log_id={lid}**")
            _render_report_summary(r)

        # 从数据库移除已处理的候选（已删除的资产不再出现）
        processed_ids = [it["asset_id"] for it in pending]
        try:
            removed = remove_pending_candidates(processed_ids)
            st.info(f"✅ 已从数据库移除 {removed} 个已处理的候选。剩余候选可继续在下次会话处理。")
        except Exception as e:
            st.warning(f"从数据库移除候选失败（不影响删除结果）：{e}")

        # 同步更新 session_state（保留未处理的）
        all_remaining = list_pending_candidates(limit=50000)
        st.session_state["selected_asset_ids_to_delete"] = all_remaining
        remaining_count = len(all_remaining)

        if remaining_count > 0:
            st.info(f"🗂 还有 {remaining_count} 个候选未处理，下次打开仍可继续。")
            if st.button("📋 查看剩余候选", key="view_remaining_btn"):
                st.rerun()
        else:
            st.success("🎉 所有候选已处理完毕！")

        if st.button("🧹 清空剩余清单", key="post_clear_btn"):
            st.session_state["selected_asset_ids_to_delete"] = []
            st.rerun()


def _render_report_summary(report):
    """ 渲染 nasDeleter.execute_batch 返回的 report 摘要 + 表格 """
    if not isinstance(report, dict):
        st.warning("report 不是 dict")
        return
    summary = report.get("summary", {})
    cols = st.columns([1, 1, 1, 1, 1])
    cols[0].metric("总数", summary.get("total", 0))
    cols[1].metric("磁盘删除", summary.get("deleted_unlink", 0))
    cols[2].metric("跳过非外部", summary.get("skip_non_external", 0))
    cols[3].metric("磁盘错误", summary.get("errors_disk", 0))
    cols[4].metric(
        "API 状态",
        summary.get("api_status_code", "—") if summary.get("api_called") else "不适用",
    )

    items = report.get("items", [])
    if items:
        st_dataframe_safe(
            [{
                "asset_id": it.get("asset_id", ""),
                "role": it.get("role", ""),
                "is_external": "✅" if it.get("is_external") else "—",
                "nas_path": it.get("nas_path", "") or "—",
                "disk_action": it.get("disk_action", ""),
                "api_result": it.get("api_result", ""),
            } for it in items],
            width="stretch",
            hide_index=True,
        )
