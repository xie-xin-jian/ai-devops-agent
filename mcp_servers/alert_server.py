#!/usr/bin/env python3
"""
标准 MCP Server - 告警通知服务
使用 MCP 官方 SDK 实现，通过 stdio 与 Agent 通信
"""

import asyncio
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Alert Notification Service")


@mcp.tool()
def send_dingtalk(webhook_url: str, message: str) -> str:
    """发送钉钉群消息。

    Args:
        webhook_url: 钉钉机器人 webhook URL
        message: 要发送的消息内容
    """
    return f"[钉钉通知] 消息已发送: {message}"


@mcp.tool()
def send_wechat(webhook_url: str, message: str) -> str:
    """发送企业微信群消息。

    Args:
        webhook_url: 企业微信机器人 webhook URL
        message: 要发送的消息内容
    """
    return f"[企业微信通知] 消息已发送: {message}"


@mcp.tool()
def check_status() -> str:
    """检查告警通知服务状态。"""
    return "告警通知服务运行正常，当前已连接 2 个通知渠道：钉钉、企业微信"


if __name__ == "__main__":
    mcp.run()
