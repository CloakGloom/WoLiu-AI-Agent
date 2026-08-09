"""TTS 语音合成服务模块"""

from agent.mcp_modules.base import BaseMCPModule, ModuleMeta, ModuleHealth


class TTSModule(BaseMCPModule):
    @property
    def meta(self) -> ModuleMeta:
        return ModuleMeta(
            id="tts",
            name="语音合成",
            description="ChatTTS / Confucius4-TTS 文本转语音服务",
            icon="microphone",
            category="external",
        )

    def detect(self) -> bool:
        """检查 TTS 项目是否存在"""
        return (
            self._exists("side-projects/ChatTTS/server.py")
            or self._exists("side-projects/Confucius4-TTS/server.py")
        )

    def get_mcp_command(self) -> dict | None:
        return None  # TTS 无 MCP Server，走 HTTP 反向代理

    async def health(self) -> ModuleHealth:
        h = ModuleHealth(installed=self.detect())
        if h.installed:
            # 检测 ChatTTS (8001) 或 Confucius4 (8000)
            if self._exists("side-projects/ChatTTS/server.py"):
                h.port = 8001
                h.running = await self._check_port(8001)
            else:
                h.port = 8000
                h.running = await self._check_port(8000) or await self._check_http("http://127.0.0.1:8000/docs")
        return h
