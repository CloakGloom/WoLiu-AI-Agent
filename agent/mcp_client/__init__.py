"""
agent.mcp_client —— MCP 工具管理层

负责:
1. 统一工具发现接口（本地直连 + MCP 服务模块合并）
2. 工具调用路由（直连 execute_tool / 远程 MCP tools/call）
3. MCP 不可用时自动回退

Phase 3: 通过 MCPModuleRegistry 动态发现已安装的服务模块，
         每个模块可独立提供 MCP Server 命令来暴露工具。
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# ── 全局单例 ──
_manager: MCPToolManager | None = None


def get_manager() -> MCPToolManager:
    """获取全局 MCPToolManager 单例"""
    global _manager
    if _manager is None:
        _manager = MCPToolManager()
    return _manager


class MCPToolManager:
    """
    MCP 工具管理器 —— Agent 工具调用的统一入口。

    工具发现优先级:
    1. 本地内置工具 (agent.tools) —— 始终可用
    2. MCP 服务模块 (agent.mcp_modules) —— 按文件夹存在性自动发现, stdio 连接

    call_tool() 自动路由到正确的执行器。
    """

    def __init__(self):
        self._initialized = False
        self._enabled = True
        self._local_tools_llm: list[dict] = []      # OpenAI format for LLM
        self._tool_sources: dict[str, str] = {}      # tool_name → "local" / module_id
        self._remote_tools: dict[str, dict] = {}     # module_id → {tool_name: MCPTool info}
        self._module_configs: dict[str, dict] = {}   # module_id → mcp_command
        self._connector: Any = None                   # MCPConnectorManager

    # ── 初始化 ──

    def initialize(self, enabled: bool = None):
        """初始化工具管理器（同步部分：加载本地 + 模块配置）"""
        if self._initialized:
            return

        if enabled is not None:
            self._enabled = enabled
        else:
            self._enabled = self._read_mcp_enabled()

        self._load_local_tools()

        if self._enabled:
            try:
                self._load_remote_tools()
            except Exception as e:
                print(f"[MCP] 远程工具加载失败，仅使用本地工具: {e}", file=sys.stderr)

        self._initialized = True
        local_count = len(self._local_tools_llm)
        remote_count = sum(len(t) for t in self._remote_tools.values())
        module_count = len(self._module_configs)
        print(f"[MCP] 工具管理器就绪: {local_count + remote_count} 个工具 "
              f"(本地 {local_count}, 远程 {remote_count}) | "
              f"{module_count} 个服务模块", file=sys.stderr)

    async def initialize_async(self):
        """异步初始化：连接所有 MCP Server 并发现工具"""
        self.initialize()

        if not self._module_configs:
            return

        try:
            from agent.mcp_client.connector import MCPConnectorManager
            self._connector = MCPConnectorManager()
            await self._connector.connect_all(self._module_configs)

            # 将发现的工具合并到注册表
            discovered = self._connector.get_tools()
            for tname, (module_id, tinfo) in discovered.items():
                self._remote_tools.setdefault(module_id, {})[tname] = tinfo
                self._tool_sources[tname] = module_id

            print(f"[MCP] 异步连接完成: 发现 {len(discovered)} 个远程工具", file=sys.stderr)
        except Exception as e:
            print(f"[MCP] 异步连接失败: {e}", file=sys.stderr)

    async def shutdown(self):
        """关闭所有 MCP 连接"""
        if self._connector:
            await self._connector.disconnect_all()
            self._connector = None

    def reload(self):
        """重新加载工具列表（工具启用/禁用或模块变更后）"""
        self._initialized = False
        self._local_tools_llm.clear()
        self._tool_sources.clear()
        self._remote_tools.clear()
        self._module_configs.clear()
        self.initialize()

    # ── 工具发现 ──

    def get_tools_for_llm(self) -> list[dict]:
        """
        返回 OpenAI function-calling 格式的工具列表。
        合并本地工具 + MCP 模块远程工具。
        """
        self.initialize()

        tools = list(self._local_tools_llm)

        # 追加远程 MCP 模块工具 (Phase 3: 实际需通过 tools/list 获取)
        for module_id, module_tools in self._remote_tools.items():
            for tname, tinfo in module_tools.items():
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tname,
                        "description": tinfo.get("description", ""),
                        "parameters": tinfo.get("inputSchema", {"type": "object", "properties": {}, "required": []}),
                    },
                })

        return tools

    def list_all_tools(self) -> list[dict]:
        """列出所有工具（含来源元数据）"""
        self.initialize()
        result = []

        from agent.tools import get_tool_registry
        for t in get_tool_registry():
            result.append({
                "name": t["name"],
                "source": "local",
                "tag": t["tag"],
                "schema": t["schema"],
            })

        for module_id, module_tools in self._remote_tools.items():
            for tname, tinfo in module_tools.items():
                result.append({
                    "name": tname,
                    "source": module_id,
                    "tag": "远程",
                    "schema": {
                        "type": "function",
                        "function": {
                            "name": tname,
                            "description": tinfo.get("description", ""),
                            "parameters": tinfo.get("inputSchema", {}),
                        },
                    },
                })

        return result

    def list_modules(self) -> list[dict]:
        """列出所有 MCP 服务模块（供 /api/mcp/modules 使用）"""
        try:
            from agent.mcp_modules import list_modules as _list
            return _list()
        except Exception:
            return []

    def get_module_status(self, module_id: str) -> dict | None:
        """获取指定模块状态"""
        try:
            from agent.mcp_modules import get_module
            mod = get_module(module_id)
            if mod is None:
                return None
            import asyncio
            health = asyncio.run(mod.health())
            return {
                "id": mod.meta.id,
                "name": mod.meta.name,
                "installed": health.installed,
                "running": health.running,
                "port": health.port,
                "has_mcp": mod.get_mcp_command() is not None,
            }
        except Exception:
            return None

    # ── 工具执行 ──

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """
        执行工具。路由到本地或远程 MCP 执行器。
        """
        self.initialize()

        source = self._tool_sources.get(tool_name, "local")

        if source != "local" and self._connector is not None:
            # 异步调用远程 MCP 工具
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            return loop.run_until_complete(
                self._connector.call_tool(source, tool_name, arguments)
            )

        return self._call_local_tool(tool_name, arguments)

    # ── MCP 开关 ──

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self.reload()

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    # ═══════════════════════════════════════════
    #  内部实现
    # ═══════════════════════════════════════════

    def _read_mcp_enabled(self) -> bool:
        try:
            from agent.config import get
            return get("mcp.enabled", True)
        except Exception:
            return True

    def _load_local_tools(self):
        from agent.tools import TOOLS_FOR_LLM, get_tool_registry
        self._local_tools_llm = list(TOOLS_FOR_LLM)
        for entry in get_tool_registry():
            self._tool_sources[entry["name"]] = "local"

    def _load_remote_tools(self):
        """从 MCPModuleRegistry 加载已安装模块的 MCP 配置"""
        try:
            from agent.mcp_modules import get_all_mcp_configs, get_all_direct_tools
        except Exception:
            return

        # 加载模块 MCP 配置
        configs = get_all_mcp_configs()
        self._module_configs = configs

        # Phase 3: 实际连接 MCP Server 并通过 tools/list 发现工具
        # 当前作为 skeleton，展示模块已就绪
        for module_id, cmd in configs.items():
            self._remote_tools.setdefault(module_id, {})
            if module_id not in self._tool_sources:
                pass  # tools/list 结果将在连接后填充

        # 加载模块的直连工具（非 MCP，HTTP 桥接）
        direct_tools = get_all_direct_tools()
        for tool in direct_tools:
            tname = tool.get("function", {}).get("name", "")
            if tname:
                self._tool_sources[tname] = "local"  # 直连工具走本地执行

    @staticmethod
    def _call_local_tool(tool_name: str, arguments: dict) -> str:
        from agent.tools import execute_tool
        return execute_tool(tool_name, arguments)

    @staticmethod
    def _call_remote_tool(module_id: str, tool_name: str, arguments: dict) -> str:
        """远程 MCP 工具调用"""
        return f"MCP 远程工具 {tool_name} (模块={module_id}) 暂未连接"
