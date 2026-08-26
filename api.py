import requests, json
import streamlit as st
from PIL import Image, UnidentifiedImageError, ImageFile
from io import BytesIO
from db import bytes_to_megabytes
from pillow_heif import register_heif_opener
import os
import urllib3
# 内网自签证书友好：抑制 InsecureRequestWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ============================================================
# A2 NEW: 纯函数 HTTP 辅助（不依赖 streamlit UI，可单元测试）
# 1. ping — 连通性 & API Key 校验
# 2. _fetch_assets_compat — Immich 新旧版本 API 路径兼容
# 3. getAssetDetail — 单资产详情 (isExternal / ownerId / albumIds)
# 4. deleteAssetsBulk — 批量删除；默认 force=False（回收站安全）
# 5. 旧 deleteAsset 单条改为委托给批量函数（修复原来 force=True 危险默认）
# ============================================================

def ping(immich_server_url: str, api_key: str, timeout: int = 10) -> bool:
    """ 连通性 + key 校验。先 GET /api/users/me，失败回退 /api/server-info """
    base = (immich_server_url or "").rstrip("/")
    if not base or not api_key:
        return False
    headers = {"Accept": "application/json", "x-api-key": api_key}
    for path in ("/api/users/me", "/api/server-info"):
        try:
            r = requests.get(base + path, headers=headers, timeout=timeout, verify=False)
            if r.ok:
                return True
        except Exception:
            continue
    return False


def _fetch_assets_compat(immich_server_url: str, api_key: str, timeout: int,
                         type_filter: str = "IMAGE"):
    """ 兼容新旧版本 Immich：
    先试 GET /api/assets（复数，v1.120+）；若 HTTP 404 再回退 /api/asset/（单数旧版）
    不依赖 streamlit UI 组件，返回 asset 列表（按 type 过滤）"""
    base = (immich_server_url or "").rstrip("/")
    if not base or not api_key:
        return []
    headers = {"Accept": "application/json", "x-api-key": api_key}
    endpoints = [base + "/api/assets", base + "/api/asset/"]
    last_exc = None
    for url in endpoints:
        try:
            resp = requests.get(url, headers=headers, timeout=timeout, verify=False)
            if resp.status_code == 404:
                continue  # 旧版本？试试下一个 endpoint
            if resp.status_code >= 400:
                last_exc = Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
                continue
            ctype = resp.headers.get("Content-Type", "")
            if "application/json" not in ctype:
                last_exc = Exception(f"非 JSON Content-Type: {ctype}")
                continue
            try:
                assets = resp.json() or []
            except Exception as je:
                last_exc = je
                continue
            if type_filter:
                assets = [a for a in assets if a.get("type") == type_filter]
            return assets
        except requests.exceptions.RequestException as re:
            last_exc = re
            continue
    if last_exc is not None:
        print(f"[_fetch_assets_compat] 失败: {last_exc}")
    return []


def getAssetDetail(immich_server_url: str, api_key: str, asset_id: str, timeout: int = 30):
    """ GET /api/assets/{id} 返回单资产完整详情。
    失败返回 None。字段至少包含 id / isExternal / ownerId / albumIds / originalPath"""
    base = (immich_server_url or "").rstrip("/")
    if not base or not asset_id:
        return None
    headers = {"Accept": "application/json", "x-api-key": api_key}
    try:
        r = requests.get(base + f"/api/assets/{asset_id}", headers=headers, timeout=timeout, verify=False)
        if r.ok:
            return r.json()
    except Exception:
        return None
    return None


def deleteAssetsBulk(immich_server_url: str, api_key: str, asset_ids,
                     force: bool = False, timeout: int = 120, data: str = None):
    """ 批量删除资产（调用 DELETE /api/assets）。
    默认 force=False -> 放入回收站，安全默认；force=True 永久删除需 UI 额外校验
    data: 可选，预先序列化好的 JSON body（由 nasDeleter 构造，含 {"ids":[...], "force":bool}）。
          若不传则本函数内部按 asset_ids+force 构造。
    Returns: (ok:bool, status_code:int, response_body_text:str)"""
    base = (immich_server_url or "").rstrip("/")
    if not base or not asset_ids:
        return False, 0, "empty args"
    if data is not None:
        payload = data
    else:
        ids = [str(x) for x in asset_ids]
        payload = json.dumps({"ids": ids, "force": bool(force)})
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-api-key": api_key,
    }
    try:
        r = requests.delete(base + "/api/assets", headers=headers, data=payload, timeout=timeout, verify=False)
        return (200 <= r.status_code < 300), r.status_code, (r.text or "")
    except requests.exceptions.RequestException as e:
        return False, 0, str(e)


# ============================================================
# Streamlit 前端的 fetchAssets：保留 @st.cache_data 装饰，内部委托 _fetch_assets_compat
# ============================================================
@st.cache_data(show_spinner=True) 
def fetchAssets(immich_server_url, api_key, timeout, type):
    if 'fetch_message' not in st.session_state:
        st.session_state['fetch_message'] = ""
    message_placeholder = st.empty()

    assets = []
    try:
        with st.spinner('Fetching assets...'):
            assets = _fetch_assets_compat(immich_server_url, api_key, timeout, type)
            if len(assets) > 0:
                st.session_state['fetch_message'] = f'Assets fetched successfully! ({len(assets)} items)'
            else:
                st.session_state['fetch_message'] = 'Received an empty list. Check Immich version/API key/permissions.'
    except Exception as e:
        st.session_state['fetch_message'] = f'Error fetching assets: {e}'
        assets = []

    message_placeholder.text(st.session_state['fetch_message'])
    return assets


def getImage(asset_id, immich_server_url, photo_choice, api_key):
    # Determine whether to fetch the original or thumbnail based on user selection
    register_heif_opener()
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    if photo_choice == 'Thumbnail (fast)':
        response = requests.request(
            "GET", f"{immich_server_url.rstrip('/')}/api/asset/thumbnail/{asset_id}?format=JPEG",
            headers={'Accept': 'application/octet-stream', 'x-api-key': api_key},
            data={}, verify=False,
        )
    else:
        asset_download_url = f"{immich_server_url.rstrip('/')}/api/download/asset/{asset_id}"
        response = requests.post(asset_download_url, headers={'Accept': 'application/octet-stream', 'x-api-key': api_key},
                                 stream=True, verify=False)
        
    if response.status_code == 200 and 'image/' in response.headers.get('Content-Type', ''):
        image_bytes = BytesIO(response.content)
        try:
            image = Image.open(image_bytes)
            image.load()
            image_bytes.close()
            return image
        except UnidentifiedImageError:
            print(f"Failed to identify image for asset_id {asset_id}. Content-Type: {response.headers.get('Content-Type')}")
            image_bytes.close()
            return None
        finally:
            image_bytes.close()
            del image_bytes 
    else:
        print(f"Skipping non-image asset_id {asset_id} with Content-Type: {response.headers.get('Content-Type')}")
        return None


def getAssetInfo(asset_id, assets):
    asset_info = next((asset for asset in assets if asset['id'] == asset_id), None)
    if asset_info:
        try:
            formatted_file_size = bytes_to_megabytes(asset_info['exifInfo']['fileSizeInByte'])
        except KeyError:
            formatted_file_size = "Unknown"
        
        original_file_name = asset_info.get('originalFileName', 'Unknown')
        resolution = "{} x {}".format(
            asset_info.get('exifInfo', {}).get('exifImageHeight', 'Unknown'), 
            asset_info.get('exifInfo', {}).get('exifImageWidth', 'Unknown')
        )
        lens_model = asset_info.get('exifInfo', {}).get('lensModel', 'Unknown')
        creation_date = asset_info.get('fileCreatedAt', 'Unknown')
        original_path = asset_info.get('originalPath', 'Unknown')
        is_offline = asset_info.get('isOffline', False)
        is_trashed = asset_info.get('isTrashed', False)
        is_favorite = asset_info.get('isFavorite', False)        
        return formatted_file_size, original_file_name, resolution, lens_model, creation_date, original_path, is_offline, is_trashed, is_favorite
    else:
        return None

def getServerStatistics(immich_server_url, api_key):
    try:
        response = requests.get(f"{immich_server_url.rstrip('/')}/api/server-info/statistics",
                                headers={'Accept': 'application/json', 'x-api-key': api_key}, verify=False)
        if response.ok:        
            return response.json()
        else:
            return None
    except:
        return None


# ============================================================
# Immich 原生重复检测 API
# GET /api/duplicates — 获取重复组（Immich 服务端基于文件名+时间戳+hash 检测）
# 相比本地 FAISS 方案：零下载、秒级返回、无需 ResNet152 权重
# ============================================================
def get_duplicates(immich_server_url: str, api_key: str, 
                    timeout: int = 30, size: int = 100) -> list:
    """ 调用 Immich 原生重复检测接口。
    返回重复组列表，每组包含多个资产 ID。
    失败返回空列表。"""
    base = (immich_server_url or "").rstrip("/")
    if not base or not api_key:
        return []
    headers = {"Accept": "application/json", "x-api-key": api_key}
    
    all_groups = []
    page = 1
    
    while True:
        try:
            url = f"{base}/api/duplicates?page={page}&size={size}"
            r = requests.get(url, headers=headers, timeout=timeout, verify=False)
            if not r.ok:
                print(f"[get_duplicates] HTTP {r.status_code}: {r.text[:200]}")
                break
            data = r.json()
            if not data:
                break
            
            # 兼容 Immich 不同版本的响应结构
            # 可能是 {items: [...], hasNext: bool} 或直接是数组
            if isinstance(data, list):
                all_groups.extend(data)
                break
            elif isinstance(data, dict):
                items = data.get("items", data.get("duplicates", []))
                if isinstance(items, list):
                    all_groups.extend(items)
                has_next = data.get("hasNext", False)
                if not has_next or not items:
                    break
                page += 1
            else:
                break
                
        except Exception as e:
            print(f"[get_duplicates] 异常: {e}")
            break
    
    return all_groups


def resolve_duplicate_group(immich_server_url: str, api_key: str,
                            duplicate_id: str, keep_asset_id: str,
                            timeout: int = 30) -> tuple:
    """ 解析重复组：指定保留哪个资产，其余标记为删除候选。
    POST /api/duplicates/resolve
    返回 (是否成功, 错误消息)。"""
    base = (immich_server_url or "").rstrip("/")
    if not base or not api_key:
        return False, "缺少服务器地址或 API 密钥"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-api-key": api_key,
    }
    # Immich v1.120+ 的字段名：duplicateIds(数组) + keepId
    payload = json.dumps({
        "duplicateIds": [duplicate_id],
        "keepId": keep_asset_id,
    })
    try:
        r = requests.post(
            base + "/api/duplicates/resolve",
            headers=headers,
            data=payload,
            timeout=timeout,
            verify=False,
        )
        if 200 <= r.status_code < 300:
            return True, None
        # 打印详细错误，便于调试
        msg = f"HTTP {r.status_code}: {r.text[:300]}"
        print(f"[resolve_duplicate_group] 失败: {msg}")
        return False, msg
    except Exception as e:
        msg = f"请求异常: {e}"
        print(f"[resolve_duplicate_group] {msg}")
        return False, msg


def dismiss_duplicate_group(immich_server_url: str, api_key: str,
                            duplicate_id: str, timeout: int = 30) -> tuple:
    """ 忽略/删除一个重复组（从检测结果中移除）。
    DELETE /api/duplicates/{id}
    返回 (是否成功, 错误消息)。"""
    base = (immich_server_url or "").rstrip("/")
    if not base or not api_key:
        return False, "缺少服务器地址或 API 密钥"
    headers = {"Accept": "application/json", "x-api-key": api_key}
    try:
        r = requests.delete(
            base + f"/api/duplicates/{duplicate_id}",
            headers=headers,
            timeout=timeout,
            verify=False,
        )
        if 200 <= r.status_code < 300:
            return True, None
        msg = f"HTTP {r.status_code}: {r.text[:300]}"
        print(f"[dismiss_duplicate_group] 失败: {msg}")
        return False, msg
    except Exception as e:
        msg = f"请求异常: {e}"
        print(f"[dismiss_duplicate_group] {msg}")
        return False, msg

# ------------------------------------------------------------
# 【安全修复】旧 deleteAsset 委托给批量函数；默认 force=False（安全默认）
#   - 之前底座硬编码 force=True (永久删除)，太危险
#   - 保留原有函数签名兼容性；新增可选 force 参数
# ------------------------------------------------------------
def deleteAsset(immich_server_url, asset_id, api_key, force: bool = False):
    st.session_state['show_faiss_duplicate'] = False
    ok, status, body = deleteAssetsBulk(immich_server_url, api_key, [asset_id], force=force)
    if ok:
        mode = " (永久删除)" if force else " (移动到回收站)"
        st.success(f"成功删除资产 ID: {asset_id}" + mode)
        print(f"Successfully deleted asset {asset_id} (force={force})")
        return True
    else:
        try:
            error_message = (json.loads(body) or {}).get('message', body) if isinstance(body, str) else str(body)
        except Exception:
            error_message = str(body)
        st.error(f"删除资产失败 {asset_id}。状态码={status}。消息={error_message}")
        print(f"Failed to delete asset {asset_id} status={status}: {error_message}")
        return False


def updateAsset(immich_server_url, asset_id, api_key, dateTimeOriginal, description, isFavorite, latitude, longitude, isArchived):
    base = immich_server_url.rstrip('/') if immich_server_url else ""
    url = f"{base}/api/asset/{asset_id}"
    payload = json.dumps({
        "dateTimeOriginal": dateTimeOriginal,
        "description": description,
        "isArchived": isArchived,
        "isFavorite": isFavorite,
        "latitude": latitude,
        "longitude": longitude
    })
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'x-api-key': api_key
    }
    try:
        response = requests.put(url, headers=headers, data=payload, verify=False)
        if response.status_code == 200:
            response_data = response.json()
            st.success(f"成功归档资产 ID: {asset_id}")
            print(f"Successfully move on archive asset with ID: {asset_id}. Response: {response_data}")
            return True
        else:
            try:
                error_message = response.json().get('message', '无附加错误信息。')
            except Exception:
                error_message = response.text or ""
            st.error(f"归档资产失败 {asset_id}。状态码={response.status_code}。消息={error_message}")
            print(f"Failed to move on archive asset {asset_id} status={response.status_code}: {error_message}")
            return False
    except requests.RequestException as e:
        st.error(f"请求失败: {str(e)}")
        print(f"Request failed: {str(e)}")
        return False
    

#For video function
def getVideoAndSave(asset_id, immich_server_url, api_key, save_directory):
    base = immich_server_url.rstrip('/') if immich_server_url else ""
    if not os.path.exists(save_directory):
        os.makedirs(save_directory)

    response = requests.get(f"{base}/api/download/asset/{asset_id}",
                            headers={'Accept': 'application/octet-stream', 'x-api-key': api_key},
                            stream=True, verify=False)
    file_path = os.path.join(save_directory, f"{asset_id}.mp4")

    if response.status_code == 200 and 'video/' in response.headers.get('Content-Type', ''):
        try:
            with open(file_path, 'wb') as f:
                f.write(response.content)
            return file_path
        except Exception as e:
            print(f"Failed to save video for asset_id {asset_id}. Error: {e}")
            return None
    else:
        print(f"Failed to retrieve video for asset_id {asset_id}. Status Code: {response.status_code}, Content-Type: {response.headers.get('Content-Type')}")
        return None
