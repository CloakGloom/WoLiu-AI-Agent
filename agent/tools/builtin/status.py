"""Agent 状态查询工具"""

from config import DEVICE_PC, DEVICE_MOBILE
from agent import database

SCHEMA = {
    "type": "function",
    "tag": "系统",
    "function": {
        "name": "get_agent_status",
        "description": "查询 Agent 当前所在的设备及可用硬件能力列表",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}


def execute(arguments: dict, current_device: str = DEVICE_PC) -> str:
    status_data = database.get_agent_status()
    device_name = "电脑" if current_device == DEVICE_PC else "手机"
    hardware = ["麦克风", "扬声器"]
    if current_device == DEVICE_PC:
        hardware.append("摄像头")
    online = "在线" if status_data.get("is_online") else "离线"
    return f"Agent 当前在{device_name}端。可用硬件：{', '.join(hardware)}。状态：{online}。"