"""
tests/test_nasDeleter.py
=========================
C2 阶段: nasDeleter 引擎 — 安全红线集合
  1. DryRun 模式：任何时候不 unlink 文件、不调用 Immich DELETE API；仅记录日志。
  2. force=False：只调用 Immich API（回收站）。
  3. role==外部媒体库 + detail.isExternal==True 双保险才允许 NAS 物理 unlink。
  4. 其他 role（内部库/缓存/PG）即使 force=True 也禁止磁盘 unlink。
  5. 每条资产都写入 operation_logs（detail JSON 结构与 PHP 参考一致）。
  6. execute_batch 返回 (report, log_id)。
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestNasDeleterDryRun(unittest.TestCase):
    """ DryRun=1：仅模拟，绝不真实删除 """

    @staticmethod
    def _item(asset_id, container_path, role, nas_path, is_external=True):
        return {
            "asset_id": asset_id,
            "originalPath": container_path,
            "asset": {"id": asset_id},
            "detail": {"id": asset_id, "isExternal": is_external, "albumIds": [], "ownerId": "U"},
            "role": role,
            "nas_path": nas_path,  # 由 page 层先解析好；nasDeleter 不再重复解析只做安全检查
        }

    def test_dryrun_does_not_unlink_or_api(self):
        from core.nasDeleter import execute_batch
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "exists.jpg")
            open(f, "w").write("jpeg data")
            items = [self._item("A1", "/volume1/family/a.jpg", "外部媒体库", nas_path=f, is_external=True)]
            calls = {"unlink": 0, "api": 0}
            real_unlink = os.unlink

            def fake_unlink(p, **kw):
                calls["unlink"] += 1
                raise AssertionError(f"DryRun 期间不该调用 unlink! path={p}")
            with mock.patch.object(os, "unlink", side_effect=fake_unlink):
                fake_delete = mock.Mock(return_value=(False, 0, "mock: dry run forbid"))
                with mock.patch("api.deleteAssetsBulk", side_effect=fake_delete) as d:
                    report, log_id = execute_batch(
                        immich_server_url="http://localhost:2283",
                        api_key="KEY",
                        items=items,
                        mapping=[],  # nasDeleter 不负责映射解析（输入 items 已含 nas_path）
                        dry_run=True,
                        force=False,
                        batch_id="batch-dryrun",
                    )
                    self.assertEqual(calls["api"], 0, "DryRun 禁止调用 deleteAssetsBulk")
                    self.assertFalse(d.called, "DryRun 禁止调用 Immich 删除 API")
            self.assertTrue(os.path.exists(f), "DryRun 期间文件必须保留")
            # report 必须给出明确的 DryRun 标记
            self.assertTrue(report.get("dry_run", False))
            rows = report.get("items") or []
            self.assertEqual(rows[0]["asset_id"], "A1")
            self.assertEqual(rows[0]["disk_action"], "DryRun-模拟，不删除")
            self.assertEqual(rows[0]["api_result"], "DryRun-不调用API")

    def test_external_real_delete_unlinks_file(self):
        """ 非 DryRun，外部媒体库 + isExternal=True：必须 unlink 真实文件，且 Immich API 调用 force=False 进入回收站 """
        from core.nasDeleter import execute_batch
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "real.bin")
            with open(f, "wb") as fh:
                fh.write(b"x" * 1000)
            self.assertTrue(os.path.exists(f))
            items = [self._item("R1", "/vol/a.bin", "外部媒体库", nas_path=f, is_external=True)]
            with mock.patch("core.nasDeleter.deleteAssetsBulk", return_value=(True, 204, "")) as d:
                report, log_id = execute_batch(
                    "http://s", "KEY", items, mapping=[],
                    dry_run=False, force=False, batch_id="batch-real"
                )
            self.assertFalse(os.path.exists(f), "外部库文件必须被 unlink")
            rows = report["items"]
            self.assertEqual(rows[0]["disk_action"], "unlink:ok")
            # 必须调用 deleteAssetsBulk，且 force=False
            import json
            self.assertTrue(d.called, "deleteAssetsBulk 必须被调用")
            payload = json.loads(d.call_args[1]["data"])
            self.assertFalse(payload["force"])
            self.assertEqual(payload["ids"], ["R1"])

    def test_internal_library_no_unlink_even_force_true(self):
        """ role=内部库原图目录：即使 force=True，也不能执行磁盘 unlink；只走 Immich API（force 按用户设定）"""
        from core.nasDeleter import execute_batch
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "library.jpeg")
            with open(f, "wb") as fh:
                fh.write(b"jpg")
            items = [self._item("LIB1", "/data/library/a.jpeg", "内部库原图目录", nas_path=f)]
            with mock.patch("core.nasDeleter.deleteAssetsBulk", return_value=(True, 204, "")) as d:
                report, log_id = execute_batch(
                    "http://s", "KEY", items, mapping=[],
                    dry_run=False, force=True, batch_id="lib-force"
                )
            self.assertTrue(os.path.exists(f), "内部库文件严禁磁盘 unlink！")
            row = report["items"][0]
            self.assertEqual(row["disk_action"], "skip:仅走ImmichAPI(非外部库)")
            # 但 Immich API 必须被调用且 force=True（因为 UI 勾选了 FORCE）
            import json
            self.assertTrue(d.called)
            payload = json.loads(d.call_args[1]["data"])
            self.assertTrue(payload["force"])

    def test_role_external_but_isExternal_false_no_unlink(self):
        """ role=外部媒体库 但 getAssetDetail().isExternal=False ：禁止 unlink（双保险）"""
        from core.nasDeleter import execute_batch
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "claim_ext.jpg")
            with open(f, "wb") as fh:
                fh.write(b"data")
            items = [self._item("B9", "/vol/x.jpg", "外部媒体库", nas_path=f, is_external=False)]
            with mock.patch("core.nasDeleter.deleteAssetsBulk", return_value=(True, 204, "")):
                report, log_id = execute_batch("http://s", "KEY", items, mapping=[],
                                               dry_run=False, force=False, batch_id="double-check")
            self.assertTrue(os.path.exists(f), "双保险不通过：isExternal=False 时禁止 unlink")
            row = report["items"][0]
            self.assertIn("双保险未通过", row["disk_action"])


class TestNasDeleterLogging(unittest.TestCase):
    @staticmethod
    def _item(asset_id):
        return {
            "asset_id": asset_id,
            "originalPath": f"/data/library/{asset_id}.jpg",
            "asset": {"id": asset_id},
            "detail": {"id": asset_id, "isExternal": False, "albumIds": [], "ownerId": "U"},
            "role": "内部库原图目录",
            "nas_path": None,
        }

    def test_log_written_to_db(self):
        from db import (
            startup_db_configurations, startup_path_mapping_db, startup_operation_logs_db,
            count_operation_logs, query_operation_logs,
        )
        startup_db_configurations(); startup_path_mapping_db(); startup_operation_logs_db()
        before = count_operation_logs()
        from core.nasDeleter import execute_batch
        with mock.patch("api.deleteAssetsBulk", return_value=(True, 204, "")):
            report, log_id = execute_batch(
                "http://s", "KEY", [self._item("LOG1"), self._item("LOG2")],
                mapping=[], dry_run=False, force=False, batch_id="b-log"
            )
        self.assertIsInstance(log_id, int)
        self.assertEqual(count_operation_logs(), before + 1)
        rows = query_operation_logs(limit=1)
        last = rows[0]
        self.assertEqual(last["batch_id"], "b-log")
        self.assertEqual(last["dry_run"], 0)
        self.assertEqual(last["force"], 0)
        items = last["detail_json"].get("items", [])
        self.assertEqual(len(items), 2)
        ids = sorted(x["asset_id"] for x in items)
        self.assertEqual(ids, ["LOG1", "LOG2"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
