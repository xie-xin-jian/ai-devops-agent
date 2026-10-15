"""
运维专用工具集 - 服务状态、磁盘、容器、系统资源、网络、日志检查

注意：这些工具在 Linux 上才能正常工作。Windows 环境下会返回错误信息，
但不会抛异常，保证 Agent 循环不被中断。
"""

import subprocess
import shutil
import os
import platform
import string
import ctypes

# 命令超时时间（秒）
_TIMEOUT = 15


def _run_cmd(cmd: list[str]) -> str:
    """通用命令执行辅助函数。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
        out = (r.stdout + r.stderr).strip()
        return out[:5000] if out else "(no output)"
    except FileNotFoundError:
        return f"Error: '{cmd[0]}' not available (non-Linux environment or not installed)"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out ({_TIMEOUT}s)"


# ═══════════════════════════════════════════════════════════
# 原有工具
# ═══════════════════════════════════════════════════════════

def run_service_status(service: str) -> str:
    """检查 systemd 服务状态。

    Args:
        service: 服务名，如 nginx、docker、sshd
    """
    if not service or not service.strip():
        return "Error: service name is required"
    return _run_cmd(["systemctl", "status", service.strip()])


def run_disk_usage() -> str:
    """检查磁盘空间使用情况（df -h）。"""
    if os.name == "nt":
        lines = ["Filesystem        Size        Used       Free      Use%"]
        for drive in string.ascii_uppercase:
            root = f"{drive}:\\"
            if not os.path.exists(root):
                continue
            usage = shutil.disk_usage(root)
            percent = (
                usage.used / usage.total * 100
                if usage.total
                else 0
            )
            lines.append(
                f"{root:<12} "
                f"{format_bytes(usage.total):>10} "
                f"{format_bytes(usage.used):>10} "
                f"{format_bytes(usage.free):>10} "
                f"{percent:>7.1f}%"
            )
        return "\n".join(lines)
    return _run_cmd(["df", "-h"])


# ═══════════════════════════════════════════════════════════
# 新增：系统信息类
# ═══════════════════════════════════════════════════════════

def run_system_info() -> str:
    """获取系统基本信息（uptime、uname、load average）。"""
    if os.name == "nt":
        uname = platform.uname()
        return "\n".join([
            "=== System ===",
            f"Platform: {platform.platform()}",
            f"Machine: {uname.machine}",
            f"Processor: {platform.processor() or uname.processor}",
            f"Python: {platform.python_version()}",
            "",
            "=== Boot / Load ===",
            f"CPU logical cores: {os.cpu_count() or 0}",
        ])
    parts = []
    # uptime
    uptime = _run_cmd(["uptime"])
    parts.append(f"=== Uptime ===\n{uptime}")
    # uname
    uname = _run_cmd(["uname", "-a"])
    parts.append(f"=== Kernel ===\n{uname}")
    # 发行版信息
    os_info = _run_cmd(["cat", "/etc/os-release"])
    if not os_info.startswith("Error"):
        parts.append(f"=== OS ===\n{os_info}")
    return "\n\n".join(parts)[:5000]


def run_memory_usage() -> str:
    """检查内存使用情况（free -h）。"""
    if os.name == "nt":
        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(
            ctypes.byref(status)
        ):
            return "Error: unable to read Windows memory status"
        used = status.ullTotalPhys - status.ullAvailPhys
        return "\n".join([
            "              total        used        free      used%",
            f"Mem:    {format_bytes(status.ullTotalPhys):>12} "
            f"{format_bytes(used):>12} "
            f"{format_bytes(status.ullAvailPhys):>12} "
            f"{status.dwMemoryLoad:>8}%",
        ])
    return _run_cmd(["free", "-h"])


def run_cpu_usage() -> str:
    """检查 CPU 使用情况（top 快照）。"""
    if os.name == "nt":
        result = _run_cmd(
            ["wmic", "cpu", "get", "loadpercentage", "/value"]
        )
        if not result.startswith("Error"):
            values = [
                line.split("=", 1)[1].strip()
                for line in result.splitlines()
                if line.lower().startswith("loadpercentage=")
            ]
            values = [value for value in values if value]
            if values:
                return "CPU load (%): " + ", ".join(values)
        result = _run_cmd([
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "(Get-CimInstance Win32_Processor | "
                "Measure-Object -Property LoadPercentage -Average).Average"
            ),
        ])
        if not result.startswith("Error") and result not in {"", "(no output)"}:
            return f"CPU load (%): {result}"
        return (
            f"CPU logical cores: {os.cpu_count() or 0}\n"
            "Detailed CPU percentage is unavailable on this Windows system."
        )
    # mpstat 优先，更精确
    mpstat = shutil.which("mpstat")
    if mpstat:
        return _run_cmd(["mpstat", "-P", "ALL", "1", "1"])
    # fallback 到 top
    return _run_cmd(["top", "-bn1"])


def format_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TiB"


# ═══════════════════════════════════════════════════════════
# 新增：进程类
# ═══════════════════════════════════════════════════════════

def run_process_top(limit: int = 20) -> str:
    """列出 CPU/内存占用最高的进程。

    Args:
        limit: 返回进程数量，默认 20
    """
    n = max(1, min(limit, 50))
    return _run_cmd([
        "sh",
        "-c",
        f"ps aux --sort=-%cpu --no-headers | head -n {n}",
    ])


def run_process_search(name: str) -> str:
    """按名称搜索进程（pgrep + ps）。

    Args:
        name: 进程名关键词，如 nginx、python
    """
    if not name or not name.strip():
        return "Error: process name is required"
    return _run_cmd(["pgrep", "-a", "-f", name.strip()])


# ═══════════════════════════════════════════════════════════
# 新增：网络类
# ═══════════════════════════════════════════════════════════

def run_network_interfaces() -> str:
    """查看网络接口配置（ip addr）。"""
    ip = shutil.which("ip")
    if ip:
        return _run_cmd(["ip", "addr"])
    return _run_cmd(["ifconfig"])


def run_port_listen() -> str:
    """查看当前监听端口（ss -tlnp）。"""
    ss = shutil.which("ss")
    if ss:
        return _run_cmd(["ss", "-tlnp"])
    return _run_cmd(["netstat", "-tlnp"])


def run_ping_host(host: str, count: int = 4) -> str:
    """Ping 测试网络连通性。

    Args:
        host: 目标主机，如 8.8.8.8、baidu.com
        count: 发送包数，默认 4
    """
    if not host or not host.strip():
        return "Error: host is required"
    c = max(1, min(count, 10))
    return _run_cmd(["ping", "-c", str(c), host.strip()])


def run_http_check(url: str, timeout: int = 10) -> str:
    """HTTP 健康检查：返回状态码、响应耗时和正文摘要。

    Args:
        url: 目标 URL，如 http://127.0.0.1:8000/health
        timeout: 超时秒数，默认 10，最大 30
    """
    import time
    import urllib.error
    import urllib.request

    if not url or not url.strip():
        return "Error: url is required"
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    t = max(1, min(int(timeout or 10), 30))
    start = time.monotonic()
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "ai-devops-agent"}
        )
        with urllib.request.urlopen(req, timeout=t) as resp:
            body = resp.read(2048).decode("utf-8", "replace")
            elapsed = time.monotonic() - start
            return f"HTTP {resp.status} ({elapsed:.2f}s)\n{body[:500]}"
    except urllib.error.HTTPError as exc:
        elapsed = time.monotonic() - start
        detail = exc.read(500).decode("utf-8", "replace")
        return f"HTTP {exc.code} ({elapsed:.2f}s)\n{detail}"
    except Exception as exc:
        return f"Error: {exc}"


# ═══════════════════════════════════════════════════════════
# 新增：磁盘 IO
# ═══════════════════════════════════════════════════════════

def run_disk_io() -> str:
    """查看磁盘 IO 情况（iostat 或 vmstat）。"""
    iostat = shutil.which("iostat")
    if iostat:
        return _run_cmd(["iostat", "-x", "1", "2"])
    return _run_cmd(["vmstat", "-d"])


# ═══════════════════════════════════════════════════════════
# 新增：日志类
# ═══════════════════════════════════════════════════════════

def run_system_logs(service: str = "", lines: int = 50) -> str:
    """查看系统日志（journalctl）。

    Args:
        service: 指定服务名查看该服务日志，空字符串查看系统日志
        lines: 查看最近多少行，默认 50，最大 200
    """
    n = max(1, min(lines, 200))
    cmd = ["journalctl", "--no-pager", "-n", str(n)]
    if service and service.strip():
        cmd.extend(["-u", service.strip()])
    return _run_cmd(cmd)


# ═══════════════════════════════════════════════════════════
# 工具 Schema（告诉 LLM 工具长什么样）
# ═══════════════════════════════════════════════════════════

# ── 原有 ──
SERVICE_STATUS_SCHEMA = {
    "name": "service_status",
    "description": "Check systemd service status (e.g. nginx, docker, sshd). Use this to diagnose service failures.",
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "Service name, e.g. 'nginx', 'docker', 'sshd'",
            },
        },
        "required": ["service"],
    },
}

DISK_USAGE_SCHEMA = {
    "name": "disk_usage",
    "description": "Check disk space usage across all mounts (df -h). Use this for routine inspection or when disk full errors occur.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

# ── 系统信息 ──
SYSTEM_INFO_SCHEMA = {
    "name": "system_info",
    "description": "Get system basic info: uptime, kernel version, OS release. Use this for quick system overview.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

MEMORY_USAGE_SCHEMA = {
    "name": "memory_usage",
    "description": "Check memory usage (free -h). Use this when OOM or memory leak is suspected.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

CPU_USAGE_SCHEMA = {
    "name": "cpu_usage",
    "description": "Check CPU usage (mpstat or top). Use this when system is slow or CPU bound.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

# ── 进程 ──
PROCESS_TOP_SCHEMA = {
    "name": "process_top",
    "description": "List top processes sorted by CPU usage (ps aux). Use this to find resource-hungry processes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Number of processes to return (1-50, default 20)",
            },
        },
        "required": [],
    },
}

PROCESS_SEARCH_SCHEMA = {
    "name": "process_search",
    "description": "Search processes by name (pgrep). Use this to check if a specific process is running.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Process name keyword, e.g. 'nginx', 'python', 'java'",
            },
        },
        "required": ["name"],
    },
}

# ── 网络 ──
NETWORK_INTERFACES_SCHEMA = {
    "name": "network_interfaces",
    "description": "Show network interface configuration (ip addr). Use this to check IP, subnet, interface status.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

PORT_LISTEN_SCHEMA = {
    "name": "port_listen",
    "description": "Show listening ports (ss -tlnp). Use this to check which services are listening on which ports.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

PING_HOST_SCHEMA = {
    "name": "ping_host",
    "description": "Ping a host to test network connectivity. Use this to diagnose network issues.",
    "input_schema": {
        "type": "object",
        "properties": {
            "host": {
                "type": "string",
                "description": "Target host, e.g. '8.8.8.8', 'baidu.com', 'github.com'",
            },
            "count": {
                "type": "integer",
                "description": "Number of packets (1-10, default 4)",
            },
        },
        "required": ["host"],
    },
}

# ── HTTP 检查 ──
HTTP_CHECK_SCHEMA = {
    "name": "http_check",
    "description": "Check an HTTP endpoint: returns status code and latency. Use this for health checks instead of curl via bash.",
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Target URL, e.g. 'http://127.0.0.1:8000/health'",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout seconds (1-30, default 10)",
            },
        },
        "required": ["url"],
    },
}

# ── 磁盘 IO ──
DISK_IO_SCHEMA = {
    "name": "disk_io",
    "description": "Check disk IO statistics (iostat or vmstat). Use this when disk performance is a bottleneck.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

# ── 日志 ──
SYSTEM_LOGS_SCHEMA = {
    "name": "system_logs",
    "description": "View system logs (journalctl). Use this to diagnose service crashes or system errors.",
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "Service name to filter logs, e.g. 'nginx', 'docker'. Leave empty for all system logs.",
            },
            "lines": {
                "type": "integer",
                "description": "Number of recent lines (1-200, default 50)",
            },
        },
        "required": [],
    },
}

OPS_TOOL_SCHEMAS = [
    SERVICE_STATUS_SCHEMA,
    DISK_USAGE_SCHEMA,
    SYSTEM_INFO_SCHEMA,
    MEMORY_USAGE_SCHEMA,
    CPU_USAGE_SCHEMA,
    PROCESS_TOP_SCHEMA,
    PROCESS_SEARCH_SCHEMA,
    NETWORK_INTERFACES_SCHEMA,
    PORT_LISTEN_SCHEMA,
    PING_HOST_SCHEMA,
    HTTP_CHECK_SCHEMA,
    DISK_IO_SCHEMA,
    SYSTEM_LOGS_SCHEMA,
]

OPS_TOOL_HANDLERS = {
    "service_status": run_service_status,
    "disk_usage": run_disk_usage,
    "system_info": run_system_info,
    "memory_usage": run_memory_usage,
    "cpu_usage": run_cpu_usage,
    "process_top": run_process_top,
    "process_search": run_process_search,
    "network_interfaces": run_network_interfaces,
    "port_listen": run_port_listen,
    "ping_host": run_ping_host,
    "http_check": run_http_check,
    "disk_io": run_disk_io,
    "system_logs": run_system_logs,
}
