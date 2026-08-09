"""Agent Browser 浏览器自动化 MCP 模块"""

import shutil
import os
from agent.mcp_modules.base import BaseMCPModule, ModuleMeta, ModuleHealth


class AgentBrowserModule(BaseMCPModule):
    @property
    def meta(self) -> ModuleMeta:
        return ModuleMeta(
            id="agent-browser",
            name="浏览器自动化",
            description="Agent Browser — 网页导航、截图、内容提取、表单填充",
            icon="globe",
            category="external",
        )

    def detect(self) -> bool:
        """检查 npx 或 agent-browser 二进制是否存在"""
        if self._exists("tools/agent-browser-0.33.2/cli/Cargo.toml"):
            return True
        # 检查 npx 是否可用
        return shutil.which("npx") is not None

    def get_mcp_command(self) -> dict | None:
        """agent-browser 已有 Rust 原生 MCP Server（stdio JSON-RPC）"""
        return {
            "command": "npx",
            "args": ["agent-browser", "mcp", "--tools", "core,network"],
            "cwd": self._project_root,
            "env": {},
        }

    async def health(self) -> ModuleHealth:
        return ModuleHealth(installed=self.detect())
