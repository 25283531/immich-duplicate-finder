"""
Immich 原生重复检测页面
直接调用 Immich /api/duplicates 获取服务端检测结果
相比本地 FAISS 方案：零下载、秒级返回、无需 ResNet152 权重
"""

import streamlit as st
from api import (
    get_duplicates,
    getImage,
    getAssetInfo,
    getAssetDetail,
    dismiss_duplicate_group,
)
from utility import st_image_safe, st_button_safe
from db import add_pending_candidates, list_pending_candidates


# 检测当前 streamlit 版本是否支持 @st.dialog (streamlit>=1.37)
# 不支持则用"页面顶部大图面板"降级实现，保证 1.32+ 都可用
_HAS_DIALOG = callable(getattr(st, "dialog", None))


# ----------------------------------------------------------------------
# 大图预览实现：优先用 @st.dialog，回退到页面顶层面板
# ----------------------------------------------------------------------
if _HAS_DIALOG:
    @st.dialog("🔍 查看大图", width="large")
    def _open_large_view(asset_id, immich_server_url, api_key, caption, info_text):
        st.markdown(info_text)
        big_img = getImage(asset_id, immich_server_url, "Thumbnail", api_key)
        if big_img:
            st_image_safe(big_img, caption=caption, use_container_width=True, output_format="auto")
        else:
            fast = getImage(asset_id, immich_server_url, "Thumbnail (fast)", api_key)
            if fast:
                st_image_safe(fast, caption=caption + "（快速缩略图）", use_container_width=True)
            else:
                st.warning("暂无法加载缩略图，请检查 Immich 连接。")
        if st.button("关闭预览"):
            st.rerun()


def _show_large(asset_id, immich_server_url, api_key, caption, info_text):
    """ 打开大图预览；有 @st.dialog 用 dialog，否则写入 session_state 走降级面板。 """
    if _HAS_DIALOG:
        _open_large_view(asset_id, immich_server_url, api_key, caption, info_text)
        return
    st.session_state["large_preview"] = {
        "asset_id": asset_id,
        "caption": caption,
        "info_text": info_text,
    }
    st.rerun()


def _render_large_preview_panel(immich_server_url, api_key):
    """ 页面顶部的降级大图预览面板（当 @st.dialog 不可用时渲染）。 """
    preview = st.session_state.get("large_preview")
    if not preview:
        return
    asset_id = preview["asset_id"]
    caption = preview["caption"]
    info_text = preview["info_text"]

    with st.container(border=True):
        col_close, col_title = st.columns([1, 9])
        with col_close:
            if st.button("✕ 关闭", key="close_large_preview", type="primary"):
                del st.session_state["large_preview"]
                st.rerun()
        with col_title:
            st.markdown("### 🔍 大图预览")

        st.markdown(info_text)
        big_img = getImage(asset_id, immich_server_url, "Thumbnail", api_key)
        if big_img:
            st_image_safe(big_img, caption=caption, use_container_width=True, output_format="auto")
        else:
            fast = getImage(asset_id, immich_server_url, "Thumbnail (fast)", api_key)
            if fast:
                st_image_safe(fast, caption=caption + "（快速缩略图）", use_container_width=True)
            else:
                st.warning("暂无法加载缩略图，请检查 Immich 连接。")


def _sync_selected_from_db():
    """ 确保 session_state.selected_asset_ids_to_delete 与数据库候选一致，
        返回 asset_id -> candidate 映射 以及 asset_id -> True 的集合。"""
    if "selected_asset_ids_to_delete" not in st.session_state:
        st.session_state["selected_asset_ids_to_delete"] = []
    try:
        persisted = list_pending_candidates(limit=50000)
        sess_ids = {
            c["asset_id"] for c in st.session_state["selected_asset_ids_to_delete"] if isinstance(c, dict)
        }
        db_ids = {c["asset_id"] for c in persisted if isinstance(c, dict)}
        # 合并：session + 数据库
        for c in persisted:
            if isinstance(c, dict) and c["asset_id"] not in sess_ids:
                st.session_state["selected_asset_ids_to_delete"].append(c)
        session_list = st.session_state["selected_asset_ids_to_delete"]
        merged_map = {}
        for c in session_list:
            if isinstance(c, dict) and c.get("asset_id"):
                merged_map[c["asset_id"]] = c
        return merged_map, set(merged_map.keys())
    except Exception as e:
        sess_list = st.session_state["selected_asset_ids_to_delete"]
        merged_map = {}
        for c in sess_list:
            if isinstance(c, dict) and c.get("asset_id"):
                merged_map[c["asset_id"]] = c
        return merged_map, set(merged_map.keys())


def _add_pending(asset_ids: list, original_paths_by_id: dict, duplicate_id: str,
                 reason_suffix: str, immich_server_url: str, api_key: str):
    """ 把一批资产加入 session_state + 数据库。返回 (added, skipped)。 """
    if not asset_ids:
        return 0, 0
    selected_map, selected_set = _sync_selected_from_db()
    added = 0
    skipped = 0
    candidates_to_save = []
    for aid in asset_ids:
        if aid in selected_set:
            skipped += 1
            continue
        op = original_paths_by_id.get(aid, "")
        # 如果 Immich API 没返回 originalPath，尝试补取一次
        if not op and immich_server_url and api_key:
            try:
                detail = getAssetDetail(immich_server_url, api_key, aid)
                if isinstance(detail, dict):
                    op = detail.get("originalPath") or detail.get("originalFileName") or ""
            except Exception:
                pass
        item = {
            "asset_id": aid,
            "originalPath": op,
            "asset": {"id": aid},
            "detail": {
                "note": f"Immich 重复组 {duplicate_id[:8]}，{reason_suffix}",
                "duplicate_id": duplicate_id,
            },
            "reason": f"Immich 重复组 {duplicate_id[:8]}，{reason_suffix}",
            "source": "immich_native",
        }
        st.session_state["selected_asset_ids_to_delete"].append(item)
        candidates_to_save.append(item)
        added += 1
    if candidates_to_save:
        try:
            add_pending_candidates(candidates_to_save)
        except Exception:
            pass
    return added, skipped


def _render_asset_card(
    i,
    asset_ref,
    duplicate_id,
    immich_server_url,
    api_key,
    selected_map,
    keep_checked_map,
):
    """渲染单个资产卡片：左边文本信息，右边缩略图。返回 asset_id 或 None(已删除)。"""
    asset_id = asset_ref.get("id", asset_ref.get("assetId", ""))

    asset_info = getAssetInfo(asset_id, [])
    if not asset_info:
        try:
            detail = getAssetDetail(immich_server_url, api_key, asset_id)
            if detail:
                asset_info = getAssetInfo(asset_id, [detail])
        except Exception:
            pass

    # asset_info 为空 → 资产可能已经被 Immich 删除，标记为不可用并返回供父级过滤
    if not asset_info:
        st.warning(f"无法获取资产 {asset_id[:8]} 的信息，可能已被删除")
        return asset_id  # 让父级知道此组需要过滤

    original_path = asset_info[5]
    info_md = (
        f"- **文件名:** {asset_info[1]}\n"
        f"- **大小:** {asset_info[0]}\n"
        f"- **分辨率:** {asset_info[2]}\n"
        f"- **拍摄时间:** {asset_info[4]}\n"
        f"- **路径:** `{original_path}`\n"
        f"- **是否收藏:** {'是' if asset_info[8] else '否'}\n"
    )
    img_caption = f"资产 {i + 1} · {asset_info[1]}"

    is_pending = asset_id in selected_map
    default_keep = keep_checked_map.get(asset_id, False)
    pending_badge = " ⛔待删" if is_pending else ""

    with st.container(border=True):
        c_info, c_img = st.columns([1, 1], gap="medium")

        with c_info:
            st.markdown(f"**🏷️ 资产 {i + 1}{pending_badge}**")
            st.markdown(info_md)
            # 多选保留的复选框（允许一组中选多个保留）
            st.checkbox(
                "✅ 保留此资产",
                value=default_keep,
                key=f"keep_cb_{duplicate_id}_{i}",
                help=f"勾选表示此资产保留，在批量操作时会排除。可多选保留。",
            )

        with c_img:
            fast_img = getImage(asset_id, immich_server_url, "Thumbnail (fast)", api_key)
            if fast_img:
                st_image_safe(fast_img, caption=img_caption, output_format="auto")
            else:
                st.info("（缩略图加载中或无权限，请先确认 Immich 连接）")
            if st_button_safe(
                "🔍 点击查看大图",
                key=f"large_{duplicate_id}_{i}",
                use_container_width=True,
            ):
                _show_large(asset_id, immich_server_url, api_key, img_caption, info_md)
    return None


def render_immich_duplicates_page(immich_server_url, api_key, timeout):
    """渲染 Immich 原生重复检测页面"""
    st.header("🖼 Immich 原生重复检测")
    st.caption("直接调用 Immich 服务端的重复检测结果，无需下载所有缩略图")

    # 顶部降级大图预览面板（仅当 @st.dialog 不可用且用户点了 查看大图 时显示）
    if not _HAS_DIALOG:
        _render_large_preview_panel(immich_server_url, api_key)

    with st.expander("💡 为什么使用 Immich 原生检测？", expanded=False):
        st.markdown(
            """
        **Immich 原生检测 vs 本地 FAISS 检测：**

        | 特性 | Immich 原生 | 本地 FAISS |
        |------|------------|------------|
        | 速度 | ⚡ 秒级返回 | 🐢 需要下载+特征提取 |
        | 带宽 | ✅ 零下载 | ❌ 需下载所有缩略图 |
        | 依赖 | ✅ 无需额外模型 | ❌ 需 230MB ResNet152 |
        | 检测算法 | 文件名+时间戳+hash | ResNet152 特征向量+L2 距离 |
        | 灵活性 | 固定算法 | 可调阈值 |
        | 适用场景 | 快速去重 | 相似图检测 |

        **建议**：先用 Immich 原生检测处理精确重复，再用 FAISS 检测相似图。

        **操作流程**：
        1. 勾选每一组需要保留的资产（可多选保留）
        2. 点击「🔥 将未勾选的加入删除候选」或「🚫 全组全部删除」
        3. 切到「🚀 批量删除管理」审核并统一执行。
        """
        )

    st.markdown("---")

    # ---------- 获取结果按钮 ----------
    col_fetch, col_hide, _ = st.columns([2, 2, 6])
    with col_fetch:
        if st_button_safe("🔍 获取重复检测结果", type="primary", use_container_width=True):
            with st.spinner("正在从 Immich 获取重复检测结果..."):
                duplicates = get_duplicates(immich_server_url, api_key, timeout)
                st.session_state["immich_duplicates"] = duplicates
                if duplicates:
                    total_assets = sum(len(g.get("assets", g.get("items", []))) for g in duplicates)
                    st.success(f"✅ 找到 {len(duplicates)} 组重复，涉及 {total_assets} 个资产")
                else:
                    st.info("未找到重复项。Immich 可能还未完成后台扫描，请稍后重试。")
    with col_hide:
        auto_filter = st.checkbox(
            "自动过滤已删除/无法取详情的组",
            value=True,
            help="删除 Immich 资产后，该资产的重复组仍会被 Immich API 返回一段时间，"
                 "开启此选项可自动隐藏这些组。",
        )

    duplicates = st.session_state.get("immich_duplicates", [])
    if not duplicates:
        st.info("👆 点击上方按钮从 Immich 获取重复检测结果")
        return

    # ---------- 顶部：候选计数（与数据库同步） ----------
    selected_map, selected_set = _sync_selected_from_db()
    n_cand = len(selected_set)
    if n_cand:
        st.info(f"💡 当前已有 {n_cand} 个删除候选，可到「🚀 批量删除管理」审核后统一删除")

    # ---------- 渲染每一组 ----------
    total_groups = len(duplicates)
    shown_groups = 0
    skipped_filtered_groups = 0
    for idx, group in enumerate(duplicates):
        assets_in_group = group.get("assets", group.get("items", []))
        duplicate_id = group.get("id", group.get("duplicateId", str(idx)))

        if not assets_in_group or len(assets_in_group) < 2:
            continue

        # 取出本租所有 asset_id 用于组内计数
        group_ids = [a.get("id", a.get("assetId", "")) for a in assets_in_group if isinstance(a, dict)]
        group_ids = [x for x in group_ids if x]
        group_count = sum(1 for aid in group_ids if aid in selected_set)

        # 资产卡片渲染
        assets_to_show = assets_in_group[:8]
        rows = (len(assets_to_show) + 1) // 2

        # 先检测这组是否要过滤（当组内任何一个资产已被删除，且开启了自动过滤）
        deleted_asset_ids_in_group = []
        if auto_filter:
            # 先看 session_state 里已被选中并删除过的：不，我们只过滤 Immich API 无法取信息的资产
            # 这里只做轻量预检：只取 assets_to_show 里前几个的详情，不把 4000+ 都调一次 API
            pass

        with st.expander(
            f"📁 重复组 #{idx + 1} ({len(assets_in_group)} 个资产) - ID: {duplicate_id[:8]}..."
            + (f" [⛔ {group_count}待删]" if group_count > 0 else ""),
            expanded=(idx == 0),
        ):
            shown_groups += 1
            pos = 0
            any_deleted = False
            for _ in range(rows):
                card_cols = st.columns(2, gap="medium")
                for col in card_cols:
                    if pos >= len(assets_to_show):
                        break
                    with col:
                        keep_checked_map = {}
                        deleted = _render_asset_card(
                            pos,
                            assets_to_show[pos],
                            duplicate_id,
                            immich_server_url,
                            api_key,
                            selected_map,
                            keep_checked_map,
                        )
                        if deleted:
                            any_deleted = True
                            deleted_asset_ids_in_group.append(deleted)
                    pos += 1

            # 组内计数
            group_count = sum(1 for aid in group_ids if aid in selected_set)

            st.markdown("---")
            col_action, col_keep = st.columns([3, 2])
            with col_action:
                b1, b2, b3 = st.columns([1, 1, 1])
                with b1:
                    if st_button_safe(
                        "🔥 将未勾选的加入删除候选",
                        key=f"apply_keep_{duplicate_id}",
                        type="primary",
                        use_container_width=True,
                        help="逐张读取卡片上方「✅ 保留此资产」的勾选状态，"
                             "未勾选的资产统一加入删除候选（多选保留也支持）。",
                    ):
                        # 重新收集所有 keep_cb 的状态
                        keep_set = set()
                        all_refs = assets_to_show
                        original_paths_by_id = {}
                        for ref_i, ref in enumerate(all_refs):
                            aid = ref.get("id", ref.get("assetId", ""))
                            if not aid:
                                continue
                            original_paths_by_id[aid] = ref.get(
                                "originalPath",
                                ref.get("originalFileName", ""),
                            )
                            is_kept = st.session_state.get(
                                f"keep_cb_{duplicate_id}_{ref_i}", False
                            )
                            if is_kept:
                                keep_set.add(aid)
                        # 若全部勾选都为 False（默认），回退到兼容老行为：一张都没勾则不删
                        # 但更合理的是：如果全没勾，则什么都不发生，必须显式操作
                        if not keep_set and len(assets_to_show) > 0:
                            st.warning(
                                "当前未勾选任何保留项。请先在每个资产上方勾选「✅ 保留此资产」，"
                                "或直接使用「🚫 全组全部删除」按钮。"
                            )
                        else:
                            delete_ids = [
                                aid for aid in original_paths_by_id if aid not in keep_set
                            ]
                            suffix = (
                                f"勾选保留 {len(keep_set)} 张后，其余 {len(delete_ids)} 张删除"
                                if keep_set else f"未勾选保留，删除全部 {len(delete_ids)} 张"
                            )
                            added, skipped = _add_pending(
                                delete_ids, original_paths_by_id, duplicate_id, suffix,
                                immich_server_url, api_key,
                            )
                            msg = f"✅ 新增 {added} 条删除候选"
                            if skipped > 0:
                                msg += f"（跳过已存在的 {skipped} 个）"
                            msg += "。可继续勾选或切到批量删除管理。"
                            st.success(msg)
                            st.rerun()
                with b2:
                    if st_button_safe(
                        "🚫 全组全部删除",
                        key=f"del_all_{duplicate_id}",
                        use_container_width=True,
                        help="不保留任何一张。如果这组都是重复且不需要的，使用此按钮最省事。"
                             " 注意：这会删除本组所有资产，包括原本想保留的！",
                    ):
                        original_paths_by_id = {}
                        delete_ids = []
                        for ref in assets_in_group:
                            aid = ref.get("id", ref.get("assetId", ""))
                            if not aid:
                                continue
                            original_paths_by_id[aid] = ref.get(
                                "originalPath",
                                ref.get("originalFileName", ""),
                            )
                            delete_ids.append(aid)
                        added, skipped = _add_pending(
                            delete_ids, original_paths_by_id, duplicate_id,
                            "全组删除 (all-in-group)",
                            immich_server_url, api_key,
                        )
                        msg = f"✅ 全组删除：新增 {added} 条删除候选"
                        if skipped > 0:
                            msg += f"（跳过已存在的 {skipped} 个）"
                        msg += "。请注意：这组已一张都不会保留！"
                        st.warning(msg)
                        st.rerun()
                with b3:
                    if st_button_safe(
                        "🕳️ 在 Immich 中忽略此组",
                        key=f"dismiss_api_{duplicate_id}",
                        use_container_width=True,
                        help="调用 Immich 的忽略接口，这样 Immich 不会再把这组显示为重复。"
                             " 不是删除资产，只是取消重复标记。",
                    ):
                        ok, err = dismiss_duplicate_group(
                            immich_server_url, api_key, duplicate_id,
                        )
                        if ok:
                            # 同步从当前 session 列表移除
                            st.session_state["immich_duplicates"] = [
                                g for g in st.session_state.get("immich_duplicates", [])
                                if g.get("id", g.get("duplicateId", "")) != duplicate_id
                            ]
                            st.success("✅ 已在 Immich 中忽略此重复组")
                            st.rerun()
                        else:
                            st.error(f"忽略失败：{err}")

            with col_keep:
                st.info(
                    f"💡 此组已有 {group_count} 个资产在删除候选中  "
                    f"(本组 {len(group_ids)} 个资产)"
                )

            # 自动过滤：如果组内存在已删除资产，且开启了自动过滤，
            # 给一条提示并提供从当前列表移除按钮
            if any_deleted and auto_filter:
                st.caption(
                    f"⚠️ 此组中 {len(deleted_asset_ids_in_group)} 个资产已不存在于 Immich"
                    "（可能已被删除）。自动过滤建议从列表隐藏。"
                )
                if st.button(
                    f"🕳️ 隐藏此已失效的重复组",
                    key=f"hide_invalid_{duplicate_id}",
                ):
                    st.session_state["immich_duplicates"] = [
                        g for g in st.session_state.get("immich_duplicates", [])
                        if g.get("id", g.get("duplicateId", "")) != duplicate_id
                    ]
                    skipped_filtered_groups += 1
                    st.rerun()

    if skipped_filtered_groups > 0:
        st.info(f"🕳️ 本次已隐藏 {skipped_filtered_groups} 个失效重复组")
