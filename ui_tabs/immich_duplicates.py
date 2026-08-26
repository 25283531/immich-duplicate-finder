"""
Immich 原生重复检测页面
直接调用 Immich /api/duplicates 获取服务端检测结果
相比本地 FAISS 方案：零下载、秒级返回、无需 ResNet152 权重
"""

import streamlit as st
from api import get_duplicates, getImage, getAssetInfo, resolve_duplicate_group, dismiss_duplicate_group
from utility import display_asset_column


def render_immich_duplicates_page(immich_server_url, api_key, timeout):
    """渲染 Immich 原生重复检测页面"""
    st.header("🖼 Immich 原生重复检测")
    st.caption("直接调用 Immich 服务端的重复检测结果，无需下载所有缩略图")
    
    # 方案说明
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
        """)
    
    st.markdown("---")
    
    # 获取重复组
    col_fetch, col_refresh = st.columns([1, 5])
    with col_fetch:
        if st.button('🔍 获取重复检测结果', type="primary"):
            with st.spinner("正在从 Immich 获取重复检测结果..."):
                duplicates = get_duplicates(immich_server_url, api_key, timeout)
                st.session_state['immich_duplicates'] = duplicates
                if duplicates:
                    st.success(f"✅ 找到 {len(duplicates)} 组重复")
                else:
                    st.info("未找到重复项。Immich 可能还未完成后台扫描，请稍后重试。")
    
    duplicates = st.session_state.get('immich_duplicates', [])
    
    if not duplicates:
        st.info("👆 点击上方按钮从 Immich 获取重复检测结果")
        return
    
    # 统计信息
    total_assets = sum(len(group.get("assets", group.get("items", []))) for group in duplicates)
    total_groups = len(duplicates)
    
    st.markdown(f"**共 {total_groups} 组重复，涉及 {total_assets} 个资产**")
    
    st.markdown("---")
    
    # 遍历展示每组重复
    for idx, group in enumerate(duplicates):
        # 兼容不同的响应结构
        assets_in_group = group.get("assets", group.get("items", []))
        duplicate_id = group.get("id", group.get("duplicateId", str(idx)))
        
        if not assets_in_group or len(assets_in_group) < 2:
            continue
        
        with st.expander(f"📁 重复组 #{idx + 1} ({len(assets_in_group)} 个资产) - ID: {duplicate_id[:8]}...", 
                         expanded=(idx == 0)):
            
            # 显示资产对比
            cols = st.columns(min(len(assets_in_group), 3))
            
            for i, asset_ref in enumerate(assets_in_group[:6]):  # 最多显示 6 个
                with cols[i % len(cols)]:
                    asset_id = asset_ref.get("id", asset_ref.get("assetId", ""))
                    
                    # 获取资产详情
                    asset_info = getAssetInfo(asset_id, [])
                    if not asset_info:
                        # 如果没有缓存的 assets 列表，单独获取
                        from api import getAssetDetail
                        detail = getAssetDetail(immich_server_url, api_key, asset_id)
                        if detail:
                            asset_info = getAssetInfo(asset_id, [detail])
                    
                    if asset_info:
                        details = f"""
                        - **文件名:** {asset_info[1]}
                        - **大小:** {asset_info[0]}
                        - **分辨率:** {asset_info[2]}
                        - **拍摄时间:** {asset_info[4]}
                        - **路径:** {asset_info[5]}
                        - **是否收藏:** {'是' if asset_info[8] else '否'}
                        """
                        st.markdown(details, unsafe_allow_html=True)
                        
                        # 缩略图
                        img = getImage(asset_id, immich_server_url, "Thumbnail (fast)", api_key)
                        if img:
                            st.image(img, caption=f"资产 {i + 1}", use_container_width=True)
                        
                        # 保留按钮
                        if st.button(f"⭐ 保留此资产", key=f"keep_{duplicate_id}_{i}"):
                            if resolve_duplicate_group(immich_server_url, api_key, duplicate_id, asset_id):
                                st.success(f"✅ 已标记保留资产 {asset_id}，其余为删除候选")
                                st.rerun()
                            else:
                                st.error("❌ 操作失败")
                    else:
                        st.warning(f"无法获取资产 {asset_id} 的信息")
            
            # 操作按钮
            st.markdown("---")
            col1, col2 = st.columns(2)
            with col1:
                if st.button(f"🗑 忽略此组检测结果", key=f"dismiss_{duplicate_id}"):
                    if dismiss_duplicate_group(immich_server_url, api_key, duplicate_id):
                        st.success("✅ 已忽略此组")
                        st.session_state['immich_duplicates'] = [
                            g for g in duplicates 
                            if g.get("id", g.get("duplicateId", "")) != duplicate_id
                        ]
                        st.rerun()
                    else:
                        st.error("❌ 操作失败")
            with col2:
                st.info("💡 保留资产后，可到「批量删除管理」统一执行删除")
