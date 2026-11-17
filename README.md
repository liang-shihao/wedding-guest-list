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
- 平面图建议先压缩到几百 KB 以内再上传（服务器带宽小，图越小宾客打开越快）。

## 部署到服务器（Ubuntu，systemd）

推荐用安装脚本，一条命令完成：复制代码到 `/opt/wedding-seat`、跑测试、生成后台密码（存在 `/etc/wedding-seat.env`）、注册并启动 systemd 服务。可重复执行，已有数据和密码会保留，更新代码也用它。

```bash
cd ~ && git clone --depth 1 https://github.com/liang-shihao/wedding-guest-list.git \
 && cd wedding-guest-list && bash deploy/make-installer.sh > /tmp/i.sh && bash /tmp/i.sh
# 以后更新：cd ~/wedding-guest-list && git pull && bash deploy/make-installer.sh > /tmp/i.sh && bash /tmp/i.sh
```

服务器连不上 GitHub 时，在本地执行 `bash deploy/make-installer.sh > install.sh`，把这一个文件传到服务器上 `bash install.sh`，效果相同。

常用运维：

```bash
sudo systemctl status wedding-seat        # 状态
sudo journalctl -u wedding-seat -n 50     # 日志
sudo systemctl restart wedding-seat       # 重启（改密码后需要）
sudo cat /etc/wedding-seat.env            # 查看后台密码
ls /opt/wedding-seat/data/backups/        # 名单备份
```

## 域名 + HTTPS（推荐，避免微信「继续访问」警告）

微信打开 `http://IP:端口` 会先弹安全提示，宾客要多点一次「继续访问」。换成「域名 + HTTPS」可以去掉。

**选服务器**：大陆服务器绑定域名必须先 ICP 备案（1～3 周），所以用**香港**服务器，不需要备案。轻量应用服务器 2 核 2G、峰值带宽 20Mbps 以上就足够；不要选 1Mbps 带宽的，背景图会很慢。镜像选 Ubuntu 22.04/24.04 系统镜像。

**先测 IP 通不通**：买完先在 <https://www.itdog.cn/tcping/> 测 `IP:22`。云厂商回收再分配的 IP 可能在大陆被屏蔽（表现为只有港台节点通、大陆全红，手机打不开但开了代理的电脑能打开）。遇到这种情况在控制台「更换公网 IP」，测通了再部署。

**步骤：**

1. 按上一节安装程序。控制台的防火墙（轻量服务器叫「防火墙」，云服务器叫「安全组」）放行 TCP 22、80、443。
2. 买域名（`.com`/`.cn` 均可，需实名；避开 `.top`/`.xyz` 等易被微信拦截的后缀），添加 A 记录 `@` → 服务器 IP。
3. 在服务器上安装 Caddy 并配置（把 `example.com` 换成你的域名），Caddy 会自动申请证书：

   ```bash
   sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
   sudo apt update && sudo apt install -y caddy
   printf 'example.com {\n\tencode gzip\n\treverse_proxy 127.0.0.1:8001\n}\n' | sudo tee /etc/caddy/Caddyfile
   printf 'HOST=127.0.0.1\nTRUST_PROXY=1\n' | sudo tee -a /etc/wedding-seat.env
   sudo systemctl restart wedding-seat caddy
   curl -sI https://example.com | head -1      # 出现 HTTP/2 200 即成功
   ```

   之后程序只监听本机，外部统一走 `https://域名`，`IP:8001` 打不开是正常的。80 端口必须留给 Caddy（申请证书要用），不要在上面做别的转发。
4. 用手机微信打开 `https://域名` 实测，最好电信、联通、移动各试一台。

**旧地址跳转**：如果之前在别的服务器上用过 IP 地址（二维码已发出），在**旧服务器**的 `/etc/wedding-seat.env` 加一行 `REDIRECT_TO=https://域名` 并重启服务，旧码扫进来会自动跳到新地址。需要保留旧数据时，先把旧服务器的 `/opt/wedding-seat/data/` 整个复制到新服务器同一位置再启动。

## 后台多人使用

可以多人、多设备同时登录（共用一个密码，每台设备登录一次，7 天有效）。注意：

- 改的是不同宾客时互不影响；两人同时改同一位宾客，以后保存的为准。
- 别人改的内容不会自动出现在你的页面上，刷新一下才能看到。
- 「覆盖导入」会替换整份名单（导入前自动备份），多人协作时只让一个人做导入。
- 「退出登录」只退出当前设备。要让所有设备都失效，修改 `/etc/wedding-seat.env` 里的密码并重启服务。

## 二维码

用任意二维码生成工具（如草料二维码）把查询页地址（换了域名就用 `https://域名`）转成二维码即可。
