---
name: linux-basics
description: Linux 基础运维命令速查，涵盖系统监控、进程管理、网络诊断等
---

# Linux 基础运维命令速查

## 系统资源监控

### CPU
```bash
top              # 实时进程和资源监控
htop             # 增强版 top
mpstat 1         # 每 1 秒显示 CPU 使用统计
```

### 内存
```bash
free -h          # 内存使用情况（人类可读）
vmstat 1         # 虚拟内存统计
```

### 磁盘
```bash
df -h            # 磁盘空间使用
du -sh /path     # 目录大小
iostat -x 1      # 磁盘 I/O 统计
ncdu             # 交互式磁盘使用分析
```

### 网络
```bash
ss -tlnp         # 监听的 TCP 端口
ss -s            # 连接统计
iftop            # 实时网络流量
nethogs          # 按进程统计网络流量
```

## 进程管理

```bash
ps aux                     # 所有进程
ps aux | grep <keyword>    # 搜索进程
kill <pid>                 # 终止进程
kill -9 <pid>              # 强制终止
pkill <name>               # 按名称杀进程
```

## 日志查看

```bash
tail -f /var/log/syslog       # 实时跟踪系统日志
tail -n 100 /var/log/syslog   # 最后 100 行
grep 'error' /var/log/syslog  # 搜索关键词
journalctl -u nginx           # systemd 服务日志
journalctl -f -u nginx        # 实时跟踪服务日志
```

## 用户和权限

```bash
whoami             # 当前用户
id                 # 用户 ID 和组
sudo !!            # 用 sudo 重跑上一条命令
chmod 755 file     # 修改权限
chown user:group file  # 修改所有者
```

## 包管理

### Debian/Ubuntu
```bash
apt update
apt install <package>
apt remove <package>
apt list --installed
```

### CentOS/RHEL
```bash
yum install <package>
yum remove <package>
systemctl status <service>
```

## 服务管理 (systemd)

```bash
systemctl start <service>
systemctl stop <service>
systemctl restart <service>
systemctl status <service>
systemctl enable <service>   # 开机自启
systemctl disable <service>  # 取消开机自启
```

## 文件操作

```bash
find /path -name "*.log"           # 按名称查找
find /path -size +100M             # 按大小查找
grep -r "keyword" /path            # 递归搜索文本
tar -czf archive.tar.gz /path      # 打包压缩
tar -xzf archive.tar.gz            # 解压
```

## 性能诊断常用组合

```bash
# 快速检查系统状态
echo "=== CPU ===" && uptime && echo "=== 内存 ===" && free -h && echo "=== 磁盘 ===" && df -h && echo "=== 网络 ===" && ss -s
```

## 本项目常用命令

### 项目启动

```bash
# 进入项目目录
cd ai-devops-agent

# 创建并激活虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .\.venv\Scripts\Activate.ps1  # Windows

# 安装依赖
pip install -r requirements.txt

# 启动后端服务
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 启动前端（新终端）
cd frontend
npm install
npm run dev
```

### 项目状态检查

```bash
# 检查后端服务状态
curl http://localhost:8000/health
# 预期返回: {"status": "healthy"}

# 检查前端服务
curl http://localhost:5173/

# 查看后端日志
tail -f app.log

# 查看运行中的进程
ps aux | grep uvicorn
ps aux | grep node
```

### 项目管理

```bash
# 更新代码
git pull origin main

# 查看项目结构
tree -L 3

# 查看依赖版本
pip list | grep -E "fastapi|uvicorn|pydantic"

# 查看前端依赖
cd frontend && npm list --depth=0
```

### 项目调试

```bash
# 查看 API 文档
curl http://localhost:8000/docs

# 测试聊天 API
curl -X POST -H "Content-Type: application/json" -d '{"message":"hello"}' http://localhost:8000/api/chat/

# 查看技能列表
curl http://localhost:8000/api/skills/

# 查看工具列表
curl http://localhost:8000/tools
```
