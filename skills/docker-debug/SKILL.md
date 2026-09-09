---
name: docker-debug
description: Docker 容器排错指南，包含容器状态检查、日志查看、资源限制等
---

# Docker 容器排错指南

## 容器状态检查

### 列出容器
```bash
docker ps                    # 运行中的容器
docker ps -a                 # 所有容器（包括停止的）
docker ps -q                 # 只显示容器 ID
```

### 容器详情
```bash
docker inspect <container>   # 容器详细信息（JSON）
docker stats <container>     # 实时资源使用
docker top <container>       # 容器内的进程
```

## 日志查看

```bash
docker logs <container>              # 查看日志
docker logs -f <container>           # 实时跟踪日志
docker logs --tail 100 <container>   # 最后 100 行
docker logs --since 1h <container>   # 最近 1 小时
```

## 进入容器调试

```bash
docker exec -it <container> bash     # 进入容器（bash）
docker exec -it <container> sh       # 进入容器（sh，alpine 等）
docker exec <container> <command>    # 在容器内执行命令
```

## 常见问题排查

### 容器启动后立即退出
**排查步骤**：
1. 查看日志：`docker logs <container>`
2. 查看退出码：`docker inspect <container> | grep ExitCode`
3. 常见原因：
   - 主进程配置错误导致崩溃
   - 前台进程没有保持运行
   - 配置文件不存在或路径错误

### 容器无法访问外部网络
**排查步骤**：
1. 进入容器测试：`docker exec -it <container> ping 8.8.8.8`
2. 检查 DNS：`docker exec -it <container> cat /etc/resolv.conf`
3. 检查网桥：`docker network ls`
4. 重启 Docker：`systemctl restart docker`

### 端口映射不生效
**排查步骤**：
1. 查看端口映射：`docker port <container>`
2. 检查宿主机监听：`ss -tlnp | grep <port>`
3. 确认容器内服务是否监听 0.0.0.0 而不是 127.0.0.1
4. 检查防火墙规则

### 容器磁盘空间不足
**排查步骤**：
1. 查看容器大小：`docker ps -s`
2. 查看镜像大小：`docker images`
3. 清理无用资源：
   ```bash
   docker system prune        # 清理停止的容器、悬挂镜像等
   docker system prune -a     # 更彻底的清理
   docker volume prune        # 清理未使用的卷
   ```

## 资源限制

### 查看资源使用
```bash
docker stats                  # 所有容器的实时资源
docker stats <container>      # 特定容器
```

### 限制资源
```bash
# 启动时限制
docker run --memory 1g --cpus 1 <image>
# 更新运行中容器的限制
docker update --memory 2g <container>
```

## 镜像管理

```bash
docker images                 # 列出本地镜像
docker pull <image>           # 拉取镜像
docker rmi <image>            # 删除镜像
docker build -t name .        # 构建镜像
```

## Docker Compose

```bash
docker compose up -d          # 后台启动
docker compose down           # 停止并删除
docker compose logs -f        # 实时日志
docker compose ps             # 查看状态
docker compose restart        # 重启所有服务
```

## 快速诊断脚本

```bash
# 一键检查 Docker 状态
echo "=== Docker 服务状态 ===" && systemctl status docker | head -5 && echo "=== 运行中容器 ===" && docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" && echo "=== 资源使用 ===" && docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"
```
