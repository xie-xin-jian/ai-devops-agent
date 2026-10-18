#!/usr/bin/env python3
"""用大白话报告持久化状态，不需要看懂各项指标。

用法（后端在跑的时候）：

    python scripts/persistence_health.py

它会去问一次 http://127.0.0.1:8000/health，然后把结果翻译成：
双写有没有开、有没有写失败、读的是哪一边、自动比对有没有发现差异。
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
    mirror = persistence.get("mirror") or {}
    totals = mirror.get("totals") or {}

    calls = int(totals.get("calls") or 0)
    failures = int(totals.get("failures") or 0)
    skipped = int(totals.get("skipped") or 0)
    deferred = int(totals.get("deferred") or 0)
    backend = persistence.get("backend", "未知")
    read_mode = persistence.get("read_mode", "未知")
    shadow_checks = int(persistence.get("shadow_checks") or 0)
    shadow_mismatches = int(persistence.get("shadow_mismatches") or 0)

    lines = []
    ok = True

    if mirror.get("enabled"):
        lines.append(_line("双写", "已开启（同一份数据同时写本地文件和 PostgreSQL）"))
    else:
        lines.append(_line("双写", f"未开启（当前后端={backend}，只写本地文件）"))

    if failures:
        lines.append(_line(
            "写入失败",
            f"有 {failures} 次没写进 PostgreSQL，需要查看日志",
        ))
        ok = False
    else:
        lines.append(_line(
            "写入失败",
            f"0 次（累计写入尝试 {calls} 次，其中 {skipped} 次是数据本身不合格被跳过）",
        ))

    if deferred:
        lines.append(_line(
            "暂停写入",
            f"{deferred} 次因数据库刚失败而跳过（这些数据只在本地，需要补写）",
        ))
        ok = False
    if mirror.get("circuit_open"):
        lines.append(_line(
            "数据库状态",
            "刚才连接失败，暂时不再尝试（恢复后会自动继续，可运行补写脚本）",
        ))

    if read_mode == "postgres":
        postgres_domains = persistence.get("postgres_reads") or []
        lines.append(_line(
            "读数据来源",
            f"PostgreSQL（{len(postgres_domains)} 个模块已切换：{'、'.join(postgres_domains) or '无'}）",
        ))
    else:
        lines.append(_line("读数据来源", "本地文件（还没切换，正常）"))

    if shadow_checks:
        if shadow_mismatches:
            lines.append(_line(
                "自动比对",
                f"比对 {shadow_checks} 次，发现 {shadow_mismatches} 次两边不一致，需要处理",
            ))
            ok = False
        else:
            lines.append(_line(
                "自动比对",
                f"比对 {shadow_checks} 次，两边完全一致",
            ))
    else:
        lines.append(_line(
            "自动比对",
            "还没开始（等切换读取之后才会比对，现在正常）",
        ))

    lines.append("")
    lines.append("结论：" + ("一切正常，可以继续这样跑。" if ok else "发现问题，把上面内容发给我。"))
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
