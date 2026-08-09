"""JadeAI 简历生成服务模块"""

from agent.mcp_modules.base import BaseMCPModule, ModuleMeta, ModuleHealth


class JadeAIModule(BaseMCPModule):
    @property
    def meta(self) -> ModuleMeta:
        return ModuleMeta(
            id="jadeai",
            name="简历生成",
            description="JadeAI 智能简历编辑与导出",
            icon="file-text",
            category="external",
        )

    def detect(self) -> bool:
        return self._exists("side-projects/JadeAI-0.4.1/package.json")

    def get_mcp_command(self) -> dict | None:
        return None  # JadeAI 是 Next.js 项目，无 MCP

    async def health(self) -> ModuleHealth:
        h = ModuleHealth(installed=self.detect())
        h.port = 3000
        if h.installed:
            h.running = await self._check_port(3000)
        return h
