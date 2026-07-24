---
name: nginx-troubleshooting
description: Nginx 故障排查指南，包含常见错误码分析和定位步骤
---

# Nginx 故障排查指南

## 常用诊断命令

### 检查 Nginx 状态
```bash
systemctl status nginx
nginx -t  # 检查配置文件语法
```

### 查看错误日志
```bash
tail -f /var/log/nginx/error.log
tail -f /var/log/nginx/access.log
```

### 查看进程和端口
```bash
ps aux | grep nginx
ss -tlnp | grep :80
ss -tlnp | grep :443
```

## 常见错误码排查

### 502 Bad Gateway
**原因**：Nginx 无法连接到上游服务器（如 PHP-FPM、Node.js、Tomcat 等）

**排查步骤**：
1. 检查上游服务是否运行：`systemctl status php-fpm` 或 `ps aux | grep node`
2. 检查上游端口是否监听：`ss -tlnp | grep 9000`
3. 检查 Nginx 配置中的 proxy_pass 或 fastcgi_pass 地址是否正确
4. 查看上游服务的日志
5. 检查防火墙是否拦截了本地端口

### 503 Service Unavailable
**原因**：服务暂时不可用，可能是后端过载或维护中

**排查步骤**：
1. 检查后端服务是否正常运行
2. 查看系统负载：`top` 或 `uptime`
3. 检查连接数：`ss -s`
4. 查看 Nginx 连接数：`grep 'active connections' /var/log/nginx/access.log | wc -l`

### 504 Gateway Timeout
**原因**：上游服务器响应超时

**排查步骤**：
1. 检查上游服务是否卡死
2. 增加超时时间配置：
   ```nginx
   proxy_connect_timeout 60s;
   proxy_read_timeout 120s;
   ```
3. 查看上游服务是否有性能问题

### 403 Forbidden
**原因**：权限不足或目录索引被禁止

**排查步骤**：
1. 检查文件/目录权限：`ls -la /path/to/webroot`
2. 确保 Nginx 用户（通常是 www-data 或 nginx）有读取权限
3. 检查是否配置了 `autoindex on`（如需目录浏览）
4. 检查 index 文件是否存在

### 404 Not Found
**原因**：请求的资源不存在

**排查步骤**：
1. 检查 root 或 alias 配置是否正确
2. 确认文件确实存在于指定路径
3. 检查 try_files 配置

## 配置热重载
```bash
nginx -s reload  # 优雅重载，不中断服务
nginx -s reopen  # 重新打开日志文件
```

## 性能调优建议

1. **worker_processes**：设置为 CPU 核心数
2. **worker_connections**：调高到 65535
3. **gzip**：开启压缩减少传输量
4. **静态文件缓存**：设置合适的 expires 头
