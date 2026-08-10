"""
agent.mcp_modules —— MCP 服务模块插件系统 → 桥接到 WoLiu-MCP

如果安装了 woliumcp 独立包，所有功能将委托给它；
否则回退到内置的 agent.mcp_modules 实现。

使用:
    from agent.mcp_modules import init, list_modules, get_module, get_all_mcp_configs

    # 初始化（设置项目根目录）
    init(project_root="/path/to/WoLiu-AI-Agent")

    # 列出所有可用模块
    for m in list_modules():
        print(f"{m['id']}: {m['name']} (installed={m['installed']})")

    # 获取某个模块的 MCP 配置
    cmd = get_module("comfyui").get_mcp_command()
"""

# ── 尝试桥接到 woliumcp 独立包 ──
_HAS_WOLIUMCP = False
try:
    import woliumcp as _woliumcp
    _HAS_WOLIUMCP = True
except ImportError:
    pass

if _HAS_WOLIUMCP:
    # woliumcp 已安装：直接委托
    init = _woliumcp.init
    list_modules = _woliumcp.list_modules
    get_module = _woliumcp.get_module
    scan_modules = _woliumcp.scan_modules
    get_all_mcp_configs = _woliumcp.get_all_mcp_configs
    get_all_direct_tools = _woliumcp.get_all_direct_tools
else:
    # 回退：使用内置实现
    from agent.mcp_modules._registry import get_registry

    def init(project_root: str = None, force_scan: bool = True):
        """兼容 woliumcp.init 接口（仅设置环境变量）"""
        import os
        if project_root:
            os.environ["WOLIU_PROJECT_ROOT"] = project_root
        if force_scan:
            get_registry().scan(force=True)

    def list_modules() -> list[dict]:
        return get_registry().list_modules()

    def get_module(module_id: str):
        return get_registry().get_module(module_id)

    def scan_modules(force: bool = False):
        return get_registry().scan(force=force)

    def get_all_mcp_configs() -> dict[str, dict]:
        return get_registry().get_all_mcp_configs()

    def get_all_direct_tools() -> list[dict]:
        return get_registry().get_all_direct_tools()
