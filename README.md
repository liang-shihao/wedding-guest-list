# 婚礼座位查询

宾客微信扫码 → 输入姓名 → 显示桌号。附带密码保护的后台（`/admin`），可在手机上改座位、从 Excel 粘贴导入、导出、上传平面图。

- 纯 Python 3 标准库，无需安装任何依赖；前端无外部资源。
- 名单存在服务器上的 SQLite（`data/guests.db`），公开接口只返回查询到的那几个人，且不含「内部备注」。

## 本地运行

```bash
ADMIN_PASSWORD=换成你的密码 python3 app.py
# 查询页 http://127.0.0.1:8001/   后台 http://127.0.0.1:8001/admin
python3 -m unittest discover -s . -p "test_*.py"   # 跑测试
```

环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `ADMIN_PASSWORD` | 必填 | 后台密码。修改后所有已登录会话失效 |
| `PORT` | `8001` | 监听端口 |
| `HOST` | `0.0.0.0` | 监听地址；放在 Caddy 后面时用 `127.0.0.1` |
| `DATA_DIR` | `./data` | 数据目录（数据库、平面图、备份） |
| `TRUST_PROXY` | 空 | 设为 `1` 时从 `X-Forwarded-For` 取客户端 IP（仅在反向代理后使用） |
| `REDIRECT_TO` | 空 | 设置后所有请求 302 跳转到该地址（迁移后让旧地址跳到新地址） |

## 名单格式

在后台「批量导入」里粘贴 Excel 内容。表头可用：`姓名`、`桌号`、`公开说明`（或 `说明`）、`内部备注`（或 `备注`）。

- **公开说明**：宾客能看到，用来区分同名的人（如「新郎大学同学」）。
- **内部备注**：只有后台能看到（如「素食」）。单独的「备注」列默认算内部备注。
- 覆盖导入、删除宾客前会自动备份到 `data/backups/`（保留最近 50 份）。

## 部署到服务器（Ubuntu，systemd）

代码放 `/opt/wedding-seat`，然后：

```bash
sudo install -m 600 /dev/null /etc/wedding-seat.env
echo 'ADMIN_PASSWORD=换成你的密码' | sudo tee /etc/wedding-seat.env >/dev/null
sudo cp /opt/wedding-seat/deploy/wedding-seat.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wedding-seat
curl -s http://127.0.0.1:8001/api/settings     # 返回 JSON 即正常
```

再在云服务器安全组「入方向」放行 TCP 8001。

常用运维：

```bash
sudo systemctl status wedding-seat        # 状态
sudo journalctl -u wedding-seat -n 50     # 日志
sudo systemctl restart wedding-seat       # 重启（改密码后需要）
ls /opt/wedding-seat/data/backups/        # 名单备份
```

## 迁移到香港服务器 + 域名

1. 新服务器上按上面步骤部署，把旧服务器的 `/opt/wedding-seat/data/` 整个复制过去。
2. 装 Caddy，参考 `deploy/Caddyfile.example`，`/etc/wedding-seat.env` 里加 `HOST=127.0.0.1` 和 `TRUST_PROXY=1`。
3. 域名解析到新服务器，安全组放行 80/443，用微信打开 `https://你的域名` 实测。
4. 确定用新地址后，在**旧服务器**的 `/etc/wedding-seat.env` 加一行 `REDIRECT_TO=https://你的域名` 并重启服务。这样即使二维码印的是旧地址，也会自动跳到新地址，数据只在新服务器一份。

## 二维码

用任意二维码生成工具（如草料二维码）把查询页地址转成二维码即可。
