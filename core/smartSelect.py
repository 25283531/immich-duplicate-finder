"""
core/smartSelect.py
====================
Smart Keeper 打分策略：在一组重复资产中选出"最值得保留的那个"

打分规则（来自计划：权重与 PHP 参考脚本偏好一致）
  +30  isFavorite == True
  +20  asset 出现在 ≥1 个相册（detail["albumIds"] 非空）
  +10  not isTrashed（在回收站了就没必要继续保留）
  +size_MB   文件大小/1024²（越大越可能是原图）
  +resolution 分辨率归一化奖励（(w*h)/1e6 的 5 倍，封顶 +5）
  +EXIF 丰富度 × 2（exifInfo 非空键数）
  +3   role == "外部媒体库"（偏向保留外部库的物理原件）

决定规则：
  pick_deletion_candidates(group, keep_count=1)
    - 对组内每个 asset 算分并降序
    - 分数相同时用 asset_id 字典序升序（保证 determinism）
    - 前 keep_count 个为 keepers；其余为 to_delete
"""
from typing import Any, Dict, List, Tuple


def _exif_info(asset: Dict[str, Any]) -> Dict[str, Any]:
    return asset.get("exifInfo") or {}


def score_asset(asset: Dict[str, Any], detail: Dict[str, Any], role: str) -> float:
    """ 计算单个资产的保留价值分数（越高越应该保留）"""
    score = 0.0

    # 1) isFavorite
    if asset.get("isFavorite"):
        score += 30.0

    # 2) album membership（来自 getAssetDetail 返回）
    album_ids = detail.get("albumIds") if isinstance(detail, dict) else None
    if album_ids and len(album_ids) > 0:
        score += 20.0

    # 3) not isTrashed
    if not asset.get("isTrashed", False):
        score += 10.0

    # 4) size in MB / 10
    exif = _exif_info(asset)
    size_b = exif.get("fileSizeInByte")
    if isinstance(size_b, (int, float)) and size_b > 0:
        score += float(size_b) / (1024 * 1024)  # 已经自然体现"越大越好"

    # 5) resolution normalized，封顶 +5
    try:
        w = exif.get("exifImageWidth")
        h = exif.get("exifImageHeight")
        if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
            norm = (w * h) / 1_000_000.0  # MP 计数
            score += min(norm * 5, 5.0)
    except Exception:
        pass

    # 6) EXIF 非空字段数 × 2（信息越丰富越保留原片）
    try:
        exif_non_empty = sum(
            1 for v in exif.values()
            if v is not None and v != "" and v != 0
        )
        score += exif_non_empty * 2.0
    except Exception:
        pass

    # 7) 角色偏好：外部媒体库 +3（优先保留 NAS 物理原件来源）
    if role == "外部媒体库":
        score += 3.0
    # 内部库 & 缓存不加分；缓存反而略"贬值"让其先删
    if role == "缓存目录(/data)":
        score -= 1.0
    if role == "Postgres数据库目录":
        score -= 100.0  # 安全保险：DB 文件永远保留到最后

    return score


def pick_deletion_candidates(
    group: List[Dict[str, Any]],
    keep_count: int = 1,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Args:
        group: 同组重复资产，每项形如：
            {"asset_id": str, "asset": dict(原始immich资产), "detail": dict(getAssetDetail), "role": str}
        keep_count: 每组保留多少张（默认 1）
    Returns:
        (keepers, to_delete) 两个列表，都是 group 内的子集（不深拷贝）
    """
    if not group:
        return [], []
    k = max(1, int(keep_count))
    k = min(k, len(group) - 1) if len(group) > 1 else 0  # 至少删除 1 个

    # 计算 (score, id_asc tiebreaker, index)
    entries = []
    for idx, item in enumerate(group):
        s = score_asset(item.get("asset", {}), item.get("detail", {}), item.get("role", "外部媒体库"))
        entries.append((s, item.get("asset_id", ""), idx, item))

    # 排序：-score 降序 + asset_id 升序（相同分数下 ID 小者优先保留）
    entries.sort(key=lambda t: (-t[0], t[1]))

    keepers = [t[3] for t in entries[:keep_count]]
    to_delete = [t[3] for t in entries[keep_count:]]
    return keepers, to_delete
