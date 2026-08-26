from datetime import datetime
import streamlit as st
from datetime import datetime
from api import deleteAsset, updateAsset
from db import delete_duplicate_pair

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