"""
MCP 模块注册表 —— 自动发现 + 热插拔

扫描 agent/mcp_modules/ 下所有子目录的 module.py，
自动发现已安装的 MCP 服务模块，支持运行时加载/卸载。
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import threading
from typing import Any

from agent.mcp_modules.base import BaseMCPModule, ModuleMeta, ModuleHealth

# 模块搜索目录
_MODULES_DIR = os.path.dirname(os.path.abspath(__file__))


class MCPModuleRegistry:
    """
    MCP 模块注册表 —— 单例。

    启动时扫描 agent/mcp_modules/ 下所有子文件夹，
    自动发现所有 module.py 并检测 install 状态。
    未安装的模块静默跳过，不出现在 API 中。
    """

    _instance: MCPModuleRegistry | None = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._modules: dict[str, BaseMCPModule] = {}
                    cls._instance._scanned = False
        return cls._instance

    # ── 扫描与发现 ──

    def scan(self, force: bool = False) -> dict[str, BaseMCPModule]:
        """
        扫描模块目录，发现所有已安装的模块。

        返回 {module_id: module_instance}
        """
        if self._scanned and not force:
            return self._modules

        self._modules.clear()
        self._scanned = True

        if not os.path.isdir(_MODULES_DIR):
            return self._modules

        for entry in sorted(os.listdir(_MODULES_DIR)):
            mod_dir = os.path.join(_MODULES_DIR, entry)
            if not os.path.isdir(mod_dir):
                continue
            if entry.startswith("_") or entry.startswith("."):
                continue

            mod_file = os.path.join(mod_dir, "module.py")
            if not os.path.isfile(mod_file):
                continue

            try:
                module = self._load_module(entry, mod_file, mod_dir)
                if module is not None:
                    self._modules[entry] = module
                    print(f"[MCP] 发现模块: {entry} ({module.meta.name})", file=sys.stderr)
            except Exception as e:
                print(f"[MCP] 加载模块失败 {entry}: {e}", file=sys.stderr)

        return self._modules

    def reload(self):
        """重新扫描（用于模块安装/卸载后）"""
        self._scanned = False
        self.scan(force=True)

    # ── 查询接口 ──

    def list_modules(self) -> list[dict]:
        """
        列出所有已安装模块的元信息（供 /api/mcp/modules 使用）。

        返回:
        [
            {
                "id": "comfyui",
                "name": "AI 绘画",
                "description": "ComfyUI 图像/视频生成",
                "icon": "paint-brush",
                "installed": true,
                "running": false,
                "status": "stopped",
                ...
            },
            ...
        ]
        """
        self.scan()
        result = []

        for mod_id, mod in self._modules.items():
            meta = mod.meta
            health = ModuleHealth(installed=mod.detect())

            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 在事件循环中，返回 installed 状态即可
                    pass
                else:
                    health = asyncio.run(mod.health())
            except RuntimeError:
                pass
            except Exception:
                pass

            status = "stopped"
            if health.running:
                status = "running"
            elif health.last_error:
                status = "error"

            result.append({
                "id": mod_id,
                "name": meta.name,
                "description": meta.description,
                "icon": meta.icon,
                "category": meta.category,
                "version": meta.version,
                "installed": health.installed,
                "running": health.running,
                "status": status,
                "port": health.port,
                "has_mcp": mod.get_mcp_command() is not None,
                "error": health.last_error,
            })

        return result

    def get_module(self, module_id: str) -> BaseMCPModule | None:
        """获取指定模块实例"""
        self.scan()
        return self._modules.get(module_id)

    def get_all_mcp_configs(self) -> dict[str, dict]:
        """
        获取所有支持 MCP 的模块的配置，用于 tools/list 发现。

        返回: {module_id: mcp_command_dict}
        """
        self.scan()
        configs = {}
        for mod_id, mod in self._modules.items():
            cmd = mod.get_mcp_command()
            if cmd:
                configs[mod_id] = cmd
        return configs

    def get_all_direct_tools(self) -> list[dict]:
        """
        收集所有模块的直连工具（非 MCP，HTTP 桥接）。
        用于发送给 LLM 的 tools 列表。
        """
        self.scan()
        tools = []
        for mod_id, mod in self._modules.items():
            tools.extend(mod.get_direct_tools())
        return tools

    # ── 内部实现 ──

    def _load_module(self, mod_id: str, mod_file: str, mod_dir: str) -> BaseMCPModule | None:
        """从 module.py 加载一个模块"""
        # 动态导入
        spec = importlib.util.spec_from_file_location(
            f"agent.mcp_modules.{mod_id}",
            mod_file,
        )
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # 查找继承 BaseMCPModule 的类
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type)
                    and issubclass(attr, BaseMCPModule)
                    and attr is not BaseMCPModule):
                instance = attr(module_dir=mod_dir)
                if instance.detect():
                    return instance
                else:
                    print(f"[MCP] 模块 {mod_id} 未安装，跳过", file=sys.stderr)
                    return None

        return None


# ── 便捷入口 ──

def get_registry() -> MCPModuleRegistry:
    return MCPModuleRegistry()
