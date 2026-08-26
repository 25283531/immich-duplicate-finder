"""
tests/test_smartSelect.py
=========================
C1 阶段: smartSelect 打分策略验证
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestScoreAsset(unittest.TestCase):
    """ score_asset(asset, detail, role) -> float 分数 """

    def test_missing_function(self):
        from core.smartSelect import score_asset
        # 全空资产 -> 0 分
        s = score_asset({}, {}, "外部媒体库")
        self.assertIsInstance(s, (int, float))

    def test_favorite_boost(self):
        """ isFavorite=True 必须显著高于 False（至少 +20）"""
        from core.smartSelect import score_asset
        base = {"id": "A"}
        a_score = score_asset({"isFavorite": False}, {}, "外部媒体库")
        b_score = score_asset({"isFavorite": True}, {}, "外部媒体库")
        self.assertGreaterEqual(b_score - a_score, 20, msg=f"isFavorite 加分不足 (+{b_score-a_score})")

    def test_album_member_boost(self):
        """ detail 中 albumIds 非空 -> 比空至少 +10 分 """
        from core.smartSelect import score_asset
        no_album = score_asset({}, {"albumIds": []}, "外部媒体库")
        in_album = score_asset({}, {"albumIds": ["x"]}, "外部媒体库")
        self.assertGreaterEqual(in_album - no_album, 10)

    def test_not_trashed_boost(self):
        """ isTrashed=False 至少比 isTrashed=True 高 +5 """
        from core.smartSelect import score_asset
        t = score_asset({"isTrashed": True}, {}, "外部媒体库")
        n = score_asset({"isTrashed": False}, {}, "外部媒体库")
        self.assertGreaterEqual(n - t, 5)

    def test_resolution_boost(self):
        """ 高分辨率得分必须更高 """
        from core.smartSelect import score_asset
        low = {"exifInfo": {"exifImageHeight": 720, "exifImageWidth": 1280}}
        high = {"exifInfo": {"exifImageHeight": 4000, "exifImageWidth": 6000}}
        self.assertGreater(score_asset(high, {}, "外部媒体库"), score_asset(low, {}, "外部媒体库"))

    def test_external_role_bonus(self):
        """ 角色 == 外部媒体库 要比 内部库原图目录 略高（保留原图来源偏好）"""
        from core.smartSelect import score_asset
        asset = {}
        ext = score_asset(asset, {}, "外部媒体库")
        lib = score_asset(asset, {}, "内部库原图目录")
        self.assertGreater(ext, lib)

    def test_size_boost(self):
        """ 文件更大（保留更高质量）"""
        from core.smartSelect import score_asset
        small = {"exifInfo": {"fileSizeInByte": 1 * 1024 * 1024}}
        big = {"exifInfo": {"fileSizeInByte": 10 * 1024 * 1024}}
        self.assertGreater(score_asset(big, {}, "外部媒体库"), score_asset(small, {}, "外部媒体库"))


class TestPickDeletionCandidates(unittest.TestCase):
    """ 在重复组里选出"要删除的候选"（保留分数最高的）"""

    def test_missing_function(self):
        from core.smartSelect import pick_deletion_candidates
        self.assertTrue(callable(pick_deletion_candidates))

    def test_three_assets_keep_highest(self):
        """ 3 个 asset 的组：得分最高的保留，另外两个为删除候选 """
        from core.smartSelect import score_asset, pick_deletion_candidates
        group = [
            {"asset_id": "keep",  "asset": {"isFavorite": True},
             "detail": {"albumIds": ["A1", "A2"]}, "role": "外部媒体库"},
            {"asset_id": "del1",  "asset": {"isFavorite": False},
             "detail": {"albumIds": []}, "role": "内部库原图目录"},
            {"asset_id": "del2",  "asset": {"isFavorite": False, "isTrashed": True},
             "detail": {"albumIds": []}, "role": "缓存目录(/data)"},
        ]
        keepers, to_delete = pick_deletion_candidates(group, keep_count=1)
        self.assertEqual(len(keepers), 1)
        self.assertEqual(keepers[0]["asset_id"], "keep")
        self.assertEqual(len(to_delete), 2)
        self.assertTrue(all(x["asset_id"] in ("del1", "del2") for x in to_delete))

    def test_tie_behavior(self):
        """ 分数完全相等时，要 deterministic 稳定（依赖 asset_id 字典序）"""
        from core.smartSelect import pick_deletion_candidates
        group = [
            {"asset_id": "Z-1", "asset": {}, "detail": {}, "role": "外部媒体库"},
            {"asset_id": "A-1", "asset": {}, "detail": {}, "role": "外部媒体库"},
        ]
        _, to_delete = pick_deletion_candidates(group, keep_count=1)
        self.assertEqual(len(to_delete), 1)
        # 两者相同：删除 id 靠后的 (Z-1)，保留 id 靠前的 (A-1)
        self.assertEqual(to_delete[0]["asset_id"], "Z-1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
