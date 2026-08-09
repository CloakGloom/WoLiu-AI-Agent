"""Spine2D 动画 MCP 模块"""

from agent.mcp_modules.base import BaseMCPModule, ModuleMeta, ModuleHealth


class Spine2DModule(BaseMCPModule):
    @property
    def meta(self) -> ModuleMeta:
        return ModuleMeta(
            id="spine2d",
            name="Spine 动画",
            description="PSD 转 Spine 2D 骨骼动画（import_psd_to_spine）",
            icon="cubes",
            category="external",
        )

    def detect(self) -> bool:
        return self._exists("side-projects/spine2d-animation-mcp-main/src/spine2d_mcp/server.py")

    def get_mcp_command(self) -> dict | None:
        """Spine2D 已有 FastMCP 实现"""
        return {
            "command": "python",
            "args": ["-m", "spine2d_mcp.server"],
            "cwd": self._path("side-projects/spine2d-animation-mcp-main"),
            "env": {"PYTHONPATH": self._path("side-projects/spine2d-animation-mcp-main")},
        }

    async def health(self) -> ModuleHealth:
        return ModuleHealth(installed=self.detect())
