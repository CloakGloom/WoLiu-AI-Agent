"""Presenton PPT 生成服务模块

Presenton 是开源 AI PPT 生成器（Electron + FastAPI）。
本模块管理其 FastAPI 后端（端口 18001）的健康检测与生命周期；
实际工具 generate_presenton_ppt 在 agent/tools/custom/presenton_bridge.py，
由 agent.tools 统一注册执行（与 ComfyUI 模块相同的直连桥接模式）。
"""

from agent.mcp_modules.base import BaseMCPModule, ModuleMeta, ModuleHealth

# 与 agent/tools/custom/presenton_bridge.py 保持一致
PRESENTON_PORT = 18001
PRESENTON_SERVER_REL = "side-projects/presenton-electron-v0.9.3-beta/servers/fastapi"


class PresentonModule(BaseMCPModule):
    @property
    def meta(self) -> ModuleMeta:
        return ModuleMeta(
            id="presenton",
            name="PPT 生成",
            description="Presenton AI 演示文稿生成（自动研究、排版、导出 PPTX）",
            icon="presentation",
            category="external",
            version="0.9.3",
            home_url="https://github.com/presenton/presenton",
        )

    def detect(self) -> bool:
        """检查 Presenton FastAPI 后端与虚拟环境是否存在"""
        return (self._exists(f"{PRESENTON_SERVER_REL}/server.py")
                and self._exists(f"{PRESENTON_SERVER_REL}/.venv/Scripts/python.exe"))

    def get_mcp_command(self) -> dict | None:
        # Presenton 自带 mcp_server.py，但其上游端口硬编码为 8000，
        # 且本项目 MCP 远程连接尚未启用，故走 HTTP 直连桥接
        return None

    def get_direct_tools(self) -> list[dict]:
        """generate_presenton_ppt 已在 agent.tools 中注册，此处不重复声明"""
        return []

    async def health(self) -> ModuleHealth:
        h = ModuleHealth(installed=self.detect())
        if h.installed:
            h.port = PRESENTON_PORT
            h.running = await self._check_http(f"http://127.0.0.1:{PRESENTON_PORT}/docs")
            if not h.running:
                h.last_error = "Presenton 未运行（调用 PPT 工具时会自动启动）"
        else:
            h.last_error = "未找到 Presenton 或虚拟环境"
        return h
