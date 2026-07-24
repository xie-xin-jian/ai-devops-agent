---
name: log-monitor
description: 日志管理与系统监控，涵盖日志收集、分析、告警和系统性能监控
---

# 日志管理与系统监控

## 日志基础

### 日志级别

| 级别 | 说明 | 示例 |
|------|------|------|
| DEBUG | 调试信息 | 函数调用、变量值 |
| INFO | 一般信息 | 服务启动、请求处理 |
| WARNING | 警告信息 | 配置缺失、资源不足 |
| ERROR | 错误信息 | 请求失败、异常捕获 |
| CRITICAL | 严重错误 | 服务崩溃、数据丢失 |

### 日志文件位置

```bash
# 系统日志
/var/log/syslog          # Ubuntu/Debian
/var/log/messages        # CentOS/RHEL

# 应用日志
/var/log/nginx/          # Nginx 日志
/var/log/apache2/        # Apache 日志
/var/log/mysql/          # MySQL 日志
/var/log/docker/         # Docker 日志

# systemd 服务日志
journalctl -u <service>
```

## 日志查看工具

### tail

```bash
# 实时跟踪日志
tail -f /var/log/syslog

# 实时跟踪多个文件
tail -f /var/log/nginx/access.log /var/log/nginx/error.log

# 查看最后 N 行
tail -n 100 /var/log/syslog

# 实时跟踪并过滤
tail -f /var/log/syslog | grep "error"
```

### grep

```bash
# 搜索关键词
grep "ERROR" /var/log/syslog

# 忽略大小写
grep -i "error" /var/log/syslog

# 显示上下文
grep -B 5 -A 5 "ERROR" /var/log/syslog

# 递归搜索
grep -r "keyword" /var/log/

# 统计匹配行数
grep -c "ERROR" /var/log/syslog
```

### awk

```bash
# 提取特定字段
awk '{print $1, $4, $7}' /var/log/nginx/access.log

# 统计访问量
awk '{count[$1]++} END {for (ip in count) print ip, count[ip]}' /var/log/nginx/access.log

# 计算平均响应时间
awk '{sum+=$NF} END {print sum/NR}' /var/log/nginx/access.log
```

### sed

```bash
# 删除空行
sed '/^$/d' /var/log/syslog

# 替换文本
sed 's/ERROR/WARNING/g' /var/log/syslog

# 提取特定行范围
sed -n '100,200p' /var/log/syslog
```

## 日志分析

### 统计分析

```bash
# 统计错误数量（按时间）
grep "ERROR" /var/log/syslog | awk '{print $1, $2}' | uniq -c | sort -rn

# 统计访问最多的 IP
awk '{print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -10

# 统计 HTTP 状态码
awk '{print $9}' /var/log/nginx/access.log | sort | uniq -c | sort -rn

# 找出响应最慢的请求
awk '{print $7, $NF}' /var/log/nginx/access.log | sort -k2nr | head -10
```

### 实时监控

```bash
# 实时错误监控
tail -f /var/log/syslog | grep --line-buffered "ERROR"

# 实时请求监控
tail -f /var/log/nginx/access.log | awk '{print strftime("[%Y-%m-%d %H:%M:%S]"), $1, $7, $9, $NF}'
```

## 日志轮转

### logrotate 配置

创建 `/etc/logrotate.d/devops-agent`：

```
/var/log/devops-agent/app.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 640 devops devops
    postrotate
        systemctl reload devops-agent > /dev/null 2>&1 || true
    endscript
}
```

### 手动执行

```bash
# 测试配置
logrotate -d /etc/logrotate.d/devops-agent

# 强制执行
logrotate -f /etc/logrotate.d/devops-agent

# 查看状态
cat /var/lib/logrotate/status
```

## 系统监控

### CPU 监控

```bash
# 实时监控
top

# 增强版
htop

# CPU 使用率统计
mpstat 1 5

# 每个 CPU 核的使用情况
mpstat -P ALL 1
```

### 内存监控

```bash
# 内存使用情况
free -h

# 虚拟内存统计
vmstat 1 5

# 内存使用详细信息
cat /proc/meminfo
```

### 磁盘监控

```bash
# 磁盘空间
df -h

# 磁盘 I/O
iostat -x 1 5

# 目录大小
du -sh /var/log/

# 大文件查找
find /var/log -type f -size +100M

# 交互式磁盘分析
ncdu /var/log/
```

### 网络监控

```bash
# 网络连接统计
ss -s

# 监听端口
ss -tlnp

# 实时网络流量
iftop

# 按进程统计流量
nethogs

# 网络接口信息
ip addr show
```

### 进程监控

```bash
# 进程资源使用
ps aux --sort=-%cpu | head -10

# 进程树
pstree -p

# 进程打开的文件
lsof -p <pid>

# 进程端口占用
lsof -i :8000
```

## 告警配置

### 简单告警脚本

```bash
#!/bin/bash

LOG_FILE="/var/log/devops-agent/app.log"
ERROR_COUNT=$(grep -c "ERROR" "$LOG_FILE")

if [ $ERROR_COUNT -gt 10 ]; then
    echo "高错误率告警: 发现 $ERROR_COUNT 个错误" | mail -s "DevOps Agent 告警" admin@example.com
fi
```

### 定时检查

配置 `crontab -e`：

```bash
# 每小时检查一次错误日志
0 * * * * /opt/ai-devops-agent/scripts/check_errors.sh

# 每天凌晨清理日志
0 0 * * * /usr/sbin/logrotate /etc/logrotate.d/devops-agent
```

## 监控工具

### Prometheus + Grafana

**安装 Prometheus:**
```bash
sudo apt install prometheus
```

**配置 Prometheus (`/etc/prometheus/prometheus.yml`):**
```yaml
scrape_configs:
  - job_name: 'devops-agent'
    static_configs:
      - targets: ['localhost:8000']
```

**启动服务:**
```bash
sudo systemctl start prometheus
sudo systemctl enable prometheus
```

### 使用 Python 进行监控

```python
import subprocess
import time

def check_service():
    result = subprocess.run(
        ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}', 'http://localhost:8000/health'],
        capture_output=True, text=True
    )
    return result.stdout == '200'

if __name__ == '__main__':
    while True:
        if not check_service():
            print("Service is down!")
        time.sleep(60)
```

## 本项目日志管理

### 日志配置

在 `api/main.py` 中添加日志配置：

```python
import logging
from logging.handlers import RotatingFileHandler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            'app.log',
            maxBytes=1024 * 1024 * 10,  # 10MB
            backupCount=5
        ),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)
```

### 日志查看命令

```bash
# 查看后端日志
tail -f app.log

# 查看前端日志（开发模式）
cd frontend && npm run dev  # 日志输出到终端

# 查看 systemd 服务日志
sudo journalctl -u devops-agent -f

# 搜索错误
grep "ERROR" app.log

# 统计请求量
grep "POST /api/chat/" app.log | wc -l
```

## 问题排查流程

```
1. 查看服务状态
   systemctl status devops-agent

2. 查看日志
   journalctl -u devops-agent -f

3. 检查端口
   ss -tlnp | grep :8000

4. 检查资源
   free -h && df -h && top -bn1 | head -5

5. 检查网络
   curl http://localhost:8000/health
   ping google.com

6. 检查依赖
   pip list | grep fastapi
```
