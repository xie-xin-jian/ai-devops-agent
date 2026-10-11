#!/usr/bin/env python3
"""
标准 MCP Server - 告警通知服务
使用 MCP 官方 SDK 实现，通过 stdio 与 Agent 通信。
支持钉钉 / 企业微信 / 飞书 群机器人 webhook 真实发送。
webhook 可显式传入，也可从环境变量读取：
  FEISHU_WEBHOOK / DINGTALK_WEBHOOK / WECHAT_WEBHOOK
"""

import os
import json
import urllib.request
import urllib.error
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Alert Notification Service")


def _post_json(url: str, payload: dict, timeout: int = 10) -> str:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return f"[HTTP {e.code}] {e.read().decode('utf-8', 'replace')}"
    except Exception as e:
        return f"[ERROR] {type(e).__name__}: {e}"


@mcp.tool()
def send_feishu(message: str, webhook_url: str = "") -> str:
    """发送飞书群自定义机器人文本消息（真实 HTTP 发送）。

    Args:
        message: 要发送的文本内容
        webhook_url: 飞书机器人 webhook；留空则用环境变量 FEISHU_WEBHOOK
    """
    url = webhook_url or os.environ.get("FEISHU_WEBHOOK", "")
    if not url:
        return "[飞书通知] 未配置 webhook（请传 webhook_url 或设置 FEISHU_WEBHOOK）"
    payload = {"msg_type": "text", "content": {"text": message}}
    resp = _post_json(url, payload)
    return f"[飞书通知] 已发送 -> {resp}"


@mcp.tool()
def send_dingtalk(message: str, webhook_url: str = "") -> str:
    """发送钉钉群文本消息（真实 HTTP 发送）。

    Args:
        message: 要发送的文本内容
        webhook_url: 钉钉机器人 webhook；留空则用环境变量 DINGTALK_WEBHOOK
    """
    url = webhook_url or os.environ.get("DINGTALK_WEBHOOK", "")
    if not url:
        return "[钉钉通知] 未配置 webhook（请传 webhook_url 或设置 DINGTALK_WEBHOOK）"
    payload = {"msgtype": "text", "text": {"content": message}}
    resp = _post_json(url, payload)
    return f"[钉钉通知] 已发送 -> {resp}"


@mcp.tool()
def send_wechat(message: str, webhook_url: str = "") -> str:
    """发送企业微信群文本消息（真实 HTTP 发送）。

    Args:
        message: 要发送的文本内容
        webhook_url: 企业微信机器人 webhook；留空则用环境变量 WECHAT_WEBHOOK
    """
    url = webhook_url or os.environ.get("WECHAT_WEBHOOK", "")
    if not url:
        return "[企业微信通知] 未配置 webhook（请传 webhook_url 或设置 WECHAT_WEBHOOK）"
    payload = {"msgtype": "text", "text": {"content": message}}
    resp = _post_json(url, payload)
    return f"[企业微信通知] 已发送 -> {resp}"


@mcp.tool()
def check_status() -> str:
    """检查告警通知服务状态及已配置的渠道。"""
    channels = []
    if os.environ.get("FEISHU_WEBHOOK"):
        channels.append("飞书")
    if os.environ.get("DINGTALK_WEBHOOK"):
        channels.append("钉钉")
    if os.environ.get("WECHAT_WEBHOOK"):
        channels.append("企业微信")
    return "告警通知服务运行正常，真实发送模式。已配置渠道: " + (", ".join(channels) or "无（需设置 *_WEBHOOK 环境变量）")


if __name__ == "__main__":
    mcp.run()
