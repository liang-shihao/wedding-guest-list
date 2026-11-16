#!/usr/bin/env bash
# Build a self-contained installer: bash deploy/make-installer.sh > install.sh
# Then run it on the server: bash install.sh
set -euo pipefail
cd "$(dirname "$0")/.."
cat <<'HEAD'
#!/usr/bin/env bash
# Wedding seat lookup installer. Safe to re-run: keeps data/ and the existing password.
set -euo pipefail
APP=/opt/wedding-seat
ENV=/etc/wedding-seat.env
RUN_USER=${RUN_USER:-$(id -un)}
echo "==> 安装到 $APP（运行用户 $RUN_USER）"
sudo mkdir -p "$APP"
sudo chown "$RUN_USER" "$APP"
base64 -d > /tmp/wedding-seat.tgz <<'B64'
HEAD
git archive --format=tar.gz HEAD app.py seat static deploy tests README.md | base64 -w 76
cat <<'TAIL'
B64
tar -xzf /tmp/wedding-seat.tgz -C "$APP"
rm -f /tmp/wedding-seat.tgz
echo "==> 运行测试"
(cd "$APP" && python3 -m unittest discover -s . -p "test_*.py" 2>&1 | tail -3)
if [ ! -f "$ENV" ]; then
  PW=$(python3 -c "import secrets; print(secrets.token_urlsafe(9))")
  sudo install -m 600 /dev/null "$ENV"
  echo "ADMIN_PASSWORD=$PW" | sudo tee "$ENV" >/dev/null
  echo "==> 已生成后台密码：$PW   （保存在 $ENV）"
else
  echo "==> 保留已有配置 $ENV"
fi
sed "s/^User=.*/User=$RUN_USER/" "$APP/deploy/wedding-seat.service" | sudo tee /etc/systemd/system/wedding-seat.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable wedding-seat >/dev/null 2>&1
sudo systemctl restart wedding-seat
sleep 2
echo "==> 自检"
curl -fsS http://127.0.0.1:8001/api/settings && echo
sudo ss -ltnp | grep -E ':(8000|8001) ' || true
echo "==> 完成。记得在安全组放行 TCP 8001，然后访问 http://<公网IP>:8001/ 和 /admin"
TAIL
