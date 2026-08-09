"""Agent Browser 浏览器自动化 MCP 模块 —— 本地 node_modules 安装"""

import shutil
import os
import sys
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

    def _agent_browser_bin(self) -> str:
        """返回本地 agent-browser 可执行文件路径"""
        # agent-browser 安装为 npm 包的 binary，Node.js 生成对应的 .cmd
        candidates = [
            os.path.join(self._project_root, "node_modules", ".bin", "agent-browser.cmd"),
            os.path.join(self._project_root, "node_modules", ".bin", "agent-browser"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        return "npx"

    def detect(self) -> bool:
        """检查 agent-browser 是否可用"""
        if self._exists("tools/agent-browser-0.33.2/cli/Cargo.toml"):
            return True
        # 本地 node_modules 安装
        if os.path.isfile(os.path.join(self._project_root, "node_modules", ".bin", "agent-browser.cmd")):
            return True
        return shutil.which("npx") is not None

    def get_mcp_command(self) -> dict | None:
        return {
            "command": self._agent_browser_bin(),
            "args": ["mcp", "--tools", "core,network"],
            "cwd": self._project_root,
            "env": {},
        }

    async def health(self) -> ModuleHealth:
        return ModuleHealth(installed=self.detect())
