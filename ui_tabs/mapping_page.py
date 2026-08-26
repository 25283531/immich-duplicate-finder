"""
pages/mapping_page.py
======================
路径映射配置 Tab —— Immich 容器路径 → NAS 宿主机真实路径映射管理

功能要点：
  1. 列表展示已保存的映射（按 container_path 长度降序，便于"最长前缀匹配"语义可视化）
  2. 增/删/改单条映射
  3. 编辑容器路径时实时自动识别 role（与 core.pathMapper.detect_role_by_container_path 同步）
  4. 保存前对 nas_path 做 os.path.isdir 校验，拒绝无效目录
  5. 一键"测试 NAS 路径访问"：随机列出每个 nas_path 前 3 项内容验证可读
"""
import os
import streamlit as st

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import (
    load_path_mappings,
    insert_path_mapping,
    update_path_mapping,
    delete_path_mapping,
)
from core.pathMapper import detect_role_by_container_path


def _render_role_badge(role: str) -> str:
    """ 根据角色返回 HTML 徽章（颜色映射：危险/警告/信息/中性）"""
    color_map = {
        "外部媒体库": "#28a745",  # 绿：可磁盘删除
        "内部库原图目录": "#17a2b8",  # 青：信息
        "缓存目录(/data)": "#ffc107",  # 黄：警告（不可删磁盘）
        "Postgres数据库目录": "#dc3545",  # 红：危险（DB 文件）
    }
    color = color_map.get(role, "#6c757d")
    return (
        f'<span style="background:{color};color:#fff;border-radius:4px;'
        f'padding:2px 8px;font-size:12px;">{role}</span>'
    )


def _form_row(existing: dict = None) -> dict:
    """ 渲染单行编辑表单；existing=None 表示新增 """
    is_edit = existing is not None
    default_cp = existing["container_path"] if is_edit else ""
    default_np = existing["nas_path"] if is_edit else ""

    cp = st.text_input(
        "容器路径（Immich originalPath 前缀）",
        value=default_cp,
        key=f"map_cp_{existing['id'] if is_edit else 'new'}",
        help="示例：/data/library  或  /volume1/photo-albums",
    )
    np_ = st.text_input(
        "NAS 真实路径（宿主机绝对路径）",
        value=default_np,
        key=f"map_np_{existing['id'] if is_edit else 'new'}",
        help="示例：D:/immich/library  或  /volume1/photo-albums",
    )

    # 实时自动识别 role
    role = detect_role_by_container_path(cp) if cp else "外部媒体库"
    st.markdown(
        f"识别角色：{_render_role_badge(role)}",
        unsafe_allow_html=True,
    )
    return {
        "id": existing["id"] if is_edit else None,
        "container_path": cp.strip(),
        "nas_path": np_.strip(),
        "role": role,
    }


def render_mapping_page():
    st.header("路径映射配置")
    st.caption(
        "Immich 容器路径 → NAS 宿主机真实路径映射表。角色自动识别；"
        "仅 **外部媒体库** 角色允许磁盘物理删除。"
    )

    # ---------- 新增表单 ----------
    st.subheader("➕ 新增映射")
    with st.form("add_mapping_form", clear_on_submit=True):
        new_row = _form_row(existing=None)
        submitted = st.form_submit_button("添加映射")
        if submitted:
            cp, np_, role = new_row["container_path"], new_row["nas_path"], new_row["role"]
            if not cp or not np_:
                st.error("容器路径与 NAS 路径均不能为空")
            elif not os.path.isdir(np_):
                st.error(f"NAS 路径不存在或不可访问：{np_}")
            else:
                try:
                    insert_path_mapping(cp, np_, role)
                    st.success(f"已添加映射：{cp} → {np_}（{role}）")
                    st.rerun()
                except Exception as e:
                    st.error(f"保存失败：{e}")

    st.markdown("---")

    # ---------- 已有映射列表 ----------
    st.subheader("📋 当前映射表")
    mappings = load_path_mappings()

    if not mappings:
        st.info("暂无映射记录。请在上方添加。")
        return

    # 表头
    cols = st.columns([3, 3, 2, 1, 1])
    cols[0].markdown("**容器路径**")
    cols[1].markdown("**NAS 真实路径**")
    cols[2].markdown("**角色**")
    cols[3].markdown("**测试**")
    cols[4].markdown("**操作**")

    for m in mappings:
        cols = st.columns([3, 3, 2, 1, 1])
        cols[0].markdown(f"`{m['container_path']}`")
        cols[1].markdown(f"`{m['nas_path']}`")
        cols[2].markdown(_render_role_badge(m["role"]), unsafe_allow_html=True)
        cols[3].markdown(
            "✅" if os.path.isdir(m["nas_path"]) else "❌",
            help="NAS 路径是否可访问",
        )
        if cols[4].button("删除", key=f"del_{m['id']}"):
            delete_path_mapping(m["id"])
            st.success(f"已删除映射 ID={m['id']}")
            st.rerun()

    st.markdown("---")

    # ---------- 批量测试 ----------
    st.subheader("🔍 NAS 路径连通性测试")
    if st.button("一键测试所有 NAS 路径", key="test_all_nas"):
        ok, fail = 0, 0
        for m in mappings:
            np_ = m["nas_path"]
            try:
                items = os.listdir(np_)[:3]
                st.markdown(
                    f"✅ `{np_}` 可读，前 3 项：{items}",
                )
                ok += 1
            except Exception as e:
                st.error(f"❌ `{np_}` 访问失败：{e}")
                fail += 1
        st.info(f"测试完成：成功 {ok} 条，失败 {fail} 条")

    # ---------- 批量导入 JSON ----------
    st.markdown("---")
    st.subheader("📥 批量导入 JSON")
    st.caption(
        'JSON 格式：`[{"container_path": "/data/library", "nas_path": "/volume1/immich/library"}, ...]`'
    )
    uploaded = st.text_area("粘贴 JSON 数组", height=150, key="bulk_json_input")
    if st.button("批量导入", key="bulk_import_btn"):
        import json
        try:
            arr = json.loads(uploaded or "[]")
            if not isinstance(arr, list):
                raise ValueError("JSON 须为数组")
            succ, errs = 0, 0
            for item in arr:
                cp = str(item.get("container_path", "")).strip()
                np_ = str(item.get("nas_path", "")).strip()
                if not cp or not np_ or not os.path.isdir(np_):
                    errs += 1
                    continue
                role = detect_role_by_container_path(cp)
                try:
                    insert_path_mapping(cp, np_, role)
                    succ += 1
                except Exception:
                    errs += 1
            st.success(f"导入完成：成功 {succ} 条，跳过/失败 {errs} 条")
            if succ:
                st.rerun()
        except Exception as e:
            st.error(f"JSON 解析失败：{e}")
