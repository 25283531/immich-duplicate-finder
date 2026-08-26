import os
import sys
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api import fetchAssets
from db import (
    startup_db_configurations,
    startup_processed_assets_db,
    startup_processed_duplicate_faiss_db,
    startup_path_mapping_db,
    startup_operation_logs_db,
)
from startup import (
    get_credentials,
    render_login_settings,
    render_runtime_switches,
    render_image_settings,
)
from imageDuplicate import (
    generate_db_duplicate,
    show_duplicate_photos_faiss,
    calculateFaissIndex,
)
from ui_tabs.mapping_page import render_mapping_page
from ui_tabs.deletion_page import render_deletion_page
from ui_tabs.log_page import render_log_page
from ui_tabs.immich_duplicates import render_immich_duplicates_page


# Set the environment variable to allow multiple OpenMP libraries
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

###############STARTUP#####################

st.set_page_config(
    page_title="Immich 重复文件查找工具",
    page_icon="https://immich.app/img/immich-logo-stacked-dark.svg",
    layout="wide",
)

# 注入全局 CSS 控制侧边栏字号与导航样式
st.markdown("""
<style>
    /* 侧边栏整体字号 */
    [data-testid="stSidebar"] {
        font-size: 14px;
    }
    /* 侧边栏按钮字号 */
    [data-testid="stSidebar"] .stButton button {
        font-size: 13px !important;
        padding: 4px 8px !important;
    }
    /* 侧边栏 expander 字号 */
    [data-testid="stSidebar"] .streamlit-expanderHeader {
        font-size: 13px !important;
    }
    /* 导航 radio 样式优化 */
    [data-testid="stSidebar"] .stRadio > div {
        gap: 4px;
    }
    [data-testid="stSidebar"] .stRadio label {
        font-size: 14px !important;
        padding: 6px 10px !important;
        border-radius: 6px !important;
        transition: background-color 0.2s !important;
    }
    [data-testid="stSidebar"] .stRadio label:hover {
        background-color: rgba(49, 51, 63, 0.1) !important;
    }
    /* 主区域标题字号 */
    .app-header h1, .app-header h2 {
        font-size: 1.5rem !important;
    }
    /* 隐藏 Streamlit 默认 chrome */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# 初始化所有数据库
startup_db_configurations()
startup_processed_assets_db()
startup_processed_duplicate_faiss_db()
startup_path_mapping_db()
startup_operation_logs_db()

# 获取初始凭据
immich_server_url, api_key, images_folder, timeout = get_credentials()


def setup_session_state():
    """Initialize session state with default values."""
    session_defaults = {
        'enable_size_filter': True,
        'size_ratio': 5,
        'deleted_photo': False,
        'filter_nr': 10,
        'show_duplicates': False,
        'calculate_faiss': False,
        'generate_db_duplicate': False,
        'show_faiss_duplicate': False,
        'avoid_thumbnail_jpeg': True,
        'is_trashed': False,
        'is_favorite': True,
        'stop_process': False,
        'stop_index': False,
        'photo_choice': 'Thumbnail (fast)',
        'selected_asset_ids_to_delete': [],
        'dry_run': True,
        'force_delete': False,
        'batch_size': 100,
        'first_run_locked': True,
    }
    for key, default_value in session_defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value


def render_sidebar():
    """渲染侧边栏导航"""
    with st.sidebar:
        # Logo
        st.image(
            "https://immich.app/img/immich-logo-stacked-dark.svg",
            width=120,
        )
        st.markdown("---")
        
        # 导航菜单（纵向平铺 radio）
        page = st.radio(
            "功能导航",
            options=[
                "🔑 登录设置",
                "⚙️ 运行开关",
                "🖼 Immich 原生重复检测",
                "🔍 图片重复查找 (FAISS)",
                "🗺 路径映射配置",
                "🚀 批量删除管理",
                "📜 操作日志",
            ],
            index=0,
            key="nav_page",
            label_visibility="collapsed",
        )
        
        st.markdown("---")
        
        # 快捷操作
        with st.expander("📊 快速操作", expanded=False):
            if st.button('🖼️ Immich 原生重复检测', use_container_width=True):
                st.session_state['nav_page'] = "🖼 Immich 原生重复检测"
                st.rerun()
            
            if st.button('🔍 FAISS 查找重复', use_container_width=True):
                st.session_state['show_faiss_duplicate'] = True
                st.session_state['nav_page'] = "🔍 图片重复查找 (FAISS)"
                st.rerun()
        
        st.markdown("---")
        
        # 状态指示（使用 HTML 替代 st.metric 以控制字号）
        dry_run = st.session_state.get("dry_run", True)
        force = st.session_state.get("force_delete", False)
        batch_size = st.session_state.get("batch_size", 100)
        
        st.markdown(
            f"""<div style="font-size:12px;line-height:1.6;">
            <table style="width:100%;border-collapse:collapse;">
            <tr><td style="color:#888;padding:2px 0;">安全模式</td><td style="text-align:right;font-weight:bold;color:{'#e74c3c' if not dry_run else '#27ae60'};">{'DryRun 模拟' if dry_run else '真实删除'}</td></tr>
            <tr><td style="color:#888;padding:2px 0;">删除模式</td><td style="text-align:right;font-weight:bold;color:{'#e74c3c' if force else '#27ae60'};">{'永久删除' if force else '回收站'}</td></tr>
            <tr><td style="color:#888;padding:2px 0;">批次大小</td><td style="text-align:right;font-weight:bold;">{batch_size}</td></tr>
            </table>
            </div>""",
            unsafe_allow_html=True,
        )
        
        st.markdown("---")
        st.markdown(
            '<div style="font-size:11px;color:#888;text-align:center;">版本 v0.2.0<br>Immich 重复文件查找工具</div>',
            unsafe_allow_html=True,
        )
    
    return page


def tab_duplicate_detection():
    """重复检测主界面"""
    st.header("🔍 重复检测")
    st.caption("点击侧边栏「功能导航」或快捷操作中的按钮进行检测")
    
    assets = None
    if (
        st.session_state['calculate_faiss']
        or st.session_state['generate_db_duplicate']
        or st.session_state['show_faiss_duplicate']
    ):
        with st.spinner("正在获取资产列表..."):
            assets = fetchAssets(immich_server_url, api_key, timeout, 'IMAGE')
        if not assets:
            st.error("未找到资产或获取资产失败。请检查登录设置。")
            return

    if st.session_state['calculate_faiss'] and assets:
        calculateFaissIndex(assets, immich_server_url, api_key)

    if st.session_state['generate_db_duplicate']:
        generate_db_duplicate()

    if st.session_state['show_faiss_duplicate'] and assets:
        show_duplicate_photos_faiss(
            assets,
            st.session_state['limit'],
            st.session_state['faiss_min_threshold'],
            st.session_state['faiss_max_threshold'],
            immich_server_url,
            api_key,
        )


def main():
    global immich_server_url, api_key, timeout
    
    setup_session_state()
    page = render_sidebar()
    
    # 根据导航选择渲染对应页面
    if page == "🔑 登录设置":
        immich_server_url, api_key, timeout = render_login_settings(
            immich_server_url, api_key, images_folder, timeout
        )
        
    elif page == "⚙️ 运行开关":
        render_runtime_switches()
        
    elif page == "🖼 Immich 原生重复检测":
        render_immich_duplicates_page(immich_server_url, api_key, timeout)
        
    elif page == "🔍 图片重复查找 (FAISS)":
        render_image_settings()
        # 如果触发了检测，显示结果
        tab_duplicate_detection()
        
    elif page == "🗺 路径映射配置":
        render_mapping_page()
        
    elif page == "🚀 批量删除管理":
        render_deletion_page(immich_server_url, api_key, timeout)
        
    elif page == "📜 操作日志":
        render_log_page()


if __name__ == "__main__":
    main()
