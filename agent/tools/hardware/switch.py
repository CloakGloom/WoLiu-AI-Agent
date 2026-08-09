"""硬件切换工具"""

from config import DEVICE_PC, DEVICE_MOBILE

SCHEMA = {
    "type": "function",
    "tag": "设备",
    "function": {
        "name": "switch_hardware",
        "description": "根据当前所在设备切换硬件调用目标（麦克风/扬声器/摄像头）",
        "parameters": {
            "type": "object",
            "properties": {
                "device": {
                    "type": "string",
                    "enum": ["电脑", "手机"],
                    "description": "目标设备",
                }
            },
            "required": ["device"],
        },
    },
}


def execute(arguments: dict) -> str:
    target = arguments.get("device", "")
    hardware = ["麦克风", "扬声器"]
    if target == "电脑":
        hardware.append("摄像头")
    return f"已切换到{target}端硬件。可用硬件：{', '.join(hardware)}。"