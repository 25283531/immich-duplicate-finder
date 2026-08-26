import os
import streamlit as st
import time

# 延迟导入：torch / torchvision / faiss 这些重依赖（ResNet152 权重 230MB）
# 改为在首次用到模型/索引时才加载，让 streamlit 首页能秒渲染
import numpy as np
from PIL import Image

from api import getImage
from utility import display_asset_column
from api import getAssetInfo
from db import load_duplicate_pairs, is_db_populated, save_duplicate_pair
from streamlit_image_comparison import image_comparison

# Set the environment variable to allow multiple OpenMP libraries
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

# 模型/transform 全局占位，首次调用 extract_features 时才真正加载
_model = None
_transform = None


def _get_model_and_transform():
    """ 惰性加载 ResNet152 + 预处理 transform。
        第一次调用时 import torch + torchvision 并加载权重；后续直接复用。 """
    global _model, _transform
    if _model is not None:
        return _model, _transform
    import torch
    from torchvision.models import resnet152, ResNet152_Weights
    from torchvision.transforms import Compose, Resize, ToTensor, Normalize

    m = resnet152(weights=ResNet152_Weights.DEFAULT)
    m.eval()

    def convert_image_to_rgb(image):
        if image.mode == 'RGBA':
            return image.convert('RGB')
        return image

    t = Compose([
        convert_image_to_rgb,
        Resize((224, 224)),
        ToTensor(),
        Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    _model, _transform = m, t
    return _model, _transform


def convert_image_to_rgb(image):
    """Convert image to RGB if it's RGBA."""
    if image.mode == 'RGBA':
        return image.convert('RGB')
    return image


# 兼容旧代码引用 transform（如果在别处直接用了 transform 变量）
# 实际推荐：调用 _get_model_and_transform() 拿到 transform
transform = None

# Global variables for paths
index_path = 'faiss_index.bin'
metadata_path = 'metadata.npy'

def extract_features(image):
    """Extract features from an image using a pretrained model."""
    import torch  # 延迟到函数内
    model, transform = _get_model_and_transform()
    image_tensor = transform(image).unsqueeze(0)  # Add batch dimension
    with torch.no_grad():
        features = model(image_tensor)
    return features.numpy().flatten()

def init_or_load_faiss_index():
    """Initialize or load the FAISS index and metadata, ensuring index is ready for use."""
    import faiss  # 延迟导入
    if os.path.exists(index_path) and os.path.exists(metadata_path):
        index = faiss.read_index(index_path)
        metadata = np.load(metadata_path, allow_pickle=True).tolist()
    else:
        index = None
        metadata = []
    return index, metadata

def save_faiss_index_and_metadata(index, metadata):
    """Save the FAISS index and metadata to disk."""
    import faiss
    faiss.write_index(index, index_path)
    np.save(metadata_path, np.array(metadata, dtype=object))

def update_faiss_index(immich_server_url,api_key, asset_id):
    
    """Update the FAISS index and metadata with a new image and its ID, 
    skipping if the asset_id has already been processed."""
    global index  # Assuming index is defined globally
    index, existing_metadata = init_or_load_faiss_index()
    
    # Check if the asset_id is already in metadata to decide whether to skip processing
    if asset_id in existing_metadata:
        return 'skipped'  # Skip processing this image

    image = getImage(asset_id, immich_server_url, "Thumbnail (fast)", api_key)
    if image is not None:
        features = extract_features(image)
    else:
        return 'error'
    
    if index is None:
        # Initialize the FAISS index with the correct dimension if it's the first time
        dimension = features.shape[0]
        index = faiss.IndexFlatL2(dimension)
    
    index.add(np.array([features], dtype='float32'))
    existing_metadata.append(asset_id)
    
    save_faiss_index_and_metadata(index, existing_metadata)
    return 'processed'

def calculateFaissIndex(assets, immich_server_url, api_key):
    # Initialize session state variables if they are not already set
    if 'message' not in st.session_state:
        st.session_state['message'] = ""
    if 'progress' not in st.session_state:
        st.session_state['progress'] = 0
    if 'stop_index' not in st.session_state:
        st.session_state['stop_index'] = False

    # Set up the UI components
    progress_bar = st.progress(st.session_state['progress'])
    stop_button = st.button('停止索引处理')
    message_placeholder = st.empty()

    # Check if stop was requested and reset it if button is pressed
    if stop_button:
        st.session_state['stop_index'] = True
        st.session_state['calculate_faiss'] = False

    total_assets = len(assets)
    processed_assets = 0
    skipped_assets = 0
    error_assets = 0
    total_time = 0

    for i, asset in enumerate(assets):
        if st.session_state['stop_index']:
            st.session_state['message'] = "处理已被用户停止。"
            message_placeholder.text(st.session_state['message'])
            break  # Break the loop if stop is requested

        asset_id = asset.get('id')
        start_time = time.time()

        status = update_faiss_index(immich_server_url,api_key, asset_id)
        if status == 'processed':
            processed_assets += 1
        elif status == 'skipped':
            skipped_assets += 1
        elif status == 'error':
            error_assets += 1

        end_time = time.time()
        processing_time = end_time - start_time
        total_time += processing_time

        # Update progress and messages
        progress_percentage = (i + 1) / total_assets
        st.session_state['progress'] = progress_percentage
        progress_bar.progress(progress_percentage)
        estimated_time_remaining = (total_time / (i + 1)) * (total_assets - (i + 1))
        estimated_time_remaining_min = int(estimated_time_remaining / 60)

        st.session_state['message'] = f"处理资产 {i + 1}/{total_assets} - (已处理: {processed_assets}, 已跳过: {skipped_assets}, 错误: {error_assets})。预计剩余时间: {estimated_time_remaining_min} 分钟。"
        message_placeholder.text(st.session_state['message'])

    # Reset stop flag at the end of processing
    st.session_state['stop_index'] = False
    if processed_assets >= total_assets:
        st.session_state['message'] = "处理完成！"
        message_placeholder.text(st.session_state['message'])
        progress_bar.progress(1.0)

def generate_db_duplicate():
    st.write("数据库初始化")
    index, metadata = init_or_load_faiss_index()
    if not index or not metadata:
        st.write("FAISS 索引或元数据不可用。")
        return

    # Check and update the stop mechanism in session state
    if 'stop_requested' not in st.session_state:
        st.session_state['stop_requested'] = False

    # Button to request stopping
    if st.button('停止查找重复'):
        st.session_state['stop_requested'] = True
        st.session_state['generate_db_duplicate'] = False

    num_vectors = index.ntotal
    message_placeholder = st.empty()
    progress_bar = st.progress(0)

    for i in range(num_vectors):
        # Check if stop has been requested
        if st.session_state['stop_requested']:
            message_placeholder.text("处理已被用户停止。")
            progress_bar.empty()
            # Optionally, reset the stop flag here if you want the process to be restartable without refreshing the page
            st.session_state['stop_requested'] = False
            return None

        progress = (i + 1) / num_vectors
        message_placeholder.text(f"查找重复: 正在处理向量 {i+1} / {num_vectors}")
        progress_bar.progress(progress)

        query_vector = np.array([index.reconstruct(i)])
        distances, indices = index.search(query_vector, 2)

        for j in range(1, indices.shape[1]):
            #if distances[0][j] < threshold:
            idx1, idx2 = i, indices[0][j]
            if idx1 != idx2:
                sorted_pair = (min(idx1, idx2), max(idx1, idx2))
                # Check if the indices in sorted_pair are within the bounds of metadata
                if sorted_pair[0] < len(metadata) and sorted_pair[1] < len(metadata):
                    save_duplicate_pair(metadata[sorted_pair[0]], metadata[sorted_pair[1]], distances[0][j])
                else:
                    st.error(f"元数据索引超出范围: {sorted_pair}")
                    # Optionally log more details or handle this case further

    message_placeholder.text(f"完成处理 {num_vectors} 个向量。")
    progress_bar.empty()

def show_duplicate_photos_faiss(assets, limit, min_threshold, max_threshold,immich_server_url,api_key):
    # First check if the database is populated
    if not is_db_populated():
        st.write("数据库中不含重复条目。请先创建/更新重复数据库。")
        return  # Exit the function early if the database is not populated
    
    # Load duplicates from database
    duplicates = load_duplicate_pairs(min_threshold, max_threshold)

    if duplicates:
        st.write(f"在阈值 {min_threshold} < x < {max_threshold} 范围内找到 {len(duplicates)} 对 FAISS 重复项:")
        progress_bar = st.progress(0)
        num_duplicates_to_show = min(len(duplicates), limit)

        for i, dup_pair in enumerate(duplicates[:num_duplicates_to_show]):
            try:
                # Check if stop was requested
                if st.session_state.get('stop_requested', False):
                    st.write("处理已被用户停止。")
                    st.session_state['stop_requested'] = False  # Reset the flag for future operations
                    st.session_state['generate_db_duplicate'] = False
                    break  # Exit the loop

                progress = (i + 1) / num_duplicates_to_show
                progress_bar.progress(progress)

                asset_id_1, asset_id_2 = dup_pair

                image1 = getImage(asset_id_1, immich_server_url, 'Thumbnail (fast)', api_key)
                image2 = getImage(asset_id_2, immich_server_url, 'Thumbnail (fast)', api_key)
                asset1_info = getAssetInfo(asset_id_1, assets)
                asset2_info = getAssetInfo(asset_id_2, assets)

                if image1 is not None and image2 is not None:
                    # Convert PIL images to numpy arrays if necessary
                    image1 = np.array(image1)
                    image2 = np.array(image2)
                    # Proceed with image comparison
                    image_comparison(
                        img1=image1,
                        img2=image2,
                        label1=f"名称: {asset_id_1}",
                        label2=f"名称: {asset_id_2}",
                        width=700,
                        starting_position=50,
                        show_labels=True,
                        make_responsive=True,
                        in_memory=False,
                    )

                    col1, col2 = st.columns(2)
                #    with col1:
                #        st.image(image1, caption=f"名称: {asset_id_1}")
                #    with col2:
                #        st.image(image2, caption=f"名称: {asset_id_2}")
                    
                    display_asset_column(col1, asset1_info, asset2_info, asset_id_1,asset_id_2, immich_server_url, api_key)
                    display_asset_column(col2, asset2_info, asset1_info, asset_id_2,asset_id_1, immich_server_url, api_key)
                else:
                    st.write(f"缺少一个或两个资产的信息: {asset_id_1}, {asset_id_2}")

                st.markdown("---")
            except:
                st.write("缺少资产信息")
        progress_bar.progress(100)

        # ---------- 批量智能选择 + 批量删除面板 ----------
        render_batch_selection_panel(
            assets, duplicates, immich_server_url, api_key
        )
    else:
        st.write("未找到重复项。")


# ============================================================
# 批量智能选择面板（保留策略 → 自动勾选 → 跳转 tab3 执行）
# ============================================================
def render_batch_selection_panel(assets, duplicate_pairs, immich_server_url, api_key):
    """ 在重复列表下方渲染批量操作面板。
        把策略选中的待删项写入 session_state["selected_asset_ids_to_delete"]。"""
    from core.smartSelect import pick_deletion_candidates, score_asset
    from core.pathMapper import detect_role_by_container_path

    st.markdown("---")
    st.subheader("🧠 批量智能选择 + 批量删除")

    if not duplicate_pairs:
        st.info("当前没有重复对可供批量选择。")
        return

    # 策略下拉框
    strategy = st.selectbox(
        "保留策略",
        options=[
            "智能混合（推荐）",
            "保留最大文件",
            "保留最高分辨率",
            "保留最早拍摄",
            "保留外部库原图",
            "保留非外部库（清缓存副本）",
        ],
        index=0,
        key="batch_strategy_select",
        help="智能混合=按 smartSelect.score_asset 综合打分保留高分者",
    )

    # 构建"组"：每个 dup_pair 视为 1 组（2 个资产）
    # 为每组调用 pick_deletion_candidates 拿 keepers/to_delete
    if st.button("🎯 按策略勾选可删除项", key="batch_pick_btn"):
        candidates = []
        # 准备 assets 字典以便查找
        asset_map = {a.get("id"): a for a in (assets or []) if isinstance(a, dict)}

        for id1, id2 in duplicate_pairs:
            a1 = asset_map.get(id1, {"id": id1})
            a2 = asset_map.get(id2, {"id": id2})
            cp1 = a1.get("originalPath", "")
            cp2 = a2.get("originalPath", "")
            role1 = detect_role_by_container_path(cp1) if cp1 else "外部媒体库"
            role2 = detect_role_by_container_path(cp2) if cp2 else "外部媒体库"
            group = [
                {"asset_id": id1, "asset": a1, "detail": {}, "role": role1},
                {"asset_id": id2, "asset": a2, "detail": {}, "role": role2},
            ]

            # 按策略决定 keeper
            if strategy == "智能混合（推荐）":
                keepers, to_del = pick_deletion_candidates(group, keep_count=1)
            elif strategy == "保留最大文件":
                def size_of(it):
                    ex = (it.get("asset") or {}).get("exifInfo") or {}
                    s = ex.get("fileSizeInByte", 0)
                    return s if isinstance(s, (int, float)) else 0
                keepers = [max(group, key=size_of)] if group else []
                to_del = [it for it in group if it not in keepers]
            elif strategy == "保留最高分辨率":
                def res_of(it):
                    ex = (it.get("asset") or {}).get("exifInfo") or {}
                    w, h = ex.get("exifImageWidth", 0), ex.get("exifImageHeight", 0)
                    return (w or 0) * (h or 0)
                keepers = [max(group, key=res_of)] if group else []
                to_del = [it for it in group if it not in keepers]
            elif strategy == "保留最早拍摄":
                def time_of(it):
                    t = (it.get("asset") or {}).get("fileCreatedAt", "")
                    return t or ""
                # 最早=字符串最小
                keepers = [min(group, key=time_of)] if group else []
                to_del = [it for it in group if it not in keepers]
            elif strategy == "保留外部库原图":
                # role==外部媒体库 优先保留
                keepers = [it for it in group if it.get("role") == "外部媒体库"] or group[:1]
                to_del = [it for it in group if it not in keepers]
            else:  # 保留非外部库
                keepers = [it for it in group if it.get("role") != "外部媒体库"] or group[:1]
                to_del = [it for it in group if it not in keepers]

            for it in to_del:
                candidates.append({
                    "asset_id": it["asset_id"],
                    "originalPath": (it.get("asset") or {}).get("originalPath", ""),
                    "asset": it.get("asset") or {},
                    "detail": it.get("detail") or {},
                })

        st.session_state["selected_asset_ids_to_delete"] = candidates
        st.success(f"已勾选 {len(candidates)} 个待删资产（共 {len(duplicate_pairs)} 对）。")

    # 显示当前候选清单摘要
    pending = st.session_state.get("selected_asset_ids_to_delete", [])
    if pending:
        st.markdown(
            f"**即将删除 {len(pending)} 个资产**；建议跳转到「批量删除管理」Tab 确认并执行。"
        )
        # 简单表格预览
        st.dataframe(
            [{
                "asset_id": it.get("asset_id", ""),
                "originalPath": it.get("originalPath", ""),
            } for it in pending],
            width="stretch",
            hide_index=True,
        )
        col_a, col_b = st.columns(2)
        if col_a.button("🧹 清空已选清单", key="batch_clear_btn"):
            st.session_state["selected_asset_ids_to_delete"] = []
            st.rerun()
        # 给个提示按钮（实际 tab 切换由 Tabs 路由控制）
        col_b.info("请点击顶部 Tab「批量删除管理」继续执行")
    else:
        st.caption("暂无已选清单，请点击上方按钮按策略勾选。")

