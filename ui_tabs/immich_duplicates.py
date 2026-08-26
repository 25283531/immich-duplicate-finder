"""
Immich 原生重复检测页面
直接调用 Immich /api/duplicates 获取服务端检测结果
相比本地 FAISS 方案：零下载、秒级返回、无需 ResNet152 权重
"""

import streamlit as st
from api import get_duplicates, getImage, getAssetInfo, getAssetDetail


def render_immich_duplicates_page(immich_server_url, api_key, timeout):
    """渲染 Immich 原生重复检测页面"""
    st.header("🖼 Immich 原生重复检测")
    st.caption("直接调用 Immich 服务端的重复检测结果，无需下载所有缩略图")

    with st.expander("💡 为什么使用 Immich 原生检测？", expanded=False):
        st.markdown("""
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

        **操作流程**：点击「⭐ 保留此资产」→ 同组其余资产加入删除候选 → 切到「🚀 批量删除管理」审核并统一执行。
        """)

    st.markdown("---")

    col_fetch, _ = st.columns([1, 5])
    with col_fetch:
        if st.button('🔍 获取重复检测结果', type="primary"):
            with st.spinner("正在从 Immich 获取重复检测结果..."):
                duplicates = get_duplicates(immich_server_url, api_key, timeout)
                st.session_state['immich_duplicates'] = duplicates
                if duplicates:
                    total_assets = sum(len(g.get("assets", g.get("items", []))) for g in duplicates)
                    st.success(f"✅ 找到 {len(duplicates)} 组重复，涉及 {total_assets} 个资产")
                else:
                    st.info("未找到重复项。Immich 可能还未完成后台扫描，请稍后重试。")

    duplicates = st.session_state.get('immich_duplicates', [])
    if not duplicates:
        st.info("👆 点击上方按钮从 Immich 获取重复检测结果")
        return

    total_assets = sum(len(group.get("assets", group.get("items", []))) for group in duplicates)
    total_groups = len(duplicates)
    st.markdown(f"**共 {total_groups} 组重复，涉及 {total_assets} 个资产**")

    if 'selected_asset_ids_to_delete' not in st.session_state:
        st.session_state['selected_asset_ids_to_delete'] = []

    n_cand = len(st.session_state['selected_asset_ids_to_delete'])
    if n_cand:
        st.info(f"💡 当前已有 {n_cand} 个删除候选，可到「🚀 批量删除管理」审核后统一删除")

    st.markdown("---")

    for idx, group in enumerate(duplicates):
        assets_in_group = group.get("assets", group.get("items", []))
        duplicate_id = group.get("id", group.get("duplicateId", str(idx)))

        if not assets_in_group or len(assets_in_group) < 2:
            continue

        with st.expander(f"📁 重复组 #{idx + 1} ({len(assets_in_group)} 个资产) - ID: {duplicate_id[:8]}...",
                         expanded=(idx == 0)):

            cols = st.columns(min(len(assets_in_group), 3))

            for i, asset_ref in enumerate(assets_in_group[:6]):
                with cols[i % len(cols)]:
                    asset_id = asset_ref.get("id", asset_ref.get("assetId", ""))

                    asset_info = getAssetInfo(asset_id, [])
                    if not asset_info:
                        try:
                            detail = getAssetDetail(immich_server_url, api_key, asset_id)
                            if detail:
                                asset_info = getAssetInfo(asset_id, [detail])
                        except Exception:
                            pass

                    if asset_info:
                        details = (
                            f"- **文件名:** {asset_info[1]}\n"
                            f"- **大小:** {asset_info[0]}\n"
                            f"- **分辨率:** {asset_info[2]}\n"
                            f"- **拍摄时间:** {asset_info[4]}\n"
                            f"- **路径:** `{asset_info[5]}`\n"
                            f"- **是否收藏:** {'是' if asset_info[8] else '否'}\n"
                        )
                        st.markdown(details)

                        img = getImage(asset_id, immich_server_url, "Thumbnail (fast)", api_key)
                        if img:
                            st.image(img, caption=f"资产 {i + 1}", use_container_width=True)

                        if st.button(f"⭐ 保留此资产，标记其余为删除候选",
                                     key=f"keep_{duplicate_id}_{i}"):
                            all_ids_in_group = []
                            original_paths_by_id = {}
                            for ref in assets_in_group:
                                aid = ref.get("id", ref.get("assetId", ""))
                                if aid:
                                    all_ids_in_group.append(aid)
                                    original_paths_by_id[aid] = ref.get(
                                        "originalPath",
                                        ref.get("originalFileName", "")
                                    )

                            if 'selected_asset_ids_to_delete' not in st.session_state:
                                st.session_state['selected_asset_ids_to_delete'] = []

                            existing = {
                                c['asset_id'] for c in st.session_state['selected_asset_ids_to_delete']
                            }
                            kept = 0
                            skipped = 0
                            added = 0
                            for aid in all_ids_in_group:
                                if aid == asset_id:
                                    kept += 1
                                    continue
                                if aid in existing:
                                    skipped += 1
                                    continue
                                # 对齐 deletion_page 期望的字段格式
                                st.session_state['selected_asset_ids_to_delete'].append({
                                    "asset_id": aid,
                                    "originalPath": original_paths_by_id.get(aid, ""),
                                    "asset": {"id": aid},
                                    "detail": (
                                        f"Immich 重复组 {duplicate_id[:8]}，"
                                        f"保留资产 {asset_id[:8]}"
                                    ),
                                })
                                added += 1

                            msg = (f"✅ 已标记保留 1 个资产，其余 {len(all_ids_in_group) - kept} 个"
                                   f"中新增 {added} 条删除候选")
                            if skipped > 0:
                                msg += f"（跳过已存在的 {skipped} 个）"
                            msg += "。请到「🚀 批量删除管理」审核后统一执行删除。"
                            st.success(msg)
                            st.rerun()
                    else:
                        st.warning(f"无法获取资产 {asset_id[:8]} 的信息，请检查 Immich 连接")

            st.markdown("---")
            col1, col2 = st.columns(2)
            with col1:
                if st.button(f"🗑 暂时忽略此组（刷新后仍会出现）", key=f"dismiss_{duplicate_id}"):
                    st.session_state['immich_duplicates'] = [
                        g for g in duplicates
                        if g.get("id", g.get("duplicateId", "")) != duplicate_id
                    ]
                    st.success("✅ 已从当前列表移除此组（Immich 下次获取时仍会显示）")
                    st.rerun()
            with col2:
                group_count = sum(
                    1 for c in st.session_state.get('selected_asset_ids_to_delete', [])
                    if duplicate_id in (c.get('detail') or '')
                )
                st.info(f"💡 此组已有 {group_count} 个资产在删除候选中")
