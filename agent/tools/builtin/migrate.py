"""Agent 迁移工具"""

from config import DEVICE_PC, DEVICE_MOBILE

# 迁移回调，由 server/app.py 注入
_migrate_callback = None


def set_migrate_callback(cb):
    """设置迁移回调函数，参数: (target_device: str) -> str"""
    global _migrate_callback
    _migrate_callback = cb


SCHEMA = {
    "type": "function",
    "tag": "系统",
    "function": {
        "name": "migrate_agent",
        "description": "将 Agent 从当前设备迁移到目标设备（电脑或手机）。当用户明确要求切换设备时调用此工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "target_device": {
                    "type": "string",
                    "enum": ["电脑", "手机"],
                    "description": "目标设备：电脑 或 手机",
                }
            },
            "required": ["target_device"],
        },
    },
}


def execute(arguments: dict, current_device: str = DEVICE_PC) -> str:
    """执行迁移"""
    target_device = arguments.get("target_device", "")

    # 确定目标设备常量
    if target_device == "电脑":
        target_const = DEVICE_PC
    elif target_device == "手机":
        target_const = DEVICE_MOBILE
    else:
        return f"未知目标设备：{target_device}，请使用「电脑」或「手机」"

    # 检查是否已在目标设备
    if current_device == target_const:
        return f"Agent 已经在{target_device}端了，无需迁移"

    # 调用实际迁移回调
    if _migrate_callback is None:
        return f"迁移功能未初始化，请重启服务"

    try:
        result = _migrate_callback(target_const)
        return result
    except Exception as e:
        return f"迁移失败：{e}"