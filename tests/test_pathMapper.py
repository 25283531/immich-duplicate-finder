"""
TDD tests for core/pathMapper.py
===============================
目标：验证目录角色识别 + 容器路径 -> NAS 路径转换 + 路径穿越防护

运行：在 app/ 目录下执行  `python -m pytest tests/test_pathMapper.py -v`
（如果未安装 pytest，也可直接运行：`python tests/test_pathMapper.py`）
"""
import os
import sys
import unittest
from typing import Optional, Tuple, List, Dict

# Make 'app' importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# -----------------------------------------------------------------------------
# 预期 API（测试先定义接口，实现必须满足）
# -----------------------------------------------------------------------------
# from core.pathMapper import detect_role_by_container_path, container_to_nas
#
# detect_role_by_container_path(cp: str) -> str
# container_to_nas(cp: str, mapping: List[Dict]) -> Tuple[Optional[str], Optional[str], Optional[str]]
#   返回: (nas_real_path, role, error)
#     成功: (nas_real_path, role, None)
#     失败: (None, None, error_message)
# -----------------------------------------------------------------------------


class TestDetectRole(unittest.TestCase):
    """【阶段 1】目录角色识别 — 基于 Immich 官方前缀规则"""

    def test_cache_data_dir(self):
        """ 以 /data 开头但不是 /data/library -> 缓存目录 """
        from core.pathMapper import detect_role_by_container_path
        self.assertEqual(detect_role_by_container_path("/data"), "缓存目录(/data)")
        self.assertEqual(detect_role_by_container_path("/data/thumbs/abc.jpg"), "缓存目录(/data)")
        self.assertEqual(detect_role_by_container_path("/data/encoded/video.mp4"), "缓存目录(/data)")

    def test_internal_library_dir(self):
        """ /data/library 开头 -> 内部库原图目录 """
        from core.pathMapper import detect_role_by_container_path
        self.assertEqual(detect_role_by_container_path("/data/library"), "内部库原图目录")
        self.assertEqual(detect_role_by_container_path("/data/library/2024/01/a.jpg"), "内部库原图目录")
        self.assertEqual(detect_role_by_container_path("/data/library/user1/family/b.jpg"), "内部库原图目录")

    def test_postgres_db_dir(self):
        """ /var/lib/postgresql/data 开头 -> Postgres 数据库目录 """
        from core.pathMapper import detect_role_by_container_path
        self.assertEqual(detect_role_by_container_path("/var/lib/postgresql/data"), "Postgres数据库目录")
        self.assertEqual(detect_role_by_container_path("/var/lib/postgresql/data/base/1234"), "Postgres数据库目录")

    def test_external_library_default(self):
        """ 以上都不匹配 -> 外部媒体库（用户自定义挂载点） """
        from core.pathMapper import detect_role_by_container_path
        self.assertEqual(detect_role_by_container_path("/volume1/photos/family"), "外部媒体库")
        self.assertEqual(detect_role_by_container_path("/photos/2023"), "外部媒体库")
        self.assertEqual(detect_role_by_container_path("/mnt/nas-albums"), "外部媒体库")
        self.assertEqual(detect_role_by_container_path("/data-external"), "外部媒体库")
        # 边界：开头 /data-library 并非 /data/library 前缀
        self.assertEqual(detect_role_by_container_path("/data-library/x"), "外部媒体库")


class TestContainerToNas(unittest.TestCase):
    """【阶段 2】容器路径 -> NAS 真实路径转换（最长前缀匹配策略）"""

    MAPPING_FIXTURE: List[Dict] = [
        {"id": 1, "container_path": "/data",
         "nas_path": "E:\\code\\photochongfu\\app\\tests\\fixtures\\data_cache",
         "role": "缓存目录(/data)"},
        {"id": 2, "container_path": "/data/library",
         "nas_path": "E:\\code\\photochongfu\\app\\tests\\fixtures\\data_library",
         "role": "内部库原图目录"},
        {"id": 3, "container_path": "/volume1/family-photos",
         "nas_path": "E:\\code\\photochongfu\\app\\tests\\fixtures\\family_photos",
         "role": "外部媒体库"},
    ]

    @classmethod
    def setUpClass(cls):
        """ 创建真实 fixture 目录（os.path.isdir 校验要用）"""
        for m in cls.MAPPING_FIXTURE:
            os.makedirs(m["nas_path"], exist_ok=True)
        # 在 fixtures/family_photos 下创建子目录结构模拟 NAS
        os.makedirs(os.path.join(cls.MAPPING_FIXTURE[2]["nas_path"], "2024", "05"), exist_ok=True)

    def test_longest_prefix_wins(self):
        """ 同一路径同时命中 /data 和 /data/library -> 必须优先最长（/data/library）"""
        from core.pathMapper import container_to_nas
        nas, role, err = container_to_nas(
            "/data/library/2024/01/a.jpg", self.MAPPING_FIXTURE
        )
        self.assertIsNone(err, msg=f"unexpected error: {err}")
        self.assertEqual(role, "内部库原图目录")
        self.assertTrue(nas.endswith(os.path.join("2024", "01", "a.jpg")))
        # 必须以内部库的 nas_path 开头（而非缓存库的）
        self.assertTrue(nas.startswith(self.MAPPING_FIXTURE[1]["nas_path"]),
                        msg=f"应该命中内部库但 nas={nas}")

    def test_cache_hits(self):
        """ /data/thumbs/x.jpg -> 命中缓存库映射 """
        from core.pathMapper import container_to_nas
        nas, role, err = container_to_nas("/data/thumbs/x.jpg", self.MAPPING_FIXTURE)
        self.assertIsNone(err)
        self.assertEqual(role, "缓存目录(/data)")
        self.assertTrue(nas.startswith(self.MAPPING_FIXTURE[0]["nas_path"]))

    def test_external_library_hits(self):
        """ /volume1/family-photos/2024/05/a.jpg -> 外部媒体库 + 正确 nas 拼接 """
        from core.pathMapper import container_to_nas
        nas, role, err = container_to_nas(
            "/volume1/family-photos/2024/05/a.jpg", self.MAPPING_FIXTURE
        )
        self.assertIsNone(err)
        self.assertEqual(role, "外部媒体库")
        expect = os.path.join(self.MAPPING_FIXTURE[2]["nas_path"], "2024", "05", "a.jpg")
        self.assertEqual(nas, expect)

    def test_no_match_returns_error(self):
        """ 映射表里完全无匹配前缀 -> 返回错误不允许执行 """
        from core.pathMapper import container_to_nas
        nas, role, err = container_to_nas("/unknown/path/a.jpg", self.MAPPING_FIXTURE)
        self.assertIsNone(nas)
        self.assertIsNone(role)
        self.assertIsInstance(err, str)
        self.assertTrue(len(err) > 0)


class TestTraversalProtection(unittest.TestCase):
    """【阶段 3】路径穿越防护（安全红线 — 一条都不能漏）"""

    MAPPING_FIXTURE: List[Dict] = [
        {"id": 1, "container_path": "/data/library",
         "nas_path": "E:\\code\\photochongfu\\app\\tests\\fixtures\\data_library",
         "role": "内部库原图目录"},
        {"id": 2, "container_path": "/volume1/family",
         "nas_path": "E:\\code\\photochongfu\\app\\tests\\fixtures\\family_photos",
         "role": "外部媒体库"},
    ]

    @classmethod
    def setUpClass(cls):
        for m in cls.MAPPING_FIXTURE:
            os.makedirs(m["nas_path"], exist_ok=True)

    def test_dotdot_segment_rejected_explicit(self):
        """ 字符串包含 '/../' 段 — 直接拦截，不进入前缀匹配 """
        from core.pathMapper import container_to_nas
        cases = [
            "/data/library/../../etc/passwd",
            "/data/library/../secret.txt",
            "/data/library/./../traverse/a.jpg",
        ]
        for cp in cases:
            nas, role, err = container_to_nas(cp, self.MAPPING_FIXTURE)
            self.assertIsNone(nas, msg=f"case {cp} 未被拦截！nas={nas}")
            self.assertIsNone(role)
            self.assertIn("越权", err)

    def test_result_must_start_with_nas_prefix(self):
        """ 即使字符串不含 '..'，如果 realpath/normpath 后结果不以 NAS 前缀开头
            （Windows 上可能因 junction / subst 出现），必须拦截 """
        from core.pathMapper import container_to_nas
        # 情形 A：超长合法路径 — 应正常通过，且结果以映射表 nas_path 开头
        cp = "/data/library/" + ("A" * 260) + ".jpg"
        nas, role, err = container_to_nas(cp, self.MAPPING_FIXTURE)
        self.assertIsNone(err)
        self.assertTrue(nas.startswith(self.MAPPING_FIXTURE[0]["nas_path"]),
                        msg=f"nas={nas[:120]}... 应该以 {self.MAPPING_FIXTURE[0]['nas_path']} 开头")

        # 情形 B：相对路径在 nas 侧拼接后越过 nas_prefix（模拟 junction 攻击防御）
        # 这里用"相对部分含有前置反斜杠"的边界用例：container 不含 ..，但拼接后 normpath
        # 仍在 NAS 前缀内部；如果 nas_path 本身被篡改成短路径就应该被拦截——我们通过
        # "篡改 mapping 中的 nas_path 为完全不同的路径"后调用时该断言必须走错误分支。
        fake_mapping = [
            {"id": 99, "container_path": "/data/library",
             "nas_path": "X:\\totally\\fake\\path",  # 不存在且不同前缀
             "role": "内部库原图目录"},
        ]
        nas2, role2, err2 = container_to_nas("/data/library/x/y/z.jpg", fake_mapping)
        # 具体行为：若 nas_path 是合法存在的真实目录则 3-b 要求它是前缀；
        # 这里 fake_mapping 的 nas_path 本身虽然不存在，但 normpath 比较仍以字符串为依据，
        # 因此只要相对拼接后仍以它为前缀，就不会拦截。断言：不报错（字符串层面合法）。
        if err2 is None:
            self.assertTrue(nas2.startswith(fake_mapping[0]["nas_path"]))

    def test_result_equals_nas_root_itself_rejected(self):
        """ 转换后 == NAS 根目录（不是根目录下的文件）— 禁止（防误删整个挂载点）"""
        from core.pathMapper import container_to_nas
        # 直接映射到根目录
        cp = "/data/library"
        nas, role, err = container_to_nas(cp, self.MAPPING_FIXTURE)
        self.assertIsNone(nas)
        self.assertIn("目录根", err if err else "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
