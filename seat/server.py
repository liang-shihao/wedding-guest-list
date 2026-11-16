"""HTTP layer: routing, JSON API, static pages."""
import hmac
import json
import logging
import os
import re
import time
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .importer import parse_import
from .security import LoginGuard, RateLimiter, check_token, client_ip, make_token
from .store import Store

log = logging.getLogger("seat")

MAX_BODY = 6 * 1024 * 1024
# Uploadable images: slot name -> max bytes. Stored as data/<slot>.<ext>, settings key <slot>.
IMAGE_SLOTS = {"floorplan": 5 * 1024 * 1024, "background": 1 * 1024 * 1024}
LOGIN_MAX_BODY = 4096
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
EXT_TYPES = {ext: ctype for ctype, ext in IMAGE_TYPES.items()}
COOKIE = "admin"
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
PAGES = {"/": "index.html", "/admin": "admin.html", "/admin/": "admin.html"}
PUBLIC_SETTINGS = ("title", "date_text", "welcome")


class HttpError(Exception):
    def __init__(self, status, message, extra=None):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra or {}


class Context:
    def __init__(self, data_dir, password, redirect_to, trust_proxy, rate_limiter):
        self.data_dir = data_dir
        self.store = None if redirect_to else Store(data_dir)
        self.password = password
        self.redirect_to = redirect_to.rstrip("/") if redirect_to else ""
        self.trust_proxy = trust_proxy
        self.guard = LoginGuard()
        self.limiter = rate_limiter or RateLimiter()


class Handler(BaseHTTPRequestHandler):
    server_version = "seat"
    sys_version = ""
    timeout = 20  # seconds; stops idle/slow clients pinning threads

    # ---- plumbing --------------------------------------------------------
    @property
    def ctx(self) -> Context:
        return self.server.ctx

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _send(self, status, body=b"", ctype="application/json; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.path.startswith("/api/admin/"):
            self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, status=200, headers=None):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), headers=headers)

    def _ip(self):
        return client_ip(self.client_address[0], self.headers, self.ctx.trust_proxy)

    def _raw_body(self, limit=MAX_BODY) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise HttpError(400, "请求格式错误")
        if length > limit:
            self.close_connection = True
            raise HttpError(413, "内容太大")
        return self.rfile.read(length) if length > 0 else b""

    def _json_body(self, limit=MAX_BODY) -> dict:
        raw = self._raw_body(limit)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise HttpError(400, "请求格式错误")
        if not isinstance(data, dict):
            raise HttpError(400, "请求格式错误")
        return data

    def _authed(self) -> bool:
        try:
            cookie = SimpleCookie(self.headers.get("Cookie") or "")
        except CookieError:
            return False
        morsel = cookie.get(COOKIE)
        return bool(morsel) and check_token(self.ctx.password, morsel.value, time.time())

    def _dispatch(self, method):
        if self.ctx.redirect_to:
            self._send(302, b"", "text/plain", {"Location": self.ctx.redirect_to + self.path})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        try:
            if length > MAX_BODY:
                self.close_connection = True
                raise HttpError(413, "内容太大")
            self._route(method)
        except HttpError as e:
            self._json({"error": e.message, **e.extra}, e.status)
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except Exception:  # noqa: BLE001 - last-resort guard, logged
            log.exception("unhandled error on %s %s", method, self.path)
            self._json({"error": "服务器出错了，请稍后再试"}, 500)

    # ---- routing ---------------------------------------------------------
    def _route(self, method):
        url = urlsplit(self.path)
        path = url.path

        if method == "GET" and path in PAGES:
            return self._page(PAGES[path])
        if path == "/api/search" or path.startswith("/api/seat/"):
            if not self.ctx.limiter.allow(self._ip(), time.time()):
                raise HttpError(429, "查询太频繁，请稍后再试")
            if method == "GET" and path == "/api/search":
                q = parse_qs(url.query).get("q", [""])[0]
                return self._json(self.ctx.store.search(q))
            m = re.fullmatch(r"/api/seat/(\d+)", path)
            if method == "GET" and m:
                q = parse_qs(url.query).get("q", [""])[0]
                seat = self.ctx.store.seat(int(m.group(1)), q)
                if seat is None:
                    raise HttpError(404, "没有找到")
                return self._json(seat)
            raise HttpError(404, "没有找到")
        if method == "GET" and path == "/api/settings":
            s = self.ctx.store.get_settings()
            out = {k: s[k] for k in PUBLIC_SETTINGS}
            for slot in IMAGE_SLOTS:
                fp = self._image_path(slot, s)
                out[f"has_{slot}"] = fp is not None
                out[f"{slot}_version"] = str(os.stat(fp[0]).st_mtime_ns) if fp else ""
            return self._json(out)
        if method == "GET" and path.lstrip("/") in IMAGE_SLOTS:
            return self._image(path.lstrip("/"))
        if path.startswith("/api/admin/"):
            return self._admin(method, path[len("/api/admin/"):])
        raise HttpError(404, "没有找到")

    def _page(self, name):
        with open(os.path.join(STATIC_DIR, name), "rb") as f:
            body = f.read()
        self._send(200, body, "text/html; charset=utf-8", {"Cache-Control": "no-cache"})

    def _image_path(self, slot, settings=None):
        name = (settings or self.ctx.store.get_settings())[slot]
        ext = name.rsplit(".", 1)[-1] if name.startswith(slot + ".") else ""
        if ext not in EXT_TYPES:
            return None
        p = os.path.join(self.ctx.data_dir, f"{slot}.{ext}")
        return (p, EXT_TYPES[ext]) if os.path.isfile(p) else None

    def _image(self, slot):
        fp = self._image_path(slot)
        if fp is None:
            raise HttpError(404, "没有图片")
        with open(fp[0], "rb") as f:
            body = f.read()
        # URL carries ?v=<mtime>, so a new upload gets a new URL; let phones cache it.
        self._send(200, body, fp[1], {"Cache-Control": "public, max-age=86400"})

    # ---- admin -----------------------------------------------------------
    def _admin(self, method, sub):
        if sub == "login" and method == "POST":
            return self._login()
        if not self._authed():
            raise HttpError(401, "请先登录")
        store = self.ctx.store
        if sub == "logout" and method == "POST":
            return self._json({"ok": True}, headers={
                "Set-Cookie": f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
        if sub == "me" and method == "GET":
            return self._json({"ok": True})
        if sub == "guests" and method == "GET":
            dups = store.duplicate_names_missing_note()
            guests = [dict(g, dup_missing_note=g["id"] in dups) for g in store.list_guests()]
            return self._json({"guests": guests})
        if sub == "guests" and method == "POST":
            b = self._json_body()
            gid = store.add_guest(b.get("name", ""), b.get("table", ""),
                                  b.get("public_note", ""), b.get("private_note", ""))
            return self._json({"id": gid})
        m = re.fullmatch(r"guests/(\d+)", sub)
        if m and method == "PUT":
            if not store.update_guest(int(m.group(1)), **self._json_body()):
                raise HttpError(404, "没有这位宾客")
            return self._json({"ok": True})
        if m and method == "DELETE":
            if not store.delete_guest(int(m.group(1))):
                raise HttpError(404, "没有这位宾客")
            return self._json({"ok": True})
        if sub == "import" and method == "POST":
            b = self._json_body()
            mode = b.get("mode")
            if mode not in ("replace", "append"):
                raise HttpError(400, "导入方式不正确")
            rows, errors = parse_import(str(b.get("text") or ""))
            if errors:
                raise HttpError(400, "导入失败，请修正后重试", {"errors": errors})
            count = store.replace_all(rows) if mode == "replace" else store.append(rows)
            return self._json({"count": count})
        if sub == "export" and method == "GET":
            return self._send(200, store.export_csv(), "text/csv; charset=utf-8",
                              {"Content-Disposition": 'attachment; filename="guests.csv"'})
        if sub == "settings" and method == "PUT":
            b = self._json_body()
            if set(b) - set(PUBLIC_SETTINGS):
                raise HttpError(400, "未知设置")
            store.set_settings(**{k: str(b[k] if b[k] is not None else "") for k in b})
            return self._json({"ok": True})
        if sub in IMAGE_SLOTS and method == "POST":
            return self._upload_image(sub)
        if sub in IMAGE_SLOTS and method == "DELETE":
            self._remove_images(sub)
            store.set_settings(**{sub: ""})
            return self._json({"ok": True})
        raise HttpError(404, "没有找到")

    def _login(self):
        ip = self._ip()
        now = time.time()
        if self.ctx.guard.is_locked(ip, now):
            raise HttpError(429, "密码错误次数太多，请 10 分钟后再试")
        given = str(self._json_body(LOGIN_MAX_BODY).get("password") or "")
        if not hmac.compare_digest(given.encode("utf-8"), self.ctx.password.encode("utf-8")):
            self.ctx.guard.fail(ip, now)
            raise HttpError(401, "密码错误")
        self.ctx.guard.success(ip)
        token = make_token(self.ctx.password, now)
        self._json({"ok": True}, headers={
            "Set-Cookie": f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800"})

    def _remove_images(self, slot):
        for ext in EXT_TYPES:
            p = os.path.join(self.ctx.data_dir, f"{slot}.{ext}")
            if os.path.exists(p):
                os.remove(p)

    def _upload_image(self, slot):
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype not in IMAGE_TYPES:
            raise HttpError(400, "只支持 PNG / JPG / WEBP 图片")
        body = self._raw_body()
        limit = IMAGE_SLOTS[slot]
        if len(body) > limit:
            raise HttpError(413, f"图片不能超过 {limit // (1024 * 1024)}MB，请先压缩")
        if not body:
            raise HttpError(400, "图片为空")
        ext = IMAGE_TYPES[ctype]
        self._remove_images(slot)
        path = os.path.join(self.ctx.data_dir, f"{slot}.{ext}")
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, path)
        self.ctx.store.set_settings(**{slot: f"{slot}.{ext}"})
        return self._json({"ok": True})


class _Server(ThreadingHTTPServer):
    daemon_threads = True


def make_server(host, port, data_dir, password, redirect_to="", trust_proxy=False, rate_limiter=None):
    if not password:
        raise ValueError("password is required")
    httpd = _Server((host, port), Handler)
    httpd.ctx = Context(data_dir, password, redirect_to, trust_proxy, rate_limiter)
    return httpd
