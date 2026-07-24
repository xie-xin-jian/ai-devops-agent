---
name: learning-path
description: AI DevOps Agent 学习路线指引，从零基础到完全掌握项目使用
---

# AI DevOps Agent 学习路线

## 学习目标

通过本学习路线，你将：
1. ✅ 完全掌握本项目的使用方法
2. ✅ 具备基础运维技能
3. ✅ 能够独立部署和维护服务
4. ✅ 了解 Agent 开发中需要的运维知识

---

## 学习路线图

```
┌─────────────────────────────────────────────────────────────────┐
│                    第一阶段：入门基础                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐   │
│  │  Git 基础 │  │ Linux 基础│  │ 终端操作  │  │ 网络基础  │   │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘   │
└────────┴──────────────┴──────────────┴──────────────┴──────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    第二阶段：项目实战                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐   │
│  │ Python    │  │ FastAPI   │  │ 前后端    │  │ 技能系统  │   │
│  │ 虚拟环境  │  │ 部署指南  │  │ 启动调试  │  │ 使用指南  │   │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘   │
└────────┴──────────────┴──────────────┴──────────────┴──────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    第三阶段：运维进阶                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐   │
│  │ 服务部署  │  │ 日志监控  │  │ Docker    │  │ Nginx     │   │
│  │ 进程管理  │  │ 告警配置  │  │ 容器化    │  │ 反向代理  │   │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘   │
└────────┴──────────────┴──────────────┴──────────────┴──────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    第四阶段：安全加固                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐   │
│  │ 防火墙    │  │ SSL/TLS   │  │ SSH 安全  │  │ 权限管理  │   │
│  │ 配置      │  │ 证书配置  │  │ 加固      │  │           │   │
│  └───────────┘  └───────────┘  └───────────┘  └───────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 第一阶段：入门基础（1-2 天）

### 学习内容

| 技能文件 | 学习重点 | 预计时间 |
|----------|----------|----------|
| [git-basics](file:///d:/ai_agent/ai-devops-agent/skills/git-basics/SKILL.md) | 版本控制、分支管理、远程操作 | 半天 |
| [linux-basics](file:///d:/ai_agent/ai-devops-agent/skills/linux-basics/SKILL.md) | 系统监控、进程管理、文件操作 | 1 天 |
| [network-security](file:///d:/ai_agent/ai-devops-agent/skills/network-security/SKILL.md) | IP 地址、端口、HTTP 基础 | 半天 |

### 实践任务

1. **安装 Git 并配置**
   ```bash
   git config --global user.name "你的名字"
   git config --global user.email "你的邮箱"
   ```

2. **克隆项目到本地**
   ```bash
   git clone <项目地址>
   cd ai-devops-agent
   ```

3. **熟悉 Linux 命令**
   ```bash
   ls -la              # 查看目录内容
   cd /path/to/dir     # 切换目录
   pwd                 # 当前目录
   mkdir test          # 创建目录
   touch test.txt      # 创建文件
   ```

4. **检查网络状态**
   ```bash
   ping baidu.com
   ss -tlnp
   ```

### 学习目标
- 能够使用 Git 管理代码
- 能够使用基本 Linux 命令操作文件和目录
- 理解 IP、端口、HTTP 等基本网络概念

---

## 第二阶段：项目实战（2-3 天）

### 学习内容

| 技能文件 | 学习重点 | 预计时间 |
|----------|----------|----------|
| [python-deploy](file:///d:/ai_agent/ai-devops-agent/skills/python-deploy/SKILL.md) | 虚拟环境、依赖管理、服务启动 | 1 天 |
| [linux-basics](file:///d:/ai_agent/ai-devops-agent/skills/linux-basics/SKILL.md) | 项目常用命令章节 | 半天 |
| 项目代码阅读 | api/main.py, agent/comprehensive.py | 1 天 |

### 实践任务

1. **创建虚拟环境并安装依赖**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **启动后端服务**
   ```bash
   python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
   ```

3. **启动前端服务**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

4. **测试 API**
   ```bash
   curl http://localhost:8000/health
   curl http://localhost:8000/api/skills/
   ```

5. **使用前端界面**
   - 访问 http://localhost:5173/
   - 尝试对话功能
   - 浏览技能页面
   - 查看工具列表

### 学习目标
- 能够独立启动项目（前后端）
- 理解项目结构和核心文件
- 能够使用前端界面完成基本操作

---

## 第三阶段：运维进阶（3-5 天）

### 学习内容

| 技能文件 | 学习重点 | 预计时间 |
|----------|----------|----------|
| [service-deploy](file:///d:/ai_agent/ai-devops-agent/skills/service-deploy/SKILL.md) | systemd 服务配置、进程管理 | 1 天 |
| [log-monitor](file:///d:/ai_agent/ai-devops-agent/skills/log-monitor/SKILL.md) | 日志查看、分析、监控 | 1 天 |
| [docker-debug](file:///d:/ai_agent/ai-devops-agent/skills/docker-debug/SKILL.md) | Docker 容器管理、排错 | 1 天 |
| [nginx-troubleshooting](file:///d:/ai_agent/ai-devops-agent/skills/nginx-troubleshooting/SKILL.md) | Nginx 配置、故障排查 | 1 天 |

### 实践任务

1. **配置 systemd 服务**
   ```bash
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

   sudo systemctl daemon-reload
   sudo systemctl enable devops-agent
   sudo systemctl start devops-agent
   ```

2. **查看和分析日志**
   ```bash
   tail -f app.log
   grep "ERROR" app.log
   sudo journalctl -u devops-agent -f
   ```

3. **Docker 部署**
   ```bash
   # 创建 Dockerfile
   cat > Dockerfile << 'EOF'
   FROM python:3.10-slim

   WORKDIR /app
   COPY requirements.txt .
   RUN pip install -r requirements.txt --no-cache-dir

   COPY . .
   CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
   EOF

   # 构建和运行
   docker build -t devops-agent .
   docker run -d -p 8000:8000 devops-agent
   ```

4. **Nginx 反向代理**
   ```bash
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
       }
   }
   EOF

   sudo ln -s /etc/nginx/sites-available/devops-agent /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl reload nginx
   ```

### 学习目标
- 能够将项目部署为系统服务
- 能够查看和分析日志
- 了解 Docker 容器化部署
- 能够配置 Nginx 反向代理

---

## 第四阶段：安全加固（1-2 天）

### 学习内容

| 技能文件 | 学习重点 | 预计时间 |
|----------|----------|----------|
| [network-security](file:///d:/ai_agent/ai-devops-agent/skills/network-security/SKILL.md) | 防火墙、SSL/TLS、SSH 安全 | 1 天 |

### 实践任务

1. **配置防火墙**
   ```bash
   # Ubuntu/Debian
   sudo ufw enable
   sudo ufw allow 22/tcp
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw status
   ```

2. **配置 HTTPS**
   ```bash
   sudo apt install certbot python3-certbot-nginx
   sudo certbot --nginx -d devops.example.com
   ```

3. **加固 SSH**
   ```bash
   sudo sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
   sudo sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
   sudo systemctl restart sshd
   ```

### 学习目标
- 能够配置防火墙规则
- 能够配置 HTTPS 证书
- 了解基本的服务器安全加固措施

---

## 每日学习计划示例

### 第 1 天：Git 和 Linux 基础
- 上午：学习 git-basics 技能文件，练习基本 Git 操作
- 下午：学习 linux-basics 技能文件，练习系统命令
- 晚上：克隆项目，了解项目结构

### 第 2 天：网络基础和项目启动
- 上午：学习 network-security 技能文件的网络基础部分
- 下午：启动后端服务，测试 API
- 晚上：启动前端服务，使用界面

### 第 3 天：Python 部署和项目实战
- 上午：学习 python-deploy 技能文件
- 下午：练习虚拟环境管理，依赖安装
- 晚上：完整启动项目，完成一次对话

### 第 4 天：服务部署和进程管理
- 上午：学习 service-deploy 技能文件
- 下午：配置 systemd 服务
- 晚上：测试服务自启动和重启

### 第 5 天：日志管理和监控
- 上午：学习 log-monitor 技能文件
- 下午：配置日志轮转，练习日志分析
- 晚上：编写简单的健康检查脚本

### 第 6 天：Docker 和 Nginx
- 上午：学习 docker-debug 技能文件
- 下午：使用 Docker 部署项目
- 晚上：配置 Nginx 反向代理

### 第 7 天：安全加固和总结
- 上午：学习 network-security 技能文件的安全部分
- 下午：配置防火墙和 HTTPS
- 晚上：复习总结，完成部署测试

---

## 学习资源推荐

### 在线教程
- **Linux 命令教程**: https://linuxize.com/
- **Git 教程**: https://www.atlassian.com/git/tutorials
- **FastAPI 文档**: https://fastapi.tiangolo.com/
- **Docker 入门**: https://docs.docker.com/get-started/

### 工具推荐
- **终端工具**: Windows Terminal, iTerm2
- **SSH 工具**: PuTTY, Termius
- **文件传输**: FileZilla, scp

---

## 常见问题解答

### Q1: 端口被占用怎么办？
```bash
# 查找占用端口的进程
ss -tlnp | grep :8000

# 杀死进程
kill -9 <pid>
```

### Q2: 后端启动失败？
```bash
# 检查依赖是否安装
pip list | grep fastapi

# 检查 Python 版本
python --version

# 查看错误日志
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### Q3: 前端无法访问后端？
```bash
# 检查后端是否运行
curl http://localhost:8000/health

# 检查 Vite 代理配置
cat frontend/vite.config.ts

# 检查 CORS 配置
cat api/main.py | grep -A 10 CORSMiddleware
```

### Q4: 如何更新代码？
```bash
# 拉取最新代码
git pull origin main

# 安装新依赖（如有）
pip install -r requirements.txt

# 重启服务
sudo systemctl restart devops-agent
```

---

## 学习检验清单

- [ ] 能够使用 Git 克隆、提交、推送代码
- [ ] 能够使用基本 Linux 命令（ls, cd, mkdir, rm, grep 等）
- [ ] 能够独立启动项目前后端
- [ ] 能够使用前端界面完成对话
- [ ] 能够查看和分析服务日志
- [ ] 能够配置 systemd 服务实现开机自启
- [ ] 能够使用 Docker 部署项目
- [ ] 能够配置 Nginx 反向代理
- [ ] 能够配置防火墙和 HTTPS
- [ ] 能够排查常见的服务启动问题

---

## 结束语

学习运维是一个循序渐进的过程，不要急于求成。建议每天花 1-2 小时学习，多动手实践。遇到问题时，先尝试自己查找解决方案，这也是运维能力的重要组成部分。

祝你学习顺利！🚀
