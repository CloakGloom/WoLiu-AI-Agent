"""
agent.mcp_server —— AI Agent 本地 MCP Server

将现有 tool (SCHEMA + execute) 暴露为 MCP 标准工具。
支持 stdio / SSE 两种传输模式。
"""

from agent.mcp_server.server import mcp, register_all_tools, main

__all__ = ["mcp", "register_all_tools", "main"]
