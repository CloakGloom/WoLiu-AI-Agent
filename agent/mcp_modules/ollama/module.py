"""Ollama 本地 LLM 服务模块"""

import os
from agent.mcp_modules.base import BaseMCPModule, ModuleMeta, ModuleHealth


class OllamaModule(BaseMCPModule):
    @property
    def meta(self) -> ModuleMeta:
        return ModuleMeta(
            id="ollama",
            name="本地 LLM",
            description="Ollama 本地模型推理（视觉/对话/代码）",
            icon="server",
            category="external",
        )

    def detect(self) -> bool:
        """检查 ollama.exe 是否存在"""
        paths = [
            "D:/Ollama/ollama.exe",
            "C:/Users/15PRO/AppData/Local/Programs/Ollama/ollama.exe",
        ]
        for p in paths:
            if os.path.exists(p):
                return True

        # 也检查 PATH 中是否有 ollama
        import shutil
        return shutil.which("ollama") is not None

    def get_mcp_command(self) -> dict | None:
        return None  # Ollama 无 MCP，走 REST API

    async def health(self) -> ModuleHealth:
        h = ModuleHealth(installed=self.detect())
        h.port = 11434
        if h.installed:
            h.running = await self._check_http("http://127.0.0.1:11434/api/version")
        return h
