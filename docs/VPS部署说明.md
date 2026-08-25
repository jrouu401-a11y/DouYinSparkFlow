# VPS 部署

正式定时任务运行在长期在线的 Ubuntu 22.04/24.04 VPS 上，GitHub Actions 仅保留手动诊断入口。建议服务器至少 2 vCPU、4 GB 内存，并使用独立的低权限 `douyin` 用户。

## 安装

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git curl ca-certificates
sudo useradd --system --create-home --shell /usr/sbin/nologin douyin || true
sudo install -d -o douyin -g douyin /opt/douyin-spark-flow /etc/douyin-spark-flow /var/lib/douyin-spark-flow
sudo git clone https://github.com/jrouu401-a11y/DouYinSparkFlow.git /opt/douyin-spark-flow
sudo chown -R douyin:douyin /opt/douyin-spark-flow
sudo -u douyin python3 -m venv /opt/douyin-spark-flow/.venv
sudo -u douyin /opt/douyin-spark-flow/.venv/bin/pip install -r /opt/douyin-spark-flow/requirements.txt
sudo -u douyin /opt/douyin-spark-flow/.venv/bin/playwright install chromium
```

将配置生成器产生的变量和 Cookies 写入 `/etc/douyin-spark-flow/.env`，不要提交到 Git：

```bash
sudo install -o douyin -g douyin -m 600 /path/to/.env /etc/douyin-spark-flow/.env
```

部署前应重新导出 Cookie。Cookie 失效或抖音出现验证码时，任务会失败，不绕过平台验证。

## 启用定时器

```bash
sudo cp /opt/douyin-spark-flow/deploy/systemd/douyin-spark-flow.service /etc/systemd/system/
sudo cp /opt/douyin-spark-flow/deploy/systemd/douyin-spark-flow.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now douyin-spark-flow.timer
systemctl list-timers douyin-spark-flow.timer
```

四个窗口使用北京时间 09:00、09:30、10:00、10:30。状态保存于 `/var/lib/douyin-spark-flow/run-state.json`；已确认发送的目标不会被补偿窗口重复发送，Enter 后未确认的目标也不会自动重发。

## 检查与故障处理

```bash
sudo systemctl start douyin-spark-flow.service
sudo journalctl -u douyin-spark-flow.service -n 200 --no-pager
sudo systemctl status douyin-spark-flow.timer
```

只有所有目标均为“已确认发送”时服务才返回成功。建议接入 Healthchecks 或 Uptime Kuma，监控每天是否产生成功汇总；不要把 Cookie、消息正文或完整 `.env` 放进外部监控 URL。
