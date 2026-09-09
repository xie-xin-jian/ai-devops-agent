---
name: network-security
description: 网络基础与安全，涵盖网络配置、防火墙、SSL/TLS、安全加固等
---

# 网络基础与安全

## 网络基础

### IP 地址

```bash
# 查看本机 IP
ip addr show
ifconfig

# 查看路由表
ip route show

# DNS 配置
cat /etc/resolv.conf

# 测试 DNS
nslookup google.com
dig google.com
```

### 端口

```bash
# 查看监听端口
ss -tlnp

# 查看所有连接
ss -tuln

# 查看特定端口
ss -tlnp | grep :80

# 检查端口连通性
telnet localhost 8000
nc -zv localhost 8000
```

### 网络测试

```bash
# 测试连通性
ping google.com
ping -c 4 google.com  # 发送 4 个包

# 测试端口
curl http://localhost:8000/health

# 跟踪路由
traceroute google.com  # Linux
tracert google.com     # Windows

# 检查 DNS 解析
dig @8.8.8.8 google.com
```

## HTTP 基础

### HTTP 状态码

| 状态码 | 类别 | 说明 |
|--------|------|------|
| 1xx | 信息 | 请求已接收，继续处理 |
| 2xx | 成功 | 请求成功 |
| 3xx | 重定向 | 需要进一步操作 |
| 4xx | 客户端错误 | 请求有问题 |
| 5xx | 服务器错误 | 服务器内部错误 |

### 常见状态码

```bash
# 200 OK - 请求成功
# 301 Moved Permanently - 永久重定向
# 400 Bad Request - 请求参数错误
# 401 Unauthorized - 未授权
# 403 Forbidden - 禁止访问
# 404 Not Found - 资源不存在
# 500 Internal Server Error - 服务器内部错误
# 502 Bad Gateway - 网关错误
# 503 Service Unavailable - 服务不可用
# 504 Gateway Timeout - 网关超时
```

### curl 使用

```bash
# 发送 GET 请求
curl http://localhost:8000/health

# 发送 POST 请求
curl -X POST -H "Content-Type: application/json" -d '{"message":"hello"}' http://localhost:8000/api/chat/

# 查看响应头
curl -I http://localhost:8000/health

# 保存响应到文件
curl -o response.json http://localhost:8000/api/skills/

# 跟随重定向
curl -L http://example.com
```

## HTTPS 配置

### SSL/TLS 证书

```bash
# 使用 Let's Encrypt 免费证书
sudo apt install certbot python3-certbot-nginx

# 获取证书
sudo certbot --nginx -d example.com

# 自动续期
sudo certbot renew --dry-run
```

### Nginx HTTPS 配置

```nginx
server {
    listen 443 ssl;
    server_name example.com;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# HTTP 重定向到 HTTPS
server {
    listen 80;
    server_name example.com;
    return 301 https://$host$request_uri;
}
```

## CORS 配置

### FastAPI CORS 配置

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 生产环境配置

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://example.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)
```

## 防火墙

### iptables

```bash
# 查看规则
sudo iptables -L

# 允许本地回环
sudo iptables -A INPUT -i lo -j ACCEPT

# 允许已建立的连接
sudo iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# 允许 SSH
sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT

# 允许 HTTP/HTTPS
sudo iptables -A INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT

# 允许特定端口
sudo iptables -A INPUT -p tcp --dport 8000 -j ACCEPT

# 拒绝所有其他入站流量
sudo iptables -A INPUT -j DROP

# 保存配置
sudo iptables-save > /etc/iptables/rules.v4
```

### 端口转发

```bash
# 将 80 端口转发到 8000
sudo iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8000

# 将外部端口转发到内部服务
sudo iptables -t nat -A PREROUTING -p tcp --dport 8080 -j DNAT --to-destination 192.168.1.100:8000
```

## 安全加固

### SSH 安全

```bash
# 修改 SSH 端口
sudo sed -i 's/Port 22/Port 2222/' /etc/ssh/sshd_config

# 禁止 root 登录
sudo sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config

# 禁用密码登录（使用密钥）
sudo sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config

# 重启 SSH
sudo systemctl restart sshd
```

### 用户管理

```bash
# 创建普通用户
sudo useradd -m -s /bin/bash devops

# 设置密码
sudo passwd devops

# 添加到 sudo 组
sudo usermod -aG sudo devops

# 切换用户
su - devops

# 删除用户
sudo userdel -r devops
```

### 文件权限

```bash
# 修改文件权限
chmod 644 file.txt      # 所有者读写，其他只读
chmod 755 directory     # 所有者读写执行，其他读执行

# 修改所有者
chown user:group file.txt

# 修改目录所有者（递归）
chown -R user:group directory/

# 禁止其他用户访问
chmod 700 ~/.ssh/
```

## 安全检查

### 扫描开放端口

```bash
# 使用 nmap 扫描
nmap -sS localhost

# 扫描特定端口
nmap -p 80,443,8000 localhost

# 全面扫描
nmap -A localhost
```

### 检查漏洞

```bash
# Debian/Ubuntu
sudo apt update && sudo apt upgrade

# CentOS/RHEL
sudo yum update

# 检查安全更新
sudo unattended-upgrades
```

### 日志审计

```bash
# 查看登录尝试
grep "Failed password" /var/log/auth.log

# 查看 sudo 日志
grep "sudo" /var/log/auth.log

# 检查异常登录
last -20

# 检查当前登录用户
who
w
```

## 本项目网络配置

### 开发环境

```bash
# 后端启动
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 前端启动（带代理）
cd frontend
npm run dev
# Vite 配置会将 /api 请求代理到 http://localhost:8000
```

### 生产环境

```bash
# Nginx 反向代理配置
sudo cat > /etc/nginx/sites-available/devops-agent << 'EOF'
server {
    listen 80;
    server_name devops.example.com;

    location / {
        root /opt/ai-devops-agent/static;
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /health {
        proxy_pass http://localhost:8000;
    }
}
EOF

# 启用站点
sudo ln -s /etc/nginx/sites-available/devops-agent /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 配置 HTTPS

```bash
# 获取证书
sudo certbot --nginx -d devops.example.com

# 配置完成后自动生成 HTTPS 配置
```

## 常见问题

### 无法访问服务

```bash
# 1. 检查服务是否运行
systemctl status devops-agent

# 2. 检查端口是否监听
ss -tlnp | grep :8000

# 3. 检查防火墙
ufw status
iptables -L

# 4. 检查网络连接
curl http://localhost:8000/health

# 5. 检查 DNS
nslookup devops.example.com
```

### CORS 错误

```bash
# 检查浏览器控制台错误
# 确认后端 CORS 配置正确
# 在开发环境允许所有来源，生产环境限制特定域名
```

### SSL 证书过期

```bash
# 检查证书过期时间
openssl x509 -enddate -noout -in /etc/letsencrypt/live/example.com/fullchain.pem

# 续期证书
sudo certbot renew
```
