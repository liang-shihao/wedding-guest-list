# 婚礼座位查询 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 微信扫码 → 输入姓名 → 显示桌号的网页，附带密码保护的后台管理。

**Architecture:** 单进程 Python 标准库 HTTP 服务（`ThreadingHTTPServer`），SQLite 存名单与设置，JSON API + 两个原生 HTML 页面。逻辑按职责拆成 `seat/` 包内小模块，`app.py` 只负责读环境变量并启动。

**Tech Stack:** Python 3.14 标准库（http.server, sqlite3, hmac, json, csv, unittest），原生 HTML/CSS/JS。本地用 `py -3.14` 跑测试。

**Spec:** `docs/superpowers/specs/2026-11-16-wedding-seat-lookup-design.md`

## Global Constraints

- 零第三方依赖；前端零外部资源（无 CDN、无外部字体）。
- 默认端口 `8001`，`HOST` 默认 `0.0.0.0`，`DATA_DIR` 默认 `./data`；`ADMIN_PASSWORD` 未设置则拒绝启动。
- 公开接口永不返回 `private_note`。
- 公开接口（search / seat）每 IP 每分钟 300 次，超出 429。
- 登录：同 IP 10 分钟内失败 5 次锁 10 分钟；cookie 7 天有效，`HttpOnly; SameSite=Strict`。
- 请求体上限 6MB；平面图 ≤ 5MB，类型 `image/png|image/jpeg|image/webp`。
- 备份保留最近 50 份，路径 `data/backups/guests-YYYYmmdd-HHMMSS.csv`。
- 前端插入用户数据只用 `textContent`。
- 所有响应带 `X-Content-Type-Options: nosniff`；`/api/admin/*` 带 `Cache-Control: no-store`。

## Review Focus

- 姓名带首尾/中间空格、全角空格、全角字母（如「Ｔｏｍ」）→ 应与存储的名字匹配。（Task 1 测试）
- 从 Excel 粘贴的文本带 `\r\n`、尾部空行、单元格内含逗号的 CSV 引号 → 正确解析，不产生空记录。（Task 3 测试）
- 同名但公开说明为空 → 后台能标出来。（Task 2 `duplicate_names_missing_note` 测试）
- 查询 `q` 只有 1 个字且无精确匹配 → 返回空列表，不做模糊。（Task 2 测试）
- 反向代理/直连下取客户端 IP：直连用 socket 地址；仅当 `TRUST_PROXY=1` 时取 `X-Forwarded-For` 首项，否则伪造的 XFF 可绕过限流。（Task 4 测试）

---

### Task 1: 姓名规范化与桌号显示

**Files:**
- Create: `seat/__init__.py`（空）, `seat/text.py`
- Test: `tests/test_text.py`

**Interfaces:**
- Produces: `normalize_name(s: str) -> str`；`format_table(t: str) -> str`

- [ ] **Step 1: 写失败测试**

```python
def test_normalize(self):
    self.assertEqual(normalize_name("  张 三 "), "张三")
    self.assertEqual(normalize_name("张　三"), "张三")
    self.assertEqual(normalize_name("Ｔｏｍ Lee"), "tomlee")
    self.assertEqual(normalize_name("   "), "")
def test_format_table(self):
    self.assertEqual(format_table("8"), "第 8 桌")
    self.assertEqual(format_table(" 12 "), "第 12 桌")
    self.assertEqual(format_table("主桌"), "主桌")
    self.assertEqual(format_table("A3"), "A3")
```

- [ ] **Step 2:** `py -3.14 -m unittest tests.test_text -v` → FAIL（ImportError）
- [ ] **Step 3:** 实现：`unicodedata.normalize("NFKC", s)` 后删除所有 `str.isspace()` 字符，再 `.lower()`。
- [ ] **Step 4:** 同命令 → PASS
- [ ] **Step 5:** commit `feat: name normalization`

### Task 2: 存储层（SQLite）与查询

**Files:**
- Create: `seat/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `normalize_name`
- Produces: `class Store(data_dir: str)`，方法：
  - `search(q: str) -> dict` → `{"mode": "exact"|"fuzzy"|"none", "results": [...]}`；exact 项 `{id,name,table,public_note}`，fuzzy 项 `{id,name,public_note}`（≤5）。`q` 规范化为空时 `raise ValueError`。
  - `seat(guest_id: int) -> dict | None` → `{name,table,public_note}`
  - `list_guests() -> list[dict]`（全字段 `id,name,table,public_note,private_note`，按 id）
  - `add_guest(name, table, public_note="", private_note="") -> int`；`update_guest(id, **fields) -> bool`；`delete_guest(id) -> bool`（删除前 `backup()`）。姓名/桌号去空白后为空 `raise ValueError`。
  - `replace_all(rows: list[dict])`（先 `backup()`，事务内清空再插入）；`append(rows)`
  - `backup() -> str`（写 CSV，保留最近 50 份）；`export_csv() -> bytes`（UTF-8 BOM，表头 `姓名,桌号,公开说明,内部备注`）
  - `get_settings() -> dict`（`title,date_text,welcome,floorplan`，缺省为空串）；`set_settings(**kv)`
  - `duplicate_names_missing_note() -> set[int]`（同 `name_key` 出现 ≥2 次且 `public_note` 为空的 id）
- 每次操作新开连接（`check_same_thread` 问题不存在），写操作用 `with conn:` 事务；`PRAGMA journal_mode=WAL`。

- [ ] **Step 1: 写失败测试**（`tempfile.TemporaryDirectory` 作 data_dir）

```python
# 准备: 张三(8,"新郎同学","素食"), 张三(9,"新娘同事",""), 张三丰(3), 李四(主桌)
test_exact_returns_all_same_name: search("张 三") mode=="exact", len==2, 每项无 "private_note" 键
test_fuzzy_hides_table: search("三丰")... 注意"三丰"精确不中 → fuzzy，结果项 keys == {"id","name","public_note"}
test_fuzzy_needs_two_chars: search("丰")["mode"] == "none"
test_fuzzy_limit_5: 插入 7 个"王小X" → search("王小") 返回 5 条
test_empty_query_raises: assertRaises(ValueError, search, "  ")
test_seat: seat(id) == {"name":"李四","table":"主桌","public_note":""}; seat(9999) is None
test_add_requires_name_and_table: assertRaises(ValueError) for name="" / table=" "
test_replace_all_backs_up: replace_all([...]) 后 data/backups 下 1 个文件，旧名单在里面
test_backup_keeps_50: 调 backup() 55 次（文件名冲突时加序号后缀）→ 50 个文件
test_export_bom: export_csv().startswith(b"\xef\xbb\xbf")，含 "内部备注"
test_duplicates_missing_note: 加一个 王五 ×2 都无公开说明 → 两个 id 都在集合中；张三 不在
test_settings_roundtrip
```

- [ ] **Step 2:** `py -3.14 -m unittest tests.test_store -v` → FAIL
- [ ] **Step 3:** 实现 `seat/store.py`。fuzzy 用 `name_key LIKE ? ESCAPE '\'`（对 `%_\` 转义），`ORDER BY id LIMIT 5`。
- [ ] **Step 4:** → PASS
- [ ] **Step 5:** commit `feat: sqlite store and search`

### Task 3: 导入解析

**Files:**
- Create: `seat/importer.py`
- Test: `tests/test_importer.py`

**Interfaces:**
- Produces: `parse_import(text: str) -> tuple[list[dict], list[str]]` → (rows, errors)。row 键 `name,table,public_note,private_note`。errors 形如 `"第 3 行：姓名为空"`（行号按粘贴文本的物理行，从 1 开始）。

- [ ] **Step 1: 写失败测试**

```python
test_tab_with_header: "姓名\t桌号\t备注\r\n张三\t8\t素食\r\n" → [{"name":"张三","table":"8","public_note":"","private_note":"素食"}]
test_header_mapping: "姓名,桌号,公开说明,内部备注\n张三,8,新郎同学,素食" → public_note "新郎同学", private_note "素食"
test_header_aliases: 表头 "说明" → public_note
test_no_header_order: "张三\t8\t素食\t新郎同学" → private_note "素食", public_note "新郎同学"
test_csv_quoted_comma: '张三,8,"素食,不吃辣"' → private_note "素食,不吃辣"
test_blank_lines_skipped: 中间/尾部空行不产生记录、不报错
test_errors_with_line_numbers: "姓名\t桌号\n\t8\n李四\t\n" → rows==[], errors==["第 2 行：姓名为空","第 3 行：桌号为空"]
test_values_trimmed: " 张三 \t 8 " → name "张三", table "8"
```

- [ ] **Step 2:** → FAIL
- [ ] **Step 3:** 实现：分隔符判定——文本含 `\t` 用 `\t`，否则 `,`；用 `csv.reader(io.StringIO(text), delimiter=...)`。表头判定：首个非空行任一单元格去空白后等于 `姓名`。有错误时 rows 返回 `[]`。
- [ ] **Step 4:** → PASS
- [ ] **Step 5:** commit `feat: paste import parser`

### Task 4: 鉴权与限流

**Files:**
- Create: `seat/security.py`
- Test: `tests/test_security.py`

**Interfaces:**
- Produces:
  - `make_token(password: str, now: float) -> str`；`check_token(password: str, token: str, now: float) -> bool`（格式 `"{expiry}.{hexsig}"`，key = `sha256(b"wedding-seat:" + password)`，有效期 `7*86400`）
  - `class LoginGuard(max_fail=5, window=600, lock=600)`：`is_locked(ip, now) -> bool`，`fail(ip, now)`，`success(ip)`
  - `class RateLimiter(limit=300, window=60)`：`allow(ip, now) -> bool`（固定窗口计数，线程锁保护）
  - `client_ip(socket_ip: str, headers, trust_proxy: bool) -> str`

- [ ] **Step 1: 写失败测试**

```python
test_token_roundtrip: check_token("pw", make_token("pw", 1000), 1001) is True
test_token_expired: check_token("pw", make_token("pw", 0), 7*86400 + 1) is False
test_token_wrong_password: check_token("other", make_token("pw", 0), 1) is False
test_token_garbage: check_token("pw", "abc", 1) is False; check_token("pw", "", 1) is False
test_guard_locks_after_5: 5 次 fail(t=0..4) → is_locked(ip, 5) True；is_locked(ip, 5+600+1) False
test_guard_success_resets: 4 次 fail 后 success → 再 fail 1 次不锁
test_guard_window: fail 间隔 > 600 秒不累计
test_rate_limit: 300 次 allow True，第 301 次 False；61 秒后 True；不同 ip 互不影响
test_client_ip: trust_proxy False 时忽略 X-Forwarded-For；True 时取 "1.2.3.4, 5.6.7.8" 的 "1.2.3.4"
```

- [ ] **Step 2:** → FAIL
- [ ] **Step 3:** 实现，比较用 `hmac.compare_digest`。
- [ ] **Step 4:** → PASS
- [ ] **Step 5:** commit `feat: auth token, login guard, rate limiter`

### Task 5: HTTP 服务与路由

**Files:**
- Create: `seat/server.py`, `app.py`, `static/index.html`, `static/admin.html`（此任务先放最小占位 HTML，Task 6/7 完善）, `.gitignore`（`data/`, `__pycache__/`）
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: Task 1–4 全部
- Produces: `make_server(host: str, port: int, data_dir: str, password: str, redirect_to: str = "", trust_proxy: bool = False) -> ThreadingHTTPServer`；`app.py` 的 `main()` 读 `ADMIN_PASSWORD, PORT, HOST, DATA_DIR, REDIRECT_TO, TRUST_PROXY`，缺密码 `sys.exit("ADMIN_PASSWORD is required")`。
- 路由（JSON 响应 `application/json; charset=utf-8`，错误体 `{"error": "中文提示"}`）：
  - `GET /` → static/index.html；`GET /admin` → static/admin.html；其他路径不服务文件（白名单仅这两个）
  - `GET /api/settings` → `{title,date_text,welcome,has_floorplan}`
  - `GET /api/search?q=` → Store.search；空 → 400；限流 429
  - `GET /api/seat/<id>` → 200 / 404；限流 429
  - `GET /floorplan` → 图片或 404
  - `POST /api/admin/login {password}` → 200 + `Set-Cookie: admin=<token>; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800`；错 401；锁定 429
  - `POST /api/admin/logout` → 清 cookie
  - 以下需 cookie，否则 401：`GET /api/admin/me`，`GET/POST /api/admin/guests`（GET 每项附 `dup_missing_note: bool`），`PUT/DELETE /api/admin/guests/<id>`，`POST /api/admin/import {text, mode}`（errors 非空 → 400 `{"error":..., "errors":[...]}`；成功 `{"count": n}`），`GET /api/admin/export`（`Content-Disposition: attachment; filename="guests.csv"`），`PUT /api/admin/settings`，`POST/DELETE /api/admin/floorplan`
  - `REDIRECT_TO` 非空 → 任何请求 302 到 `REDIRECT_TO.rstrip("/") + self.path`
  - `Content-Length` > 6MB → 413；ValueError → 400
- 平面图存 `data/floorplan.{png|jpg|webp}`，settings.floorplan 记文件名；上传新图删除旧图。

- [ ] **Step 1: 写失败测试**（`setUp` 在随机端口 `make_server("127.0.0.1", 0, tmp, "pw")` 起线程，`urllib.request` 调用）

```python
test_index_served / test_static_traversal: GET "/static/../app.py" 与 "/../app.py" → 404
test_search_public_has_no_private_note: 加入带内部备注的宾客后，search 与 seat 的响应文本不含 "素食"
test_search_empty_400
test_admin_requires_login: GET /api/admin/guests → 401
test_login_and_crud: 登录拿 cookie → POST 新增 → PUT 改桌号 → GET 列表反映 → DELETE
test_login_wrong_401_then_locked_429: 5 次错 → 第 6 次（即使正确密码）429
test_import_replace_and_errors: 有错误行 → 400 且名单不变；正确 → count 正确
test_export_csv_headers
test_floorplan_upload_type_and_size: text/plain → 400；6MB 以内但 >5MB → 413；png → 200，GET /floorplan 返回同样字节，/api/settings has_floorplan True
test_redirect_mode: redirect_to="https://x.example" → GET /api/search?q=a 302，Location "https://x.example/api/search?q=a"
test_nosniff_and_no_store_headers
test_rate_limit_429: 用 limit 小的 RateLimiter 注入（make_server 接受可选 `rate_limiter` 参数）
```

- [ ] **Step 2:** → FAIL
- [ ] **Step 3:** 实现 `seat/server.py`（`BaseHTTPRequestHandler` 子类，handler 通过 `self.server.ctx` 取 store/guard/limiter/password）与 `app.py`。
- [ ] **Step 4:** `py -3.14 -m unittest discover -s tests -v` → 全部 PASS
- [ ] **Step 5:** commit `feat: http server and routes`

### Task 6: 宾客查询页 `static/index.html`

**Files:** Modify `static/index.html`

- 启动时 `GET /api/settings` 填标题/日期/欢迎语，`has_floorplan` 时在结果下方显示 `<img src="/floorplan">`（点击可全屏查看）。
- 输入框 + 查询按钮，回车提交；按 spec 的 exact/fuzzy/none 三种展示；查无结果文案用 spec 原文：「没有找到，请检查姓名；随行家属请输入邀请人的姓名，或咨询现场工作人员」；429 显示「查询太频繁，请稍后再试」。
- 桌号大字醒目（显示用的格式与 `format_table` 一致：纯数字 → `第 N 桌`，在 JS 里同规则实现）。
- 移动端优先，喜庆但克制的配色，无外部资源。
- [ ] 验证：本地 `ADMIN_PASSWORD=pw py -3.14 app.py`，浏览器窄屏打开 `http://127.0.0.1:8001/`，导入样例后查 exact / 同名 / fuzzy / 无结果四种情况。
- [ ] commit `feat: guest lookup page`

### Task 7: 后台页 `static/admin.html`

**Files:** Modify `static/admin.html`

- 未登录（`/api/admin/me` 401）显示密码框；登录后显示四块：宾客列表、批量导入、页面设置、平面图。
- 宾客列表：顶部搜索框本地过滤；每行可编辑姓名/桌号/公开说明/内部备注，保存与删除（删除需 confirm）；`dup_missing_note` 行高亮并提示「有同名，请填写公开说明」；底部新增一行；显示总人数；导出按钮。
- 批量导入：textarea 粘贴 → 前端预览（简单按同样规则拆列显示前 20 行）→ 选「覆盖 / 追加」→ 覆盖需 confirm「将替换全部 N 人名单（会自动备份）」→ 提交；400 时列出 errors。
- 页面设置：title / date_text / welcome 三个输入框 + 保存。
- 平面图：文件选择 → `fetch` 以 `file` 为 body、`Content-Type: file.type` 上传；显示当前图与删除按钮。
- 退出登录按钮。手机上可用。
- [ ] 验证：本地走一遍登录、导入（含错误行）、编辑、同名高亮、导出、上传平面图、退出。
- [ ] commit `feat: admin page`

### Task 8: 部署文件与说明，上线北京 ECS

**Files:** Create `deploy/wedding-seat.service`, `deploy/Caddyfile.example`, Modify `README.md`

- service：`WorkingDirectory=/opt/wedding-seat`，`ExecStart=/usr/bin/python3 /opt/wedding-seat/app.py`，`User=ecs-user`，`EnvironmentFile=/etc/wedding-seat.env`，`Restart=always`，`Environment=PYTHONUNBUFFERED=1`。
- Caddyfile：`example.com { reverse_proxy 127.0.0.1:8001 }`，配合 `HOST=127.0.0.1`、`TRUST_PROXY=1`。
- README：功能简介、本地运行、部署步骤、改密码、备份位置、迁移香港与 `REDIRECT_TO` 切换、二维码生成提示。
- [ ] 部署到 `/opt/wedding-seat`，`systemctl enable --now wedding-seat`；`curl -s http://127.0.0.1:8001/api/settings` 返回 JSON；`ss -ltnp` 确认 8000 服务仍在。
- [ ] 用户在安全组放行 8001，微信实测。
- [ ] commit `chore: deploy files and readme`
