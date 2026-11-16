# 婚礼座位查询 — 设计文档

日期：2026-11-16　婚礼：约 6 天后（2026-11-22 前后）

## 意图

婚礼现场，宾客用微信扫迎宾牌/桌牌上的二维码，打开网页，输入自己的姓名，立即看到桌号。新人（或帮忙的人）能在手机上通过后台随时调整座位，不必登录服务器。

宾客群体没有特别的年龄倾向，正常的移动端可用性即可。

## 目标

- 微信扫码可打开，输入姓名一步出桌号。
- 名单只存在服务器端，前端不暴露完整名单。
- 后台可增删改宾客（含公开说明 / 内部备注）、从 Excel 粘贴批量导入、导出 CSV、修改页面文案、上传平面图。
- 6 天内稳定可用，婚礼当天几百人并发查询无压力。
- 能在 10 分钟内整体搬迁到另一台服务器。

## 非目标

- 不做微信小程序、不做微信登录/授权。
- 不做多账号、权限分级、操作日志、统计报表。
- 不做平面图上的桌位高亮（只展示整张平面图）。
- 不做 RSVP / 签到。

## 反目标（技术上能跑但算失败）

- 宾客打开慢、要加载境外 CDN 资源（国内微信里会卡或白屏）——**禁止任何外部 CDN / 字体**，所有资源同源。
- 能通过前端源码或公开接口拿到完整宾客名单。
- 婚礼当天因一次误操作把名单清空且无法恢复。

## 约束

- 现有服务器：阿里云华北2（北京）ECS，Ubuntu 26.04，Python 3.14，公网 IP `39.106.139.161`，2C2G。
- 无已备案域名 → 国内机房只能用 `http://IP:端口` 访问；已实测微信会弹「非微信官方网页」提示，点「继续访问」可打开。
- 8000 端口已被另一个 uvicorn 服务占用，**不得影响它**。本服务使用 **8001**，需在安全组入方向放行 TCP 8001。
- 同时并行准备：阿里云香港轻量服务器 + 新域名（免备案），实名认证通过后迁移过去并实测微信是否还弹提示。
- 无 HTTPS 期间后台密码明文传输，已告知用户，接受；迁移到域名后用 Caddy 自动配 HTTPS。

## 方案对比（已选 A+B）

| 方案 | 优点 | 代价 |
|---|---|---|
| A. 现有北京 ECS，IP:8001 | 今天可上线，完全自定义，名单在服务端 | 每位宾客先看到微信风险提示 |
| B. 香港轻量服务器 + 新域名 | 免备案，正常域名，大概率无提示，可上 HTTPS | 少量费用，域名实名需几小时~1 天 |
| C. 腾讯文档/金山表单凭姓名查询 | 零代码、无提示 | 界面不可定制 |

**选择**：A 先做并作为保底；B 并行准备，同一套代码迁移，实测无提示则用 B 的地址出二维码。C 仅作最后备胎，不预先做。

## 设计

### 技术选型（我方决定）

- **纯 Python 标准库**：`http.server.ThreadingHTTPServer` + `sqlite3` + `json` + `hmac` + `secrets`。零依赖，便于迁移。
- 前端：原生 HTML/CSS/JS，两个页面，无构建步骤，无外部资源。

### 目录结构

```
app.py               # 服务端：路由、API、鉴权、数据库
static/index.html    # 宾客查询页
static/admin.html    # 后台管理页
tests/               # unittest
deploy/wedding-seat.service   # systemd 单元
deploy/Caddyfile.example      # 迁移到域名后的 HTTPS 反代示例
data/                # 运行时生成，git 忽略：guests.db、floorplan.*
```

### 配置（环境变量）

- `ADMIN_PASSWORD`（必填，未设置则拒绝启动）
- `PORT`（默认 8001）、`HOST`（默认 0.0.0.0）、`DATA_DIR`（默认 `./data`）

### 数据模型（SQLite）

- `guests(id INTEGER PK, name TEXT NOT NULL, name_key TEXT NOT NULL, table_no TEXT NOT NULL, public_note TEXT NOT NULL DEFAULT '', private_note TEXT NOT NULL DEFAULT '')`，`name_key` 建索引。
  - `public_note`「公开说明」：宾客可见，用于区分同名（如「新郎大学同学」）。
  - `private_note`「内部备注」：仅后台可见（如「素食」）。**任何公开接口都不得返回它。**
- 名单一人一行。随行家属通常不在名单里，靠输入邀请人姓名查询（见查询页提示）。
- `settings(key TEXT PK, value TEXT)`：`title`（如「XX & XX 的婚礼」）、`date_text`、`welcome`、`floorplan`（文件名或空）。
- 桌号为文本（支持「8」「主桌」「A3」）。展示时纯数字显示为「第 8 桌」，否则原样显示。

### 姓名规范化 `name_key`

去掉所有空白（含全角空格、中间空格），拉丁字母转小写，全角字母数字转半角。查询与存储使用同一函数。

### 查询规则（公开接口）

`GET /api/search?q=...`

1. 规范化后为空 → 400。
2. 精确匹配 `name_key` → 返回全部同名记录 `[{id, name, table, public_note}]`，`mode: "exact"`。
3. 无精确结果且规范化后长度 ≥ 2 → 返回 `name_key` 包含该输入的记录，最多 5 条，**只含 `[{id, name, public_note}]`，不含桌号**，`mode: "fuzzy"`。
4. 否则返回空列表。

`GET /api/seat/{id}?q=<原查询>` → `{name, table, public_note}`，供点选模糊候选后取桌号。`q` 规范化后须 ≥ 2 字且被该宾客姓名包含，否则 404（防止按 id 枚举出整份名单）。

前端：精确匹配 1 条直接大字显示桌号；多条（同名）逐条显示「姓名 · 公开说明 · 桌号」；模糊结果列出「姓名 · 公开说明」候选，点选后请求桌号。查无结果提示「没有找到，请检查姓名；随行家属请输入邀请人的姓名，或咨询现场工作人员」。

限流：公开接口（search / seat）每 IP 每分钟 300 次，超出返回 429。阈值宽松，因为现场大量宾客共用 WiFi/运营商 NAT 出口 IP；目的只是挡住脚本批量枚举。

`GET /api/settings` 公开返回 `title / date_text / welcome / has_floorplan`。`GET /floorplan` 返回平面图图片。

### 后台

`/admin` 页面；接口均在 `/api/admin/*`，除 login 外都需鉴权。

- **登录**：`POST /api/admin/login {password}`，用 `hmac.compare_digest` 比较。成功后下发 `HttpOnly; SameSite=Strict` cookie，内容为 `过期时间.HMAC(签名)`，签名密钥由 `ADMIN_PASSWORD` 派生 → 服务重启后仍有效，改密码后全部失效。有效期 7 天。`POST /api/admin/logout` 清除。
- **防爆破**：同一 IP 10 分钟内失败 5 次 → 锁 10 分钟（内存记录）。
- **同名提醒**：后台列表高亮「存在同名但公开说明为空」的记录，提示补填，否则宾客无法区分。
- **宾客 CRUD**：`GET /api/admin/guests`（全量，前端本地搜索过滤）、`POST`（新增）、`PUT /api/admin/guests/{id}`、`DELETE /api/admin/guests/{id}`。姓名、桌号必填。
- **批量导入**：`POST /api/admin/import {text, mode: "replace"|"append"}`。`text` 是从 Excel 复制粘贴的内容（制表符分隔），也兼容逗号分隔。若首行含「姓名」视为表头，并按表头名映射列：`姓名`、`桌号`、`公开说明`/`说明`、`内部备注`/`备注`（**单独的「备注」默认归为内部备注**，宁可不公开）。无表头时按列序：姓名、桌号、内部备注、公开说明。姓名或桌号为空的行报错并指出行号，**有任何错误则整体不导入**。前端先在本地解析并预览，再提交。
- **防误删**：`replace` 导入和单条删除前，服务端自动把当前名单备份到 `data/backups/guests-YYYYmmdd-HHMMSS.csv`（保留最近 50 份）。前端 replace 需二次确认。
- **导出**：`GET /api/admin/export` 返回 UTF-8 BOM 的 CSV（Excel 打开不乱码）。
- **页面设置**：`PUT /api/admin/settings {title, date_text, welcome}`。
- **平面图**：`POST /api/admin/floorplan`，请求体为图片原始字节，`Content-Type` 限 `image/png|jpeg|webp`，≤ 5MB；`DELETE` 移除。（Python 3.13+ 已无 `cgi` 模块，避免 multipart 解析。）

### 安全细节

- 所有 SQL 参数化。前端插入用户数据一律用 `textContent`，不用 `innerHTML`。
- 请求体上限 6MB。静态文件只服务 `static/` 下白名单文件，防目录穿越。
- 响应加 `X-Content-Type-Options: nosniff`；后台接口 `Cache-Control: no-store`。

### 部署（北京 ECS）

1. 代码放 `/opt/wedding-seat`（git clone 或 scp）。
2. `/etc/wedding-seat.env` 写 `ADMIN_PASSWORD=...`，权限 600。
3. `deploy/wedding-seat.service`：`User=ecs-user`，`EnvironmentFile=/etc/wedding-seat.env`，`Restart=always`，`systemctl enable --now`。
4. 阿里云安全组入方向放行 TCP 8001。
5. 微信实测 `http://39.106.139.161:8001`。

### 迁移（香港服务器 + 域名）

复制代码与 `data/` 目录 → 同样的 systemd 配置 → Caddy 反代域名到 `127.0.0.1:8001`（自动 HTTPS，`HOST` 改为 `127.0.0.1`）→ 微信实测是否仍弹提示 → 决定二维码用哪个地址。

**单一数据源**：环境变量 `REDIRECT_TO`（如 `https://example.com`）一旦设置，北京实例对所有请求返回 302 跳转到该地址的同路径，不再读写自己的数据。这样即使二维码已按北京地址印出，数据也只在香港一份。

**截止时间**：香港方案须在迎宾牌/桌牌送印前实测完毕；来不及就用北京地址印。

**部署执行者**：用户本人（开发侧无服务器 SSH / 控制台权限）。交付物含逐步部署说明（README）。

### 测试

`python3 -m unittest`：姓名规范化、精确/模糊/同名查询、公开接口绝不返回内部备注、限流、REDIRECT_TO 跳转、导入解析（表头映射）（表头、制表符/逗号、错误行整体回滚）、登录签名与过期、锁定逻辑、静态文件路径穿越。手动：手机微信实测查询页与后台。

## 留给实现者

- 页面视觉风格（简洁、喜庆但不俗；移动端优先，查询结果桌号大字醒目）。
- 二维码生成：README 中说明用任意二维码生成工具即可，不在本服务内实现。
