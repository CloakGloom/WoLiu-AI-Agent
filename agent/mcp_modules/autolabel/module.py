"""
AutoLabel MCP 模块 —— 通过子进程调用（规避 AGPL import）
"""
import os, sys, json, subprocess, logging

logger = logging.getLogger(__name__)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class AutolabelModule:
    """AutoLabel MCP 模块：提供 yolo_dataset_manage / yolo_train / yolo_predict"""
    name = "autolabel"
    display_name = "AutoLabel (YOLO)"
    description = "YOLO 目标检测标注与训练工具"

    # ── 前端配置 ──
    @property
    def frontend_config(self):
        cfg_path = os.path.join(ROOT, "config", "services.json")
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                svc = json.load(f)
        except Exception:
            svc = {}
        autolabel = svc.get("autolabel", {})
        return {
            "id": self.name,
            "label": self.display_name,
            "desc": self.description,
            "enabled": autolabel.get("enabled", False),
            "autostart": autolabel.get("autostart", False),
            "extra_fields": [
                {"key": "autostart", "type": "boolean", "label": "启动时自启", "default": False},
            ],
            "actions": {
                "is_binary_toggle": autolabel.get("enabled", False),
                "commands": {
                    "enable": {"label": "启用", "action": f"mcp_{self.name}_enable"},
                    "disable": {"label": "禁用", "action": f"mcp_{self.name}_disable"},
                }
            }
        }

    # ── 启动 / 停止 ──
    async def start(self):
        """启用模块（无独立服务需启动，仅切换启用标记）"""
        logger.info(f"[autolabel] 模块已启用（工具通过子进程按需启动）")
        return True

    async def stop(self):
        logger.info(f"[autolabel] 模块已禁用")
        return True

    # ── 健康检查 ──
    async def health_check(self):
        cli = os.path.join(ROOT, "scripts", "autolabel_cli.py")
        return os.path.isfile(cli)

    # ── 工具 Schema ──
    @property
    def tool_list(self):
        import importlib.util
        tools_dir = os.path.join(ROOT, "agent", "tools", "custom")
        schemas = []
        for name in ("autolabel_dataset", "autolabel_train", "autolabel_predict"):
            spec = importlib.util.spec_from_file_location(name, os.path.join(tools_dir, f"{name}.py"))
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
                if hasattr(mod, "SCHEMA"):
                    schemas.append(mod.SCHEMA)
            except Exception as e:
                logger.warning(f"[autolabel] 加载工具 {name} schema 失败: {e}")
        return schemas

    # ── 工具执行 ──
    async def execute_tool(self, tool_name: str, arguments: dict):
        import importlib.util
        tools_dir = os.path.join(ROOT, "agent", "tools", "custom")
        mapping = {
            "yolo_dataset_manage": "autolabel_dataset",
            "yolo_train": "autolabel_train",
            "yolo_predict": "autolabel_predict",
        }
        mod_name = mapping.get(tool_name)
        if not mod_name:
            return f"未知工具: {tool_name}"
        spec = importlib.util.spec_from_file_location(mod_name, os.path.join(tools_dir, f"{mod_name}.py"))
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            return mod.execute(arguments)
        except Exception as e:
            logger.error(f"[autolabel] 执行 {tool_name} 失败: {e}")
            return f"❌ 执行失败: {e}"
