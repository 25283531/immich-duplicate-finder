"""
core/pathMapper.py
===================
Immich 容器路径 -> NAS 宿主机真实路径转换 + 目录角色自动识别 + 路径穿越防护

严格对齐 PHP 参考脚本语义：
  Role detection rules (prefix match):
    /data/library[/...]          -> 内部库原图目录
    /data[/...] (非上条)         -> 缓存目录(/data)
    /var/lib/postgresql/data[...] -> Postgres数据库目录
    其他                          -> 外部媒体库

Security rules (三重防护 防穿越):
    1. container_path 规范化后若包含 ".." 路径段 => 拦截 "路径越权拦截(包含 ..)"
    2. 必须命中一条 mapping；采用"最长匹配的容器路径前缀"优先原则
       - 命中的相对部分(rel) 若以 "/" 开头去掉斜杠
    3. nas_full = normpath( nas_path + rel )
       - 若 normpath 后结果 **不以 normpath(nas_path) + sep 开头**，且不等于 normpath(nas_path) => 拦截
       - 若 normpath 后结果 **恰好 == normpath(nas_path)**（恰好是 NAS 根目录本身，非文件）=> 拦截 "禁止映射到目录根本身"
"""
import os
from typing import List, Dict, Optional, Tuple, Any


# ---------------------------------------------------------------------------
# Public 1: 角色识别（独立函数，不依赖映射表）
# ---------------------------------------------------------------------------
def detect_role_by_container_path(cp: str) -> str:
    if not isinstance(cp, str):
        return "外部媒体库"
    # 规范化斜杠（Windows 用户有时会误写成 '\'）
    cp_norm = cp.replace("\\", "/").rstrip("/")

    # 1. 内部库原图目录（必须先于 /data 判断，保证最长优先）
    if cp_norm == "/data/library" or cp_norm.startswith("/data/library/"):
        return "内部库原图目录"
    # 2. 缓存目录
    if cp_norm == "/data" or cp_norm.startswith("/data/"):
        return "缓存目录(/data)"
    # 3. Postgres 数据库目录
    if cp_norm == "/var/lib/postgresql/data" or cp_norm.startswith("/var/lib/postgresql/data/"):
        return "Postgres数据库目录"
    # 4. 其他均视为用户自定义的外部媒体库挂载点
    return "外部媒体库"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _contains_dotdot_segment(cp: str) -> bool:
    """ 判断容器路径中是否存在 '..' 穿越段

    规则：
    - 按 '/' 分割，任一段 == '..' -> True
    - 覆盖 '..' 出现在开头 / 中间 / 结尾 全部情形
    - 处理 Windows '\\' 分隔符
    """
    for part in cp.replace("\\", "/").split("/"):
        if part == "..":
            return True
    return False


def _safe_normpath(p: str) -> str:
    """ 跨平台安全 normpath：
    - Windows 保留盘符大小写 + 扩展长度前缀
    - 去掉尾随分隔符
    - 结果统一转成 str（兼容 os.path.normpath 返回类型）
    """
    return os.path.normpath(p)


# ---------------------------------------------------------------------------
# Public 2: 核心转换函数
# ---------------------------------------------------------------------------
def container_to_nas(
    container_path: str,
    mapping: List[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Args:
        container_path: Immich API 返回的 asset.originalPath（容器内路径）
        mapping: [{"id":int, "container_path":str, "nas_path":str, "role":str(optional)}, ...]
                 要求容器路径已存在且 nas_path 为真实目录（上层已校验）

    Returns:
        (nas_real_path, role, None)          成功
        (None, None, error_message)          失败
    """
    # [防护 1-a] 基本类型校验
    if not isinstance(container_path, str) or len(container_path) == 0:
        return None, None, "容器路径为空或类型错误"

    # [防护 1-b] 禁止包含任何 ".." 段
    if _contains_dotdot_segment(container_path):
        return None, None, "路径越权拦截(包含 '..' 穿越段)"

    # 规范化容器路径（统一 Unix 斜杠）
    cp_norm = container_path.replace("\\", "/")

    # [防护 2] 在所有映射项中找 "最长前缀匹配" 的那条
    # 长度按 container_path 字符数；前缀后如果紧跟 '/' 或完全相等才算匹配
    best: Optional[Dict[str, Any]] = None
    best_cp_len = -1
    for m in mapping:
        m_cp = (m.get("container_path") or "").replace("\\", "/").rstrip("/")
        if not m_cp:
            continue
        if cp_norm == m_cp or cp_norm.startswith(m_cp + "/"):
            if len(m_cp) > best_cp_len:
                best_cp_len = len(m_cp)
                best = m
    if best is None:
        return None, None, f"没有匹配的路径映射（容器路径={container_path}）"

    # 计算相对路径部分 + 拼接到 NAS 根
    best_cp = (best["container_path"] or "").replace("\\", "/").rstrip("/")
    if cp_norm == best_cp:
        rel = ""
    else:
        # cp_norm starts with best_cp + "/" guaranteed by match logic
        rel = cp_norm[len(best_cp) + 1:]  # 去掉前缀 + '/'
    nas_raw = best["nas_path"] if rel == "" else os.path.join(best["nas_path"], rel.replace("/", os.sep))

    # [防护 3] normpath 后必须以 NAS 前缀开头
    nas_norm = _safe_normpath(nas_raw)
    nas_base_norm = _safe_normpath(best["nas_path"])

    # 3-a: 结果不得恰好等于 NAS 根目录（意味着用户尝试定位"目录"本身而非目录内文件）
    if nas_norm == nas_base_norm:
        return None, None, "禁止映射到目录根本身（必须是目录下的具体文件）"

    # 3-b: 结果必须以 nas_base + sep 开头
    prefix_ok = nas_norm.startswith(nas_base_norm + os.sep)
    # 因为 Windows 下 nas_base 'E:\\x' 和 nas_norm 'E:\\x-y' 都以 'E:\\x' 开头但前者不是子路径
    # 3-a 已经排除等于的情形，因此前缀末尾必须有 os.sep
    if not prefix_ok:
        return None, None, "路径越权拦截（结果超出 NAS 前缀范围，疑似越权）"

    # 计算角色
    role = best.get("role") or detect_role_by_container_path(best_cp)

    # OK
    return nas_norm, role, None
