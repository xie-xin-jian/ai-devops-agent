---
name: service-deploy
description: 服务部署与进程管理，涵盖 systemd 配置、守护进程、进程监控等
---

# 服务部署与进程管理

## systemd 服务配置

### 创建服务文件

创建 `/etc/systemd/system/devops-agent.service`：

```ini
[Unit]
Description=AI DevOps Agent Service
After=network.target

[Service]
Type=simple
User=devops
WorkingDirectory=/opt/ai-devops-agent
ExecStart=/opt/ai-devops-agent/.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
Environment="PYTHONPATH=/opt/ai-devops-agent"

[Install]
WantedBy=multi-user.target
```

### 常用命令

```bash
# 重新加载配置
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start devops-agent

# 停止服务
sudo systemctl stop devops-agent

# 重启服务
sudo systemctl restart devops-agent

# 查看状态
sudo systemctl status devops-agent

# 设置开机自启
sudo systemctl enable devops-agent

# 取消开机自启
sudo systemctl disable devops-agent

# 查看服务日志
sudo journalctl -u devops-agent
sudo journalctl -u devops-agent -f  # 实时查看
```

### 服务状态说明

| 状态 | 含义 |
|------|------|
| `active (running)` | 服务正常运行 |
| `active (exited)` | 服务已完成（一次性任务） |
| `active (waiting)` | 服务正在等待某个条件 |
| `inactive` | 服务未运行 |
| `failed` | 服务启动失败 |

## 进程管理

### 查看进程

```bash
# 查看所有进程
ps aux

# 按 CPU 使用排序
ps aux --sort=-%cpu | head -10

# 按内存使用排序
ps aux --sort=-%mem | head -10

# 查看特定进程
ps aux | grep python
ps aux | grep uvicorn
```

### 进程状态

```bash
# 查看进程树
pstree

# 查看进程详细信息
cat /proc/<pid>/status
cat /proc/<pid>/cmdline  # 命令行参数
```

### 终止进程

```bash
# 优雅终止（发送 SIGTERM）
kill <pid>

# 强制终止（发送 SIGKILL）
kill -9 <pid>

# 按名称终止进程
pkill <process-name>
pkill -f <pattern>  # 按命令行模式匹配
```

## 后台运行

### 使用 nohup

```bash
# 后台运行并输出到日志文件
nohup python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 > app.log 2>&1 &

# 查看后台任务
jobs

# 恢复到前台
fg %1

# 查看进程 ID
echo $!
```

### 使用 tmux 或 screen

```bash
# 创建新会话
tmux new -s devops-agent

# 分离会话（保持运行）
Ctrl + B, D

# 查看会话列表
tmux ls

# 重新连接会话
tmux attach -t devops-agent
```

## 端口管理

### 查看端口占用

```bash
# Linux
ss -tlnp
netstat -tlnp

# 查看特定端口
ss -tlnp | grep :8000

# Windows
netstat -ano | findstr :8000
```

### 端口转发

```bash
# 将 80 端口转发到 8000
sudo iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8000

# 持久化配置（不同发行版方式不同）
sudo iptables-save > /etc/iptables/rules.v4
```

## 防火墙配置

### ufw（Ubuntu/Debian）

```bash
# 允许 HTTP
sudo ufw allow 80/tcp

# 允许 HTTPS
sudo ufw allow 443/tcp

# 允许特定端口
sudo ufw allow 8000/tcp

# 允许从特定 IP 访问
sudo ufw allow from 192.168.1.0/24 to any port 8000

# 查看规则
sudo ufw status

# 启用防火墙
sudo ufw enable
```

### firewalld（CentOS/RHEL）

```bash
# 允许服务
sudo firewall-cmd --add-service=http --permanent
sudo firewall-cmd --add-service=https --permanent

# 允许端口
sudo firewall-cmd --add-port=8000/tcp --permanent

# 重新加载
sudo firewall-cmd --reload

# 查看状态
sudo firewall-cmd --list-all
```

## 部署最佳实践

### 目录结构

```
/opt/ai-devops-agent/
├── current/        # 当前版本（软链接）
├── releases/       # 版本历史
│   ├── v1.0.0/
│   └── v1.1.0/
├── logs/           # 日志目录
└── .env            # 环境变量
```

### 部署流程

```bash
# 1. 拉取代码
cd /opt/ai-devops-agent/releases
git clone <repo> v1.1.0
cd v1.1.0

# 2. 安装依赖
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. 构建前端
cd frontend
npm install
npm run build

# 4. 更新软链接
rm /opt/ai-devops-agent/current
ln -s /opt/ai-devops-agent/releases/v1.1.0 /opt/ai-devops-agent/current

# 5. 重启服务
sudo systemctl restart devops-agent
```

### 回滚

```bash
# 更新软链接到旧版本
rm /opt/ai-devops-agent/current
ln -s /opt/ai-devops-agent/releases/v1.0.0 /opt/ai-devops-agent/current

# 重启服务
sudo systemctl restart devops-agent
```

## 健康检查脚本

```bash
#!/bin/bash

URL="http://localhost:8000/health"
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" $URL)

if [ $RESPONSE -eq 200 ]; then
    echo "OK - Service is running"
    exit 0
else
    echo "CRITICAL - Service is down (HTTP $RESPONSE)"
    exit 2
fi
```

使用：
```bash
chmod +x health_check.sh
./health_check.sh
```

## 本项目服务化部署

```bash
# 1. 创建用户
sudo useradd -m -s /bin/bash devops

# 2. 安装项目
sudo git clone <repo> /opt/ai-devops-agent
sudo chown -R devops:devops /opt/ai-devops-agent

# 3. 创建虚拟环境
sudo -u devops python -m venv /opt/ai-devops-agent/.venv
sudo -u devops /opt/ai-devops-agent/.venv/bin/pip install -r /opt/ai-devops-agent/requirements.txt

# 4. 创建 systemd 服务文件
sudo cat > /etc/systemd/system/devops-agent.service << 'EOF'
[Unit]
Description=AI DevOps Agent Service
After=network.target

[Service]
Type=simple
User=devops
WorkingDirectory=/opt/ai-devops-agent
ExecStart=/opt/ai-devops-agent/.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 5. 启动服务
sudo systemctl daemon-reload
sudo systemctl enable devops-agent
sudo systemctl start devops-agent
```
