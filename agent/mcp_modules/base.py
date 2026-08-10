"""
MCP 服务模块基类 —— 所有 MCP 模块的约定接口

每个模块只需在 agent/mcp_modules/<module_id>/ 下放一个 module.py，
导出模块类继承 BaseMCPModule 并实现必要方法即可被自动发现。
"""

from __future__ import annotations

import abc
import asyncio
import subprocess
import sys
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModuleMeta:
    """模块元信息 —— 用于 UI 展示"""
    id: str                             # 唯一标识: "comfyui", "tts" ...
    name: str                           # 中文名: "AI 绘画"
    description: str = ""               # 一句话描述
    icon: str = "plugin"                # 前端图标名
    category: str = "external"          # builtin | external
    version: str = "1.0.0"
    author: str = ""
    home_url: str = ""


@dataclass
class ModuleHealth:
    """模块健康状态"""
    installed: bool = False             # 文件夹/可执行文件是否存在
    running: bool = False               # 进程是否在运行
    pid: int | None = None
    port: int | None = None
    last_error: str = ""
    uptime_seconds: float = 0.0


class BaseMCPModule(abc.ABC):
    """
    MCP 服务模块抽象基类。

    子类需要实现:
    - meta: 返回模块元信息
    - detect(): 检查模块是否可运行（文件夹/exe 是否存在）
    - get_mcp_command(): 返回 MCP server 命令（None = 不支持 MCP）
    - start() / stop(): 进程管理（如果 expose_service_endpoints = True）
    - health(): 返回健康状态

    可选覆盖:
    - get_direct_tools(): 如果模块自身不提供 MCP 但需要通过 HTTP 桥接的工具
    """

    def __init__(self, module_dir: str, project_root: str | None = None):
        self._module_dir = module_dir  # 模块所在目录的绝对路径
        if project_root:
            self._project_root = project_root
        else:
            self._project_root = os.environ.get("WOLIU_PROJECT_ROOT",
                os.path.dirname(os.path.dirname(os.path.dirname(module_dir))))

    # ── 必须实现的属性 ──

    @property
    @abc.abstractmethod
    def meta(self) -> ModuleMeta:
        """模块元信息"""
        ...

    # ── 必须实现的方法 ──

    @abc.abstractmethod
    def detect(self) -> bool:
        """
        检测模块是否已安装（文件夹/可执行文件存在）。
        返回 False 的模块不会出现在 UI 中。
        """
        ...

    def get_mcp_command(self) -> dict | None:
        """
        返回 MCP Server 启动配置:
        {
            "command": "python",
            "args": ["-m", "comfyui.mcp_server"],
            "cwd": "./side-projects/ComfyUI_windows_portable",
        }
        返回 None 表示该模块不支持 MCP 协议。
        """
        return None

    # ── 服务管理（可选）──

    def get_start_command(self) -> list[str] | None:
        """返回启动服务的命令行。None = 不需要进程管理"""
        return None

    def get_stop_command(self) -> list[str] | None:
        """返回停止服务的命令行。None = 用 taskkill"""
        return None

    async def health(self) -> ModuleHealth:
        """检查服务健康状态"""
        return ModuleHealth(installed=self.detect())

    # ── 工具定义（可选）──

    def get_direct_tools(self) -> list[dict]:
        """
        返回该模块通过 HTTP 桥接可用的工具定义（OpenAI function schema）。
        用于 comfyui / tts 等虽然不提供 MCP Server 但仍有工具的场景。
        """
        return []

    # ── 辅助方法 ──

    def _path(self, rel: str) -> str:
        """相对于项目根目录的路径"""
        return os.path.normpath(os.path.join(self._project_root, rel))

    def _exists(self, rel: str) -> bool:
        """检查相对路径是否存在"""
        return os.path.exists(self._path(rel))

    async def _check_port(self, port: int, host: str = "127.0.0.1") -> bool:
        """检查端口是否监听"""
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False

    async def _check_http(self, url: str) -> bool:
        """检查 HTTP 端点是否可访问"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(url)
                return resp.status_code < 500
        except Exception:
            return False
