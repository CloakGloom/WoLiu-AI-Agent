"""AutoLabel YOLO 训练/预测服务模块"""

from agent.mcp_modules.base import BaseMCPModule, ModuleMeta, ModuleHealth


class AutoLabelModule(BaseMCPModule):
    @property
    def meta(self) -> ModuleMeta:
        return ModuleMeta(
            id="autolabel",
            name="YOLO 训练",
            description="AutoLabel YOLO 目标检测训练、预测、数据集管理",
            icon="target",
            category="external",
        )

    def detect(self) -> bool:
        return self._exists("side-projects/autolabel-dock-main/main.py")

    def get_mcp_command(self) -> dict | None:
        return None  # AutoLabel 是 PyQt5 GUI，无 MCP

    async def health(self) -> ModuleHealth:
        h = ModuleHealth(installed=self.detect())
        return h  # GUI 应用无法端口检测
