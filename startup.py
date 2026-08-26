import os
import sys
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sqlite3
from db import load_settings_from_db, save_settings_to_db, count_operation_logs
from api import ping
from core.pathMapper import detect_role_by_container_path


def _force_dry_run_for_first_run() -> bool:
    """ 首次启动（操作日志完全为空）时强制 DryRun 模式，且不能关闭 """
    try:
        return count_operation_logs() == 0
    except Exception:
        # 表未创建时保守返回 True（强制 DryRun）
        return True


def get_credentials():
    """ 获取当前保存的凭据 """
    return load_settings_from_db()


def render_login_settings(immich_server_url, api_key, images_folder, timeout):
    """ 渲染登录设置界面（主区域） """
    st.header("🔑 登录设置")
    st.caption("配置 Immich 服务器连接信息")
    
    col1, col2 = st.columns(2)
    
    with col1:
        try:
            immich_server_url = st.text_input('Immich 服务器地址', immich_server_url)
        except Exception:
            immich_server_url = ''
            
        api_key = st.text_input('API 密钥', api_key, type="password")
        
    with col2:
        timeout = st.number_input('请求超时 (毫秒)', value=timeout, min_value=100)
        st.caption("网络较差时可适当调高")

    if timeout < 10 or timeout == 0:
        st.warning('超时时间太低可能导致请求失败。')

    col_save, col_test = st.columns([1, 3])
    with col_save:
        if st.button('💾 保存设置', key='save_settings_btn', type="primary"):
            save_settings_to_db(immich_server_url, api_key, images_folder, timeout)
            st.success('设置已保存！')
    
    with col_test:
        if st.button('🔌 测试连接', key='ping_btn'):
            if not immich_server_url or not api_key:
                st.error("请先填写服务器地址与 API 密钥")
            else:
                with st.spinner("测试连接中..."):
                    ok = ping(immich_server_url, api_key, timeout=min(int(timeout) or 10, 30))
                if ok:
                    st.success(f"✅ 连接成功！服务器响应正常。")
                else:
                    st.error(f"❌ 连接失败：请检查 URL、API Key 或网络。")

    return immich_server_url, api_key, timeout


def render_runtime_switches():
    """ 渲染运行开关界面（主区域） """
    st.header("⚙️ 运行开关")
    st.caption("控制批量删除时的安全模式与 API 调用参数")
    
    first_run = _force_dry_run_for_first_run()
    
    # DryRun 模式
    st.subheader("🛡 安全模式")
    if first_run:
        st.warning("⚠️ 检测到无操作日志记录：**首次运行强制开启 DryRun**，不可关闭。")
        st.checkbox(
            "Dry Run 模式（模拟运行，不真实删除）",
            value=True,
            disabled=True,
            key="runtime_dry_run_locked",
            help="首次运行强制开启，至少跑过一次 DryRun 后才能关闭。",
        )
        dry_run = True
    else:
        dry_run = st.checkbox(
            "Dry Run 模式（模拟运行，不真实删除）",
            value=True,
            key="runtime_dry_run",
            help="建议新部署时先 DryRun 一次验证映射与权限。",
        )
    
    st.markdown("---")
    
    # 删除模式
    st.subheader("🗑 删除模式")
    force = st.radio(
        "删除方式",
        options=["移动到回收站（推荐，可恢复）", "永久删除（不可恢复）"],
        index=0,
        key="runtime_force_mode",
        help="永久删除会绕过回收站，直接从数据库清除。",
    )
    force_flag = force.startswith("永久")
    
    if force_flag:
        st.error("⚠️ 已选择永久删除模式！执行前会要求输入 FORCE 字符串二次确认。")
    else:
        st.info("💡 回收站模式下，删除的资产会进入 Immich 回收站，可在 30 天内恢复。")
    
    st.markdown("---")
    
    # 批次大小
    st.subheader("📦 API 批次大小")
    batch_size = st.number_input(
        "每批处理数量",
        min_value=1,
        max_value=500,
        value=100,
        step=10,
        key="runtime_batch_size",
        help="一次 API 调用处理的资产数量，数量越大调用次数越少，但单次请求越大。",
    )
    
    # 把开关写入 session_state 供其他页面读取
    st.session_state["dry_run"] = dry_run
    st.session_state["force_delete"] = force_flag
    st.session_state["batch_size"] = int(batch_size)
    st.session_state["first_run_locked"] = first_run
    
    st.success(f"当前设置：{'DryRun 模拟' if dry_run else '真实删除'} | {'永久删除' if force_flag else '回收站'} | 每批 {batch_size} 个")
    
    return dry_run, force_flag, int(batch_size), first_run


def render_image_settings():
    """ 渲染图片查找设置界面（主区域）- FAISS 本地检测方案 """
    st.header("🔍 图片重复查找 (FAISS 本地检测)")
    st.caption("使用 ResNet152 神经网络提取特征向量进行相似度检测")
    
    # 方案选择提示
    st.info("💡 **推荐优先使用「🖼 Immich 原生重复检测」**：速度更快、无需下载所有缩略图。FAISS 方案适合需要更灵活阈值调整的场景。")
    
    # 参数说明
    with st.expander("💡 FAISS 检测说明", expanded=False):
        st.markdown("""
        **FAISS** 是 Facebook 开发的向量相似度搜索库。它为每张图片提取特征向量，并计算图片间的"距离"来判断相似性。
        
        - **距离值越小** → 两张图片越相似
        - **阈值范围**：0.0（完全相同）到 10.0（完全不同）
        
        **调整建议**：
        - **严格去重**（只找真重复）：最大阈值设为 0.2-0.3
        - **平衡模式**（推荐）：最大阈值设为 0.5-0.7
        - **宽松检测**（找相似图）：最大阈值设为 1.0-2.0
        
        **操作流程**：
        1. 创建 FAISS 索引（首次需下载所有缩略图 + 加载 230MB ResNet152 模型）
        2. 创建重复数据库
        3. 查找重复图片
        
        **注意**：此方案需要下载所有图片缩略图到本地，首次运行可能较慢。
        """)
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    with col1:
        st.session_state['faiss_min_threshold'] = st.number_input(
            "最小 FAISS 阈值", min_value=0.0, max_value=10.0,
            value=st.session_state.get('faiss_min_threshold', 0.0), step=0.01,
            help="相似度下限，越大越严格",
        )
    with col2:
        st.session_state['faiss_max_threshold'] = st.number_input(
            "最大 FAISS 阈值", min_value=0.0, max_value=10.0,
            value=st.session_state.get('faiss_max_threshold', 0.6), step=0.01,
            help="相似度上限，越大越宽松",
        )
    
    st.markdown("---")
    
    col_btn1, col_btn2, col_btn3 = st.columns(3)
    with col_btn1:
        if st.button('🖼️ 创建/更新 FAISS 索引', type="primary"):
            st.session_state['calculate_faiss'] = True
    with col_btn2:
        if st.button('📊 创建/更新重复数据库'):
            st.session_state['generate_db_duplicate'] = True
    with col_btn3:
        st.session_state['limit'] = st.number_input(
            "显示重复对数",
            value=st.session_state.get('limit', 10), step=1,
            help="本次显示多少对重复图片",
        )
        if st.button('🔍 查找重复图片', type="primary"):
            st.session_state['show_faiss_duplicate'] = True
    
    st.markdown("---")
    st.info("💡 操作流程：1. 创建 FAISS 索引（首次）→ 2. 创建重复数据库 → 3. 查找重复图片")
