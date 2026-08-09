"""
agent.mcp_client.server_manager —— MCP 子进程生命周期管理

Phase 3 实现:
- 启动/停止外部 MCP Server 进程 (stdio / SSE)
- 健康检查 + 自动重启
- 工具发现与冲突解决

Phase 2: skeleton，不影响现有功能。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import logging
from dataclasses import dataclass, field

logger = logging.getLogger("mcp.server_manager")


@dataclass
class MCPServerConfig:
    """外部 MCP Server 配置"""
    id: str
    command: str
    args: list[str] = field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    startup_timeout: float = 30.0
    restart_on_failure: bool = True
    max_restarts: int = 3
    description: str = ""


class MCPServerManager:
    """
    MCP Server 进程生命周期管理器 (Phase 3)

    职责:
    - 从 config/mcp.json 加载配置
    - 启动 stdio/SSE 子进程
    - 工具发现 (tools/list)
    - 健康检查 + 崩溃重启
    """

    def __init__(self):
        self._configs: dict[str, MCPServerConfig] = {}
        self._sessions: dict[str, Any] = {}
        self._tools: dict[str, dict] = {}  # server_id → {tool_name: info}
        self._restart_counts: dict[str, int] = {}

    def load_config(self, config_path: str | None = None):
        """从 mcp.json 加载 MCP Server 配置"""
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "config", "mcp.json",
            )

        if not os.path.exists(config_path):
            logger.info("mcp.json not found, no external MCP servers configured")
            return

        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for server_id, cfg in data.get("mcpServers", {}).items():
            if server_id == "ai-agent-local":
                continue  # 内置工具，跳过

            self._configs[server_id] = MCPServerConfig(
                id=server_id,
                command=cfg.get("command", ""),
                args=cfg.get("args", []),
                cwd=cfg.get("cwd"),
                env=cfg.get("env", {}),
                enabled=cfg.get("enabled", True),
                startup_timeout=cfg.get("startupTimeout", 30.0) / 1000.0,
                description=cfg.get("description", ""),
            )

        logger.info(f"Loaded {len(self._configs)} external MCP server configs")

    async def start_all(self) -> dict[str, bool]:
        """启动所有启用的 MCP Server (Phase 3 实现)"""
        results = {}
        for server_id, config in self._configs.items():
            if not config.enabled:
                continue
            # Phase 3: 实际连接逻辑
            # result = await self._start_server(config)
            # results[server_id] = result
            results[server_id] = False  # skeleton
        return results

    async def stop_all(self):
        """停止所有 MCP Server"""
        for server_id in list(self._sessions.keys()):
            # Phase 3: 实际断开逻辑
            pass

    def get_tools(self) -> dict[str, dict]:
        """获取所有远程 MCP Server 发现的工具"""
        return dict(self._tools)
