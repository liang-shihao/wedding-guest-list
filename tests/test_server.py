import http.client
import json
import tempfile
import threading
import unittest

from seat.security import RateLimiter
from seat.server import make_server

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


class ServerCase(unittest.TestCase):
    redirect_to = ""
    rate_limiter = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        kw = {"redirect_to": self.redirect_to}
        if self.rate_limiter is not None:
            kw["rate_limiter"] = self.rate_limiter()
        self.httpd = make_server("127.0.0.1", 0, self.tmp.name, "pw", **kw)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = None

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd.ctx.store = None
        self.tmp.cleanup()

    def req(self, method, path, body=None, headers=None, raw=False):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = dict(headers or {})
        if self.cookie:
            h["Cookie"] = self.cookie
        data = body
        if body is not None and not isinstance(body, (bytes, bytearray)):
            data = json.dumps(body).encode("utf-8")
            h.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=h)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        if raw:
            return resp, payload
        try:
            parsed = json.loads(payload) if payload else None
        except ValueError:
            parsed = None
        return resp, parsed

    def login(self):
        resp, _ = self.req("POST", "/api/admin/login", {"password": "pw"})
        self.assertEqual(resp.status, 200)
        self.cookie = resp.getheader("Set-Cookie").split(";")[0]

    def add(self, name, table, public_note="", private_note=""):
        resp, body = self.req("POST", "/api/admin/guests",
                              {"name": name, "table": table, "public_note": public_note,
                               "private_note": private_note})
        self.assertEqual(resp.status, 200, body)
        return body["id"]


class PublicTest(ServerCase):
    def test_index_served(self):
        resp, payload = self.req("GET", "/", raw=True)
        self.assertEqual(resp.status, 200)
        self.assertIn("text/html", resp.getheader("Content-Type"))
        resp, _ = self.req("GET", "/admin", raw=True)
        self.assertEqual(resp.status, 200)

    def test_static_traversal(self):
        for path in ("/static/../app.py", "/../app.py", "/seat/store.py", "/data/guests.db", "/static/index.html"):
            resp, _ = self.req("GET", path, raw=True)
            self.assertEqual(resp.status, 404, path)

    def test_search_public_has_no_private_note(self):
        self.login()
        gid = self.add("张三", "8", "新郎同学", "素食")
        self.add("张三丰", "3", "", "素食")
        self.cookie = None
        for path in ("/api/search?q=" + "%E5%BC%A0%E4%B8%89",  # 张三
                     "/api/search?q=" + "%E4%B8%89%E4%B8%B0",  # 三丰
                     f"/api/seat/{gid}"):
            resp, payload = self.req("GET", path, raw=True)
            self.assertEqual(resp.status, 200)
            self.assertNotIn("素食", payload.decode("utf-8"))
            self.assertNotIn(b"private_note", payload)
        resp, body = self.req("GET", "/api/search?q=%E5%BC%A0%E4%B8%89")
        self.assertEqual(body["mode"], "exact")
        self.assertEqual(body["results"][0]["table"], "8")

    def test_search_empty_400(self):
        resp, body = self.req("GET", "/api/search?q=%20")
        self.assertEqual(resp.status, 400)
        self.assertIn("error", body)
        resp, _ = self.req("GET", "/api/search")
        self.assertEqual(resp.status, 400)

    def test_seat_404(self):
        resp, _ = self.req("GET", "/api/seat/999")
        self.assertEqual(resp.status, 404)
        resp, _ = self.req("GET", "/api/seat/abc")
        self.assertEqual(resp.status, 404)

    def test_settings_public(self):
        resp, body = self.req("GET", "/api/settings")
        self.assertEqual(body, {"title": "", "date_text": "", "welcome": "", "has_floorplan": False})

    def test_nosniff_and_no_store_headers(self):
        resp, _ = self.req("GET", "/api/settings")
        self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff")
        resp, _ = self.req("GET", "/api/admin/guests")
        self.assertEqual(resp.getheader("Cache-Control"), "no-store")

    def test_body_too_large_413(self):
        resp, _ = self.req("POST", "/api/admin/login", b"x", headers={"Content-Length": str(7 * 1024 * 1024)})
        self.assertEqual(resp.status, 413)


class AdminTest(ServerCase):
    def test_admin_requires_login(self):
        for method, path in (("GET", "/api/admin/guests"), ("GET", "/api/admin/me"),
                             ("GET", "/api/admin/export"), ("POST", "/api/admin/import"),
                             ("PUT", "/api/admin/settings"), ("DELETE", "/api/admin/guests/1")):
            resp, _ = self.req(method, path, {} if method != "GET" else None)
            self.assertEqual(resp.status, 401, path)
        self.cookie = "admin=123.abc"
        resp, _ = self.req("GET", "/api/admin/guests")
        self.assertEqual(resp.status, 401)

    def test_login_cookie_flags(self):
        resp, _ = self.req("POST", "/api/admin/login", {"password": "pw"})
        c = resp.getheader("Set-Cookie")
        for part in ("HttpOnly", "SameSite=Strict", "Path=/", "Max-Age=604800"):
            self.assertIn(part, c)

    def test_login_and_crud(self):
        self.login()
        resp, _ = self.req("GET", "/api/admin/me")
        self.assertEqual(resp.status, 200)
        gid = self.add("李四", "主桌")
        resp, body = self.req("PUT", f"/api/admin/guests/{gid}", {"table": "10"})
        self.assertEqual(resp.status, 200)
        resp, body = self.req("GET", "/api/admin/guests")
        self.assertEqual(body["guests"][0]["table"], "10")
        self.assertIn("private_note", body["guests"][0])
        self.assertIn("dup_missing_note", body["guests"][0])
        resp, body = self.req("PUT", f"/api/admin/guests/{gid}", {"table": ""})
        self.assertEqual(resp.status, 400)
        resp, _ = self.req("PUT", "/api/admin/guests/999", {"table": "1"})
        self.assertEqual(resp.status, 404)
        resp, _ = self.req("DELETE", f"/api/admin/guests/{gid}")
        self.assertEqual(resp.status, 200)
        resp, body = self.req("GET", "/api/admin/guests")
        self.assertEqual(body["guests"], [])

    def test_dup_flag(self):
        self.login()
        a = self.add("王五", "1")
        self.add("王五", "2", "新娘同事")
        resp, body = self.req("GET", "/api/admin/guests")
        flags = {g["id"]: g["dup_missing_note"] for g in body["guests"]}
        self.assertTrue(flags[a])
        self.assertEqual(sum(flags.values()), 1)

    def test_logout(self):
        self.login()
        resp, _ = self.req("POST", "/api/admin/logout", {})
        self.assertIn("Max-Age=0", resp.getheader("Set-Cookie"))

    def test_login_wrong_401_then_locked_429(self):
        for _ in range(5):
            resp, body = self.req("POST", "/api/admin/login", {"password": "nope"})
            self.assertEqual(resp.status, 401)
        resp, _ = self.req("POST", "/api/admin/login", {"password": "pw"})
        self.assertEqual(resp.status, 429)

    def test_bad_json_400(self):
        resp, _ = self.req("POST", "/api/admin/login", b"{not json", headers={"Content-Type": "application/json"})
        self.assertEqual(resp.status, 400)

    def test_import_replace_and_errors(self):
        self.login()
        self.add("旧人", "1")
        resp, body = self.req("POST", "/api/admin/import", {"text": "姓名\t桌号\n\t8\n", "mode": "replace"})
        self.assertEqual(resp.status, 400)
        self.assertEqual(body["errors"], ["第 2 行：姓名为空"])
        resp, body = self.req("GET", "/api/admin/guests")
        self.assertEqual(len(body["guests"]), 1)
        resp, body = self.req("POST", "/api/admin/import",
                              {"text": "姓名\t桌号\t备注\n张三\t8\t素食\n李四\t9\t", "mode": "replace"})
        self.assertEqual(resp.status, 200)
        self.assertEqual(body["count"], 2)
        resp, body = self.req("POST", "/api/admin/import", {"text": "王五\t1", "mode": "append"})
        self.assertEqual(body["count"], 1)
        resp, body = self.req("GET", "/api/admin/guests")
        self.assertEqual([g["name"] for g in body["guests"]], ["张三", "李四", "王五"])
        self.assertEqual(body["guests"][0]["private_note"], "素食")
        resp, body = self.req("POST", "/api/admin/import", {"text": "王五\t1", "mode": "bogus"})
        self.assertEqual(resp.status, 400)

    def test_export_csv_headers(self):
        self.login()
        self.add("张三", "8", "", "素食")
        resp, payload = self.req("GET", "/api/admin/export", raw=True)
        self.assertEqual(resp.status, 200)
        self.assertIn("text/csv", resp.getheader("Content-Type"))
        self.assertIn("attachment", resp.getheader("Content-Disposition"))
        self.assertTrue(payload.startswith(b"\xef\xbb\xbf"))
        self.assertIn("素食", payload.decode("utf-8-sig"))

    def test_settings_update(self):
        self.login()
        resp, _ = self.req("PUT", "/api/admin/settings", {"title": "A & B", "date_text": "11.22", "welcome": "欢迎"})
        self.assertEqual(resp.status, 200)
        resp, body = self.req("GET", "/api/settings")
        self.assertEqual(body["title"], "A & B")
        resp, _ = self.req("PUT", "/api/admin/settings", {"floorplan": "../../etc/passwd"})
        self.assertEqual(resp.status, 400)

    def test_floorplan_upload_type_and_size(self):
        self.login()
        resp, _ = self.req("POST", "/api/admin/floorplan", b"hello", headers={"Content-Type": "text/plain"})
        self.assertEqual(resp.status, 400)
        big = b"0" * (5 * 1024 * 1024 + 1)
        resp, _ = self.req("POST", "/api/admin/floorplan", big, headers={"Content-Type": "image/png"})
        self.assertEqual(resp.status, 413)
        resp, _ = self.req("POST", "/api/admin/floorplan", PNG, headers={"Content-Type": "image/png"})
        self.assertEqual(resp.status, 200)
        self.cookie = None
        resp, payload = self.req("GET", "/floorplan", raw=True)
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader("Content-Type"), "image/png")
        self.assertEqual(payload, PNG)
        resp, body = self.req("GET", "/api/settings")
        self.assertTrue(body["has_floorplan"])
        self.login()
        resp, _ = self.req("POST", "/api/admin/floorplan", b"jpgdata", headers={"Content-Type": "image/jpeg"})
        self.assertEqual(resp.status, 200)
        resp, _ = self.req("DELETE", "/api/admin/floorplan")
        self.assertEqual(resp.status, 200)
        resp, _ = self.req("GET", "/floorplan", raw=True)
        self.assertEqual(resp.status, 404)


class RedirectTest(ServerCase):
    redirect_to = "https://x.example/"

    def test_redirect_mode(self):
        resp, _ = self.req("GET", "/api/search?q=a", raw=True)
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.getheader("Location"), "https://x.example/api/search?q=a")
        resp, _ = self.req("POST", "/api/admin/login", {"password": "pw"}, raw=True)
        self.assertEqual(resp.status, 302)


class RateLimitTest(ServerCase):
    rate_limiter = staticmethod(lambda: RateLimiter(limit=3, window=60))

    def test_rate_limit_429(self):
        codes = [self.req("GET", "/api/search?q=%E5%BC%A0")[0].status for _ in range(4)]
        self.assertEqual(codes[:3], [200, 200, 200])
        self.assertEqual(codes[3], 429)
        resp, _ = self.req("GET", "/api/seat/1")
        self.assertEqual(resp.status, 429)


if __name__ == "__main__":
    unittest.main()
