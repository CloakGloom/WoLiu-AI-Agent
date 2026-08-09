"""获取当前时间工具（datetime_tool）"""

import datetime

SCHEMA = {
    "type": "function",
    "tag": "系统",
    "function": {
        "name": "get_current_time",
        "description": "获取当前日期和时间",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}


def execute(arguments: dict) -> str:
    return f"当前时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"