from datetime import datetime
import inspect
import streamlit as st
from datetime import datetime
from api import deleteAsset, updateAsset
from db import delete_duplicate_pair


# ----------------------------------------------------------------------
# Streamlit 组件版本兼容层
# 目标：支持 streamlit==1.32.2 (项目锁定版本) 以及后续 1.37+/1.40+
# 做法：运行时检测组件签名，自动把新参数转换成对应版本的等价参数。
# ----------------------------------------------------------------------

# ---- st.image / st.button / st.dataframe 的签名探测（只做一次）----
_ST_IMAGE_SIG = set(inspect.signature(st.image).parameters.keys())
_ST_BUTTON_SIG = set(inspect.signature(st.button).parameters.keys())
_ST_DATAFRAME_SIG = set(inspect.signature(st.dataframe).parameters.keys())


def st_image_safe(image, **kwargs):
    """ st.image 的版本安全封装。
    - 1.32.x 支持: use_column_width=True/"auto", width=int/None；**不支持** use_container_width / clamp / width="stretch"
    - 1.40+ 支持: use_container_width=True / width="stretch" / clamp
    - 本函数自动把新写法映射到当前 streamlit 版本能接受的参数，避免 TypeError。
    """
    mapped = {}
    # 优先级：use_container_width / width="stretch" → use_column_width=True
    if "use_container_width" in kwargs:
        ucw = kwargs.pop("use_container_width")
        if "use_column_width" in _ST_IMAGE_SIG:
            mapped["use_column_width"] = True if ucw else False
        else:
            mapped["use_container_width"] = ucw
    if isinstance(kwargs.get("width"), str):
        wstr = kwargs.pop("width")
        if wstr in ("stretch", "always"):
            if "use_container_width" in _ST_IMAGE_SIG:
                mapped.setdefault("use_container_width", True)
            elif "use_column_width" in _ST_IMAGE_SIG:
                mapped.setdefault("use_column_width", True)
        elif wstr == "content":
            mapped["width"] = None
        # 其它字符串忽略，交给默认宽度

    # clamp 在 1.32 不存在，需要丢弃
    clamp = kwargs.pop("clamp", None)
    if clamp is not None and "clamp" not in _ST_IMAGE_SIG:
        clamp = None  # 旧版本不支持，静默丢弃

    # output_format 基本都支持，继续传
    # 剩余参数 (caption / channels 等) 原样保留
    mapped.update(kwargs)
    if clamp is not None:
        mapped["clamp"] = clamp

    return st.image(image, **mapped)


def st_button_safe(label, **kwargs):
    """ st.button 的版本安全封装（use_container_width 在 1.32 里可能不存在）。 """
    if "use_container_width" in kwargs:
        ucw = kwargs.pop("use_container_width")
        if "use_container_width" in _ST_BUTTON_SIG:
            kwargs["use_container_width"] = ucw
        elif "use_container_width" not in _ST_BUTTON_SIG and "width" in _ST_BUTTON_SIG:
            # 一些中间版本 button 也用 width
            pass  # 没有等价参数，简单忽略即可，按钮默认宽度也能看
    return st.button(label, **kwargs)


def st_dataframe_safe(data=None, **kwargs):
    """ st.dataframe 的版本安全封装（width="stretch" 回退到默认/use_container_width）。 """
    if isinstance(kwargs.get("width"), str):
        wstr = kwargs.pop("width")
        if wstr == "stretch" and "use_container_width" in _ST_DATAFRAME_SIG:
            kwargs["use_container_width"] = True
    return st.dataframe(data, **kwargs)

def compare_and_color_data(value1, value2):
    date1 = datetime.fromisoformat(value1.rstrip('Z'))
    date2 = datetime.fromisoformat(value2.rstrip('Z'))
    
    # Compare the datetime objects
    if date1 > date2:  # value1 is newer
        return f"<span style='color: red;'>{value1}</span>"
    elif date1 < date2:  # value1 is older
        return f"<span style='color: green;'>{value1}</span>"
    else:  # They are the same
        return f"{value1}"

def compare_and_color(value1, value2):
    if value1 > value2:
        return f"<span style='color: green;'>{value1}</span>"
    elif value1 < value2:
        return f"<span style='color: red;'>{value1}</span>"
    else:
        return f"{value1}"

def display_asset_column(col, asset1_info, asset2_info, asset_id_1,asset_id_2, server_url, api_key):
    details = f"""
    - **文件名:** {asset1_info[1]}
    - **资产 ID:** {asset_id_1}
    - **大小:** {compare_and_color(asset1_info[0], asset2_info[0])}
    - **分辨率:** {compare_and_color(asset1_info[2], asset2_info[2])}
    - **镜头型号:** {asset1_info[3]}
    - **拍摄时间:** {compare_and_color_data(asset1_info[4], asset2_info[4])}
    - **原始路径:** {asset1_info[5]}
    - **是否离线:** {'是' if asset1_info[6] else '否'}
    - **是否回收站:** {'是' if asset1_info[7] else '否'}
    - **是否收藏:** {'是' if asset1_info[8] else '否'}
    """
    with col:
        st.markdown(details, unsafe_allow_html=True)
        delete_button_key = f"delete-{asset_id_1}"
        delete_button_label = f"删除 {asset_id_1}"
        if st.button(delete_button_label, key=delete_button_key):
            try:
                if deleteAsset(server_url, asset_id_1, api_key):
                    st.success(f"已删除照片 {asset_id_1}")
                    st.session_state[f'deleted_photo_{asset_id_1}'] = True
                    st.session_state['show_faiss_duplicate'] = True
                    st.session_state['generate_db_duplicate'] = False
                    #remove from asset db
                    delete_duplicate_pair(asset_id_1,asset_id_2)
                else:
                    st.error(f"删除照片失败 {asset_id_1}")
            except Exception as e:
                st.error(f"发生错误: {str(e)}")
                print(f"Failed to delete photo {asset_id_1}: {str(e)}")