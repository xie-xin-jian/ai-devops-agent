#!/usr/bin/env python3
"""用大白话报告持久化状态，不需要看懂各项指标。

用法（后端在跑的时候）：

    python scripts/persistence_health.py

它会去问一次 http://127.0.0.1:8000/health，然后报告数据库是否可用。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _use_utf8_output() -> None:
    """让中文在任何 Windows 控制台上都能正常显示。

    默认情况下 Python 在管道/重定向时用系统本地编码输出，中文会变成乱码。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                continue


def _fetch(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _line(label: str, text: str) -> str:
    return f"{label:<12}{text}"


def report(payload: dict) -> tuple[list[str], bool]:
    persistence = payload.get("persistence") or {}
    ok = bool(persistence.get("database_reachable"))
    lines = [
        _line("数据库地址", "已配置" if persistence.get("database_url_configured") else "未配置"),
        _line("数据库类型", str(persistence.get("dialect") or "未知")),
        _line(
            "数据库状态",
            "连接正常" if ok else str(persistence.get("database_status") or "不可用"),
        ),
        "",
        "结论：" + ("数据库正常。" if ok else "数据库不可用，应用无法读写业务数据。"),
    ]
    return lines, ok


def main() -> int:
    _use_utf8_output()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000/health",
        help="后端健康检查地址",
    )
    args = parser.parse_args()

    try:
        payload = _fetch(args.url)
    except (urllib.error.URLError, TimeoutError, OSError):
        print("后端没在运行（或者端口不是 8000）。")
        print("先启动后端，再运行这个脚本。")
        return 1
    except json.JSONDecodeError:
        print("后端返回的内容看不懂，可能版本不匹配。")
        return 1

    lines, ok = report(payload)
    for line in lines:
        print(line)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
