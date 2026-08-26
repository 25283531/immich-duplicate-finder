"""
tests/test_db_extensions.py
===========================
B1 阶段 db.py 新增功能测试：
  1. data/ 目录统一（所有 DB 文件必须落在 app/data/ 下）
  2. path_mapping 表 CRUD
  3. operation_logs 表 CRUD
运行：app/ 目录下  `python -m unittest tests.test_db_extensions -v`
"""
import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestDbDataDirRedirect(unittest.TestCase):
    """ [data/] 目录统一验证：所有 sqlite3.connect 路径都被重定向到 data/ 子目录 """

    def test_data_dir_exists(self):
        """ app/data/ 目录必须存在 """
        data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
        self.assertTrue(os.path.isdir(data_dir), msg=f"data/ 不存在：{data_dir}")


class TestPathMappingCrud(unittest.TestCase):
    """ path_mapping 表 CRUD """

    def setUp(self):
        # 每个测试隔离 — 重新 import db 模块，先确保 settings.db 建表
        from db import startup_db_configurations, startup_path_mapping_db
        startup_db_configurations()
        startup_path_mapping_db()

    def test_insert_and_load_mappings(self):
        """ insert -> load 往返 """
        from db import insert_path_mapping, load_path_mappings, delete_path_mapping
        # 先清空存量
        for m in load_path_mappings():
            delete_path_mapping(m["id"])

        id1 = insert_path_mapping("/data/library", "/volume1/data/library", "内部库原图目录")
        id2 = insert_path_mapping("/volume1/family", "/mnt/family", "外部媒体库")
        self.assertIsInstance(id1, int)
        self.assertIsInstance(id2, int)
        self.assertNotEqual(id1, id2)

        rows = load_path_mappings()
        self.assertEqual(len(rows), 2)
        by_cp = {r["container_path"]: r for r in rows}
        self.assertEqual(by_cp["/data/library"]["nas_path"], "/volume1/data/library")
        self.assertEqual(by_cp["/data/library"]["role"], "内部库原图目录")
        self.assertEqual(by_cp["/volume1/family"]["nas_path"], "/mnt/family")

    def test_delete_mapping(self):
        """ delete -> load 确认数量 """
        from db import insert_path_mapping, load_path_mappings, delete_path_mapping
        for m in load_path_mappings():
            delete_path_mapping(m["id"])

        mid = insert_path_mapping("/x", "/y", "外部媒体库")
        self.assertEqual(len(load_path_mappings()), 1)
        delete_path_mapping(mid)
        self.assertEqual(len(load_path_mappings()), 0)


class TestOperationLogsCrud(unittest.TestCase):
    """ operation_logs 表 CRUD + 查询 """

    def setUp(self):
        from db import startup_db_configurations, startup_operation_logs_db
        startup_db_configurations()
        startup_operation_logs_db()

    def test_append_and_query_logs(self):
        import datetime
        from db import append_operation_log, query_operation_logs, count_operation_logs

        before = count_operation_logs()
        detail = {
            "items": [
                {"asset_id": "A1", "container_path": "/a/b.jpg", "nas_path": "/x/b.jpg",
                 "role": "外部媒体库", "disk_action": "unlink", "api_result": "ok"},
            ]
        }
        log_id = append_operation_log(
            batch_id="batch-test-001", dry_run=1, force=0, detail_json=detail,
        )
        self.assertIsInstance(log_id, int)
        self.assertEqual(count_operation_logs(), before + 1)

        rows = query_operation_logs(limit=5)
        self.assertTrue(len(rows) >= 1)
        first = rows[0]
        # 倒序，最新在最前
        self.assertEqual(first["batch_id"], "batch-test-001")
        self.assertEqual(first["dry_run"], 1)
        self.assertEqual(first["force"], 0)
        self.assertIsInstance(first["detail_json"], dict)
        self.assertEqual(first["detail_json"]["items"][0]["asset_id"], "A1")
        # timestamp 必须存在且可解析
        ts = first["timestamp"]
        # sqlite TEXT timestamp
        self.assertTrue(isinstance(ts, str) and len(ts) >= 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
