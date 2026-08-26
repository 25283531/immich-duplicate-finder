"""
tests/test_api_extensions.py
============================
A2 阶段：验证 api.py 的新功能

实际 Immich HTTP 请求不直接发起（用 Monkey patch requests 拦截）。
运行：app/ 目录下 `python -m unittest tests.test_api_extensions -v`
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestFetchAssetsCompatibility(unittest.TestCase):
    """ fetchAssets URL 兼容：先尝试 /api/assets（复数 v1.120+），404 回退 /api/asset/（单数旧版）"""

    @staticmethod
    def _fake_response(status_code, json_data=None, text=None, content_type="application/json"):
        resp = mock.Mock()
        resp.status_code = status_code
        resp.headers = {"Content-Type": content_type}
        resp.text = text if text is not None else ("[]" if json_data is None else __import__("json").dumps(json_data))
        resp.json = mock.Mock(return_value=([] if json_data is None else json_data))
        if status_code >= 400:
            def raise_for():
                import requests as _rq
                raise _rq.exceptions.HTTPError(f"{status_code} error")
            resp.raise_for_status = raise_for
        else:
            resp.raise_for_status = mock.Mock()
        return resp

    def test_plural_works_first_call_ok(self):
        """ 新版本支持 /api/assets -> 响应成功，只发起 1 次复数请求 """
        import api
        sample_assets = [
            {"id": "A1", "type": "IMAGE"},
            {"id": "A2", "type": "VIDEO"},
        ]
        with mock.patch.object(api.requests, "get", return_value=self._fake_response(200, sample_assets)) as g:
            # 清空 cache 否则 @st.cache_data 会命中
            api.fetchAssets.clear()
            # 绕过 st.* 我们直接模拟内部 fetch_call 逻辑更有意义
            call_counter = {"n": 0}
            real_get = api.requests.get

            def track(url, **kwargs):
                call_counter["n"] += 1
                call_counter[f"url{call_counter['n']}"] = url
                if "/api/assets" in url and not "/api/asset/" in url:
                    return self._fake_response(200, sample_assets)
                return self._fake_response(404, [])
            with mock.patch.object(api.requests, "get", side_effect=track):
                # 我们没法直接调 fetchAssets 因为它依赖 st.cache_data/UI 组件，
                # 因此直接测试 A2 新增的内部辅助函数 _fetch_assets_compat
                assets = api._fetch_assets_compat(
                    "http://immich.local", "KEY-123", 15, type_filter="IMAGE"
                )
        self.assertEqual(assets, [sample_assets[0]])
        self.assertEqual(call_counter["n"], 1)
        self.assertIn("/api/assets", call_counter["url1"])
        self.assertNotIn("/api/asset/", call_counter["url1"].replace("/api/assets", ""))

    def test_plural_404_then_singular_success(self):
        """ 旧 Immich：复数 404  ->  回退到单数 /api/asset/ 成功 """
        import api
        sample_assets = [{"id": "A1", "type": "IMAGE"}]
        call_order = []
        def track(url, **kwargs):
            call_order.append(url)
            if "/api/assets" in url and not url.endswith("/api/asset/") and not url.rstrip("/").endswith("/api/asset"):
                return self._fake_response(404, [])
            # singular endpoint
            return self._fake_response(200, sample_assets)
        with mock.patch.object(api.requests, "get", side_effect=track):
            assets = api._fetch_assets_compat("http://immich.local", "KEY", 15, "IMAGE")
        self.assertEqual(len(call_order), 2)
        self.assertIn("/api/assets", call_order[0])
        self.assertIn("/api/asset/", call_order[1])
        self.assertEqual(len(assets), 1)


class TestNewApiHelpers(unittest.TestCase):
    """ ping, getAssetDetail, deleteAssetsBulk """

    def test_ping_ok(self):
        import api
        resp_ok = mock.Mock(); resp_ok.status_code = 200; resp_ok.ok = True
        resp_ok.json = mock.Mock(return_value={"name": "immich"})
        with mock.patch.object(api.requests, "get", return_value=resp_ok) as g:
            ok = api.ping("http://immich.local", "KEY")
            self.assertTrue(ok)
            called_with = g.call_args
            self.assertIn("x-api-key", called_with[1]["headers"])

    def test_ping_fail(self):
        import api
        def boom(*a, **kw):
            raise api.requests.exceptions.ConnectionError("refused")
        with mock.patch.object(api.requests, "get", side_effect=boom):
            self.assertFalse(api.ping("http://no-host", "KEY"))

    def test_getAssetDetail(self):
        import api
        fake = {"id": "A1", "isExternal": True, "originalPath": "/data/library/a.jpg",
                "ownerId": "U1", "albumIds": ["ALB1"]}
        r = mock.Mock(); r.status_code = 200; r.ok = True
        r.json = mock.Mock(return_value=fake)
        with mock.patch.object(api.requests, "get", return_value=r) as g:
            detail = api.getAssetDetail("http://immich.local", "KEY", "A1")
        self.assertEqual(detail["id"], "A1")
        self.assertTrue(detail["isExternal"])
        self.assertEqual(detail["albumIds"], ["ALB1"])
        url_used = g.call_args[0][0]
        self.assertIn("/api/assets/A1", url_used)

    def test_deleteAssetsBulk_default_force_false(self):
        """ 默认 force=False（放入回收站），调用 DELETE /api/assets body={ids, force:false} """
        import api
        r = mock.Mock(); r.status_code = 204
        with mock.patch.object(api.requests, "delete", return_value=r) as d:
            ok, status, body = api.deleteAssetsBulk(
                "http://immich.local", "KEY", ["A1", "A2"], force=False
            )
        self.assertTrue(ok)
        self.assertEqual(status, 204)
        import json as _j
        call_payload = _j.loads(d.call_args[1]["data"])
        self.assertEqual(call_payload["ids"], ["A1", "A2"])
        self.assertFalse(call_payload["force"])  # 安全默认
        self.assertIn("/api/assets", d.call_args[0][0])
        self.assertEqual(d.call_args[1]["headers"]["x-api-key"], "KEY")

    def test_deleteAssetsBulk_force_true_payload(self):
        import api
        r = mock.Mock(); r.status_code = 204
        with mock.patch.object(api.requests, "delete", return_value=r) as d:
            ok, status, body = api.deleteAssetsBulk(
                "http://immich.local", "KEY", ["A1"], force=True
            )
        import json as _j
        call_payload = _j.loads(d.call_args[1]["data"])
        self.assertTrue(call_payload["force"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
