"""
agent.mcp_client.connector —— MCP stdio 子进程连接器

负责:
1. 通过 stdio 启动 MCP Server 子进程
2. 发送 initialize 握手
3. 调用 tools/list 发现工具
4. 调用 tools/call 执行工具
5. 健康检查（ping）与自动重连
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import subprocess
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("mcp.connector")


@dataclass
class MCPServerConnection:
    """与一个 MCP Server 的连接状态"""

    module_id: str
    config: dict                              # {"command": ..., "args": ..., "cwd": ..., "env": ...}
    process: asyncio.subprocess.Process | None = None
    session: Any = None                       # mcp.ClientSession
    tools: dict[str, dict] = field(default_factory=dict)  # tool_name → MCP tool info
    connected: bool = False
    last_error: str = ""


class MCPConnectorManager:
    """
    MCP 子进程连接管理器。

    管理所有外部 MCP Server 的 stdio 连接，
    负责 connect → tools/list → tools/call 的完整生命周期。
    """

    def __init__(self):
        self._connections: dict[str, MCPServerConnection] = {}
        self._main_loop: asyncio.AbstractEventLoop | None = None

    async def connect_all(self, module_configs: dict[str, dict]) -> int:
        """连接所有 MCP 模块。返回成功连接数。"""
        # 获取当前事件循环引用
        self._main_loop = asyncio.get_running_loop()

        connected = 0
        for module_id, config in module_configs.items():
            if await self.connect(module_id, config):
                connected += 1

        logger.info(f"MCP 连接器: {connected}/{len(module_configs)} 个模块已连接")
        return connected

    async def connect(self, module_id: str, config: dict) -> bool:
        """连接一个 MCP Module 并发现工具"""
        conn = MCPServerConnection(module_id=module_id, config=config)
        self._connections[module_id] = conn

        try:
            # 1. 启动子进程
            env = {**os.environ, **config.get("env", {})}
            cwd = config.get("cwd")
            command = [config["command"]] + config.get("args", [])

            conn.process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            # 2. MCP 握手：initialize
            init_msg = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "AI-Agent",
                        "version": "3.0.0",
                    },
                },
            }
            response = await self._send_jsonrpc(conn, init_msg, timeout=15)
            if response is None:
                conn.last_error = "初始化握手超时"
                return False

            server_info = response.get("result", {}).get("serverInfo", {})
            logger.info(f"MCP [{module_id}]: {server_info.get('name', '?')} v{server_info.get('version', '?')}")

            # 3. 发送 initialized 通知
            notified = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
            await self._send_jsonrpc(conn, notified, expect_response=False)

            # 4. 发现工具：tools/list
            tools_resp = await self._send_jsonrpc(conn, {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            }, timeout=10)
            if tools_resp is not None:
                tool_list = tools_resp.get("result", {}).get("tools", [])
                for tool in tool_list:
                    tname = tool.get("name", "")
                    conn.tools[tname] = tool
                logger.info(f"MCP [{module_id}]: 发现 {len(conn.tools)} 个工具: {list(conn.tools.keys())}")

            conn.connected = True
            return True

        except FileNotFoundError as e:
            conn.last_error = f"可执行文件未找到: {e}"
            logger.warning(f"MCP [{module_id}]: {conn.last_error}")
            return False
        except Exception as e:
            conn.last_error = str(e)
            logger.warning(f"MCP [{module_id}]: 连接失败: {e}")
            return False

    async def disconnect(self, module_id: str):
        """断开 MCP 连接"""
        conn = self._connections.pop(module_id, None)
        if conn is None:
            return

        if conn.process is not None:
            try:
                conn.process.terminate()
                await asyncio.wait_for(conn.process.wait(), timeout=5)
            except Exception:
                conn.process.kill()
        conn.connected = False
        logger.info(f"MCP [{module_id}]: 已断开")

    async def disconnect_all(self):
        """断开所有连接"""
        for module_id in list(self._connections.keys()):
            await self.disconnect(module_id)

    async def call_tool(self, module_id: str, tool_name: str, arguments: dict) -> str:
        """
        通过 MCP tools/call 调用远程工具。

        返回工具执行结果字符串。
        """
        conn = self._connections.get(module_id)
        if conn is None or not conn.connected:
            return f"模块 '{module_id}' 未连接"

        try:
            response = await self._send_jsonrpc(conn, {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments,
                },
            }, timeout=60)
            if response is None:
                return f"工具 '{tool_name}' 调用超时 ({module_id})"

            # 解析 MCP 返回的 content
            content_blocks = response.get("result", {}).get("content", [])
            texts = []
            for block in content_blocks:
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
            return "\n".join(texts) if texts else str(response.get("result", ""))
        except Exception as e:
            return f"MCP 工具调用异常 [{module_id}/{tool_name}]: {e}"

    async def health_check(self, module_id: str) -> bool:
        """ping 检查连接是否存活"""
        conn = self._connections.get(module_id)
        if conn is None or not conn.connected:
            return False
        try:
            resp = await self._send_jsonrpc(conn, {
                "jsonrpc": "2.0",
                "id": 999,
                "method": "ping",
                "params": {},
            }, timeout=3)
            return resp is not None and "result" in (resp or {})
        except Exception:
            return False

    def get_tools(self) -> dict[str, tuple[str, dict]]:
        """获取所有已连接模块的工具: {tool_name: (module_id, tool_info)}"""
        result = {}
        for module_id, conn in self._connections.items():
            if conn.connected:
                for tname, tinfo in conn.tools.items():
                    result[tname] = (module_id, tinfo)
        return result

    # ═════════ 内部实现 ═════════

    async def _send_jsonrpc(
        self,
        conn: MCPServerConnection,
        message: dict,
        timeout: float = 30.0,
        expect_response: bool = True,
    ) -> dict | None:
        """发送 JSON-RPC 消息并接收响应（MCP 协议底层）"""
        import json

        if conn.process is None or conn.process.stdin is None or conn.process.stdout is None:
            return None

        try:
            raw = json.dumps(message, ensure_ascii=False) + "\n"
            conn.process.stdin.write(raw.encode("utf-8"))
            await conn.process.stdin.drain()

            if not expect_response:
                return {"ok": True}

            # 读取响应行
            line = await asyncio.wait_for(
                conn.process.stdout.readline(),
                timeout=timeout,
            )
            if not line:
                return None
            return json.loads(line.decode("utf-8"))
        except asyncio.TimeoutError:
            logger.warning(f"MCP [{conn.module_id}]: 请求超时 id={message.get('id')}")
            return None
        except Exception as e:
            logger.warning(f"MCP [{conn.module_id}]: 通信错误: {e}")
            return None
