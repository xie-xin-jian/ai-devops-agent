---
name: python-deploy
description: Python 项目部署指南，涵盖虚拟环境、依赖管理、FastAPI 服务启动等
---

# Python 项目部署指南

## 虚拟环境管理

### 创建虚拟环境
```bash
# Python 3.6+
python -m venv .venv

# 使用 conda
conda create -n devops-agent python=3.10
conda activate devops-agent
```

### 激活虚拟环境

**Linux/macOS:**
```bash
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
.\.venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**
```cmd
.venv\Scripts\activate.bat
```

### 退出虚拟环境
```bash
deactivate
```

## 依赖管理

### 安装依赖
```bash
# 使用 requirements.txt
pip install -r requirements.txt

# 安装特定版本
pip install "fastapi>=0.116" "uvicorn>=0.29"

# 升级 pip
pip install --upgrade pip
```

### 生成依赖文件
```bash
# 生成 requirements.txt
pip freeze > requirements.txt

# 生成带哈希校验的依赖文件
pip freeze --hash > requirements.txt
```

### 常见依赖问题
```bash
# 清理缓存
pip cache purge

# 强制重新安装
pip install --force-reinstall <package>

# 安装开发依赖
pip install -e .
```

## FastAPI 服务启动

### 开发模式启动
```bash
# 自动重载模式（开发用）
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 指定 IP 地址
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

### 生产模式启动
```bash
# 使用多进程
uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 4

# 使用 Gunicorn 作为进程管理器
gunicorn api.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

### 启动参数说明
| 参数 | 说明 |
|------|------|
| `--host` | 绑定的 IP 地址 |
| `--port` | 监听端口 |
| `--reload` | 代码变更自动重启（开发用） |
| `--workers` | 工作进程数（通常设为 CPU 核心数） |
| `--log-level` | 日志级别 (debug/info/warning/error) |

## 项目结构

```
ai-devops-agent/
├── api/
│   ├── __init__.py
│   ├── main.py          # FastAPI 入口
│   └── routes/          # API 路由
│       ├── task.py
│       ├── mcp_route.py
│       └── skill_route.py
├── agent/
│   ├── __init__.py
│   ├── comprehensive.py # 主 Agent 逻辑
│   ├── skill.py         # Skill 系统
│   └── tools/           # 工具模块
│       ├── ops.py       # 运维工具
│       └── ...
├── skills/              # 技能知识库
├── frontend/            # 前端代码
├── requirements.txt     # 依赖列表
└── run.py               # 启动脚本
```

## 启动脚本

创建 `run.py`：
```python
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
```

运行：
```bash
python run.py
```

## 健康检查

```bash
# 检查服务是否正常
curl http://localhost:8000/health
# 预期返回: {"status": "healthy"}

# 查看 API 文档
curl http://localhost:8000/docs
```

## 常见问题

### 端口被占用
```bash
# 查找占用端口的进程
lsof -i :8000  # Linux/macOS
netstat -ano | findstr :8000  # Windows

# 杀死进程
kill -9 <pid>  # Linux/macOS
taskkill /F /PID <pid>  # Windows
```

### 模块导入错误
```bash
# 设置 PYTHONPATH
export PYTHONPATH=/path/to/project:$PYTHONPATH
```

### 权限问题
```bash
# 使用 sudo 运行（不推荐）
sudo python run.py

# 或使用非特权端口（1024以下需要root）
uvicorn api.main:app --port 8080
```

## 本项目快速启动

```bash
# 进入项目目录
cd ai-devops-agent

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .\.venv\Scripts\Activate.ps1  # Windows

# 安装依赖
pip install -r requirements.txt

# 启动后端
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 启动前端（新终端）
cd frontend
npm install
npm run dev
```
