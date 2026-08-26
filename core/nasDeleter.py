"""
core/nasDeleter.py
====================
NAS 物理删除执行引擎 — 安全的最后一道闸门

核心流程：
  for 每个 item (已在 page 层完成路径解析 + 角色计算):
    1. DryRun：盘不删、Immich API 不调；仅打标 "DryRun-模拟，不删除"。
    2. 决定是否允许磁盘 unlink：
       permit_unlink = role=="外部媒体库" AND detail.get("isExternal") is True
       【双保险】：单一条件不满足就不能 unlink。
    3. permit_unlink=True && !DryRun -> os.unlink(nas_path)，失败异常捕获入日志。
       permit_unlink=False && !DryRun -> 标记 "skip:仅走ImmichAPI(非外部库)"
                         或 "双保险未通过(isExternal=False / role不匹配)"。
    4. !DryRun -> 把 asset_id 加入 batch_ids；最终聚合调用 deleteAssetsBulk(ids, force)。
       聚合一次 DELETE API 调用，避免每条一次 HTTP。
    5. 逐条写入 detail 记录，最后 append_operation_log 入库。

返回值: (report_dict, log_id)
"""
import os
import uuid
import time
import json
from typing import Any, Dict, List, Tuple

# intra-app imports
try:
    from db import append_operation_log
except Exception:  # pragma: no cover - fallback
    append_operation_log = None

try:
    from api import deleteAssetsBulk
except Exception:  # pragma: no cover
    deleteAssetsBulk = None


# --------------------------------------------------------------------
# Public
# --------------------------------------------------------------------
def execute_batch(
    immich_server_url: str,
    api_key: str,
    items: List[Dict[str, Any]],
    mapping: List[Dict[str, Any]],  # 预留：当前 nasDeleter 不再做路径解析
    dry_run: bool,
    force: bool,
    batch_id: str = None,
) -> Tuple[Dict[str, Any], int]:
    """
    Args:
        items: 每项需包含
            {"asset_id", "originalPath", "nas_path"|"", "role",
             "asset": dict(raw immich asset), "detail": dict(getAssetDetail返回)}
             注意 nas_path 与 role 由上层在页面中预先调用 container_to_nas 算好并校验。
    Returns:
        (report, log_id)
            report = {
                "batch_id": str,
                "dry_run": bool, "force": bool,
                "started_at": iso, "finished_at": iso,
                "items": [ {asset_id, container_path, nas_path, role, is_external, disk_action, api_result} ]
                "summary": {"total": N, "deleted_unlink": K, "skip_non_external": M, "errors_disk": E}
            }
            log_id = settings.db operation_logs 新插入行 id
    """
    started_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    if not batch_id:
        batch_id = f"batch-{int(time.time())}-{uuid.uuid4().hex[:6]}"

    detail_rows: List[Dict[str, Any]] = []
    summary = {
        "total": 0, "deleted_unlink": 0, "skip_non_external": 0,
        "errors_disk": 0, "api_called": False, "api_status_code": 0,
    }
    ids_for_api_batch: List[str] = []

    dry_run = bool(dry_run)
    force = bool(force)

    # ----- Phase 1: per-item disk -----
    for it in (items or []):
        asset_id = str(it.get("asset_id", ""))
        container_path = str(it.get("originalPath") or it.get("container_path") or "")
        nas_path = it.get("nas_path")
        role = str(it.get("role") or "")
        detail = it.get("detail") or {}
        is_external = bool(detail.get("isExternal", False))

        row = {
            "asset_id": asset_id,
            "container_path": container_path,
            "nas_path": nas_path,
            "role": role,
            "is_external": is_external,
            "disk_action": "",
            "api_result": "",
        }

        if dry_run:
            row["disk_action"] = "DryRun-模拟，不删除"
            row["api_result"] = "DryRun-不调用API"
        else:
            # 双保险判定
            permit = (role == "外部媒体库") and (is_external is True)
            if permit:
                if not nas_path or not isinstance(nas_path, str):
                    row["disk_action"] = "skip:nas_path空或无效"
                    summary["errors_disk"] += 1
                else:
                    # 最后再做一次安全校验（防止 page 层未来重构绕过）
                    if os.path.isfile(nas_path) or os.path.lexists(nas_path):
                        try:
                            os.unlink(nas_path)
                            row["disk_action"] = "unlink:ok"
                            summary["deleted_unlink"] += 1
                        except FileNotFoundError:
                            row["disk_action"] = "unlink:文件已不存在"
                            summary["errors_disk"] += 1
                        except Exception as e:
                            row["disk_action"] = f"unlink:error({e.__class__.__name__}:{e})"
                            summary["errors_disk"] += 1
                    else:
                        # nas_path 不存在（可能路径映射错、或已被人工删）
                        row["disk_action"] = "skip:nas_path不存在(可能映射错误或已删除)"
                        summary["errors_disk"] += 1
            else:
                # 非外部库 or isExternal=False  -> 严禁 unlink
                if role != "外部媒体库":
                    row["disk_action"] = "skip:仅走ImmichAPI(非外部库)"
                    summary["skip_non_external"] += 1
                else:
                    row["disk_action"] = f"双保险未通过(role={role},isExternal={is_external})→不允许unlink"
                    summary["skip_non_external"] += 1

            # 标记该资产需参与 Immich API 批量删除
            ids_for_api_batch.append(asset_id)

        detail_rows.append(row)
        summary["total"] += 1

    # ----- Phase 2: Immich bulk API (非 DryRun，且有 id) -----
    api_status = 0
    api_body_text = ""
    api_ok = False
    if (not dry_run) and ids_for_api_batch and callable(deleteAssetsBulk):
        # 期望 Immich DELETE /api/assets body: {"ids":[...], "force": bool}
        payload_data = json.dumps({"ids": ids_for_api_batch, "force": bool(force)})
        api_ok, api_status, api_body_text = deleteAssetsBulk(
            immich_server_url, api_key, ids_for_api_batch,
            force=force, data=payload_data,
        )
        summary["api_called"] = True
        summary["api_status_code"] = api_status
        # 把聚合 API 结果回写到每条 row（省空间简单写一样的）
        aggregated = f"BULK status={api_status};ok={api_ok}"
        for r in detail_rows:
            if r["api_result"] == "":  # 只补非 DryRun 的
                r["api_result"] = aggregated
    elif dry_run:
        pass  # rows 已设 DryRun-不调用API
    elif not ids_for_api_batch:
        for r in detail_rows:
            if r["api_result"] == "":
                r["api_result"] = "N/A(无asset_id参与批量API)"
    else:
        for r in detail_rows:
            if r["api_result"] == "":
                r["api_result"] = "N/A(deleteAssetsBulk不可用)"

    finished_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    report = {
        "batch_id": batch_id,
        "dry_run": dry_run,
        "force": force,
        "started_at": started_at,
        "finished_at": finished_at,
        "summary": summary,
        "items": detail_rows,
    }

    # ----- Phase 3: 日志入库 -----
    log_id = 0
    if callable(append_operation_log):
        log_id = append_operation_log(
            batch_id=batch_id,
            dry_run=1 if dry_run else 0,
            force=1 if force else 0,
            detail_json=report,
        )
    report["log_id"] = log_id

    return report, log_id
