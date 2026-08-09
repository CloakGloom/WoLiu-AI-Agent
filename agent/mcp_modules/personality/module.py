"""
人格系统 MCP 模块 —— 15维演化人格的可观测模块

内置模块，始终 detected。不提供外部进程管理，仅用于状态展示。
"""
from __future__ import annotations

from agent.mcp_modules.base import BaseMCPModule, ModuleMeta, ModuleHealth


class PersonalityModule(BaseMCPModule):
    """15维演化人格 - 内置模块"""

    @property
    def meta(self) -> ModuleMeta:
        return ModuleMeta(
            id="personality",
            name="15维人格系统",
            description="warmth/sarcasm/sexual_openness 等15维动态演化人格",
            icon="theater-masks",
            category="builtin",
            version="1.0",
            author="builtin",
        )

    def detect(self) -> bool:
        return True

    def get_mcp_command(self) -> dict | None:
        return None

    async def health(self) -> ModuleHealth:
        enabled = True
        try:
            import os, json
            settings = os.path.join(self._project_root, "config", "settings.json")
            with open(settings, encoding="utf-8") as f:
                enabled = json.load(f).get("personality_enabled", True)
        except Exception:
            pass
        return ModuleHealth(installed=True, running=enabled)
