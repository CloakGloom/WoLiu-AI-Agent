"""
agent.mcp_modules —— MCP 服务模块插件系统

自动发现:
    扫描 agent/mcp_modules/ 下所有子文件夹的 module.py，
    检测已安装的模块，未安装的自动跳过。

使用:
    from agent.mcp_modules import list_modules, get_module, get_all_mcp_configs

    # 列出所有可用模块
    for m in list_modules():
        print(f"{m['id']}: {m['name']} (installed={m['installed']})")

    # 获取某个模块的 MCP 配置
    cmd = get_module("comfyui").get_mcp_command()
"""

from agent.mcp_modules._registry import get_registry


def list_modules() -> list[dict]:
    """列出所有可用模块（已安装的才会出现）"""
    return get_registry().list_modules()


def get_module(module_id: str):
    """获取指定模块实例"""
    return get_registry().get_module(module_id)


def scan_modules(force: bool = False):
    """重新扫描模块目录"""
    return get_registry().scan(force=force)


def get_all_mcp_configs() -> dict[str, dict]:
    """获取所有支持 MCP 的模块配置"""
    return get_registry().get_all_mcp_configs()


def get_all_direct_tools() -> list[dict]:
    """获取所有模块的直连工具"""
    return get_registry().get_all_direct_tools()
