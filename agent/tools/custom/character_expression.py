"""2D Live 角色表情切换工具 —— 供 AI 根据对话情绪调用"""

SCHEMA = {
    "type": "function",
    "tag": "系统",
    "function": {
        "name": "set_expression",
        "description": "切换 2D Live 角色的面部表情。仅在完成用户任务后、或纯聊天时根据情绪适当调用。"
                       "happy = 开心、兴奋、成功完成任务时；"
                       "unhappy = 遗憾、抱歉、无法完成任务时；"
                       "default = 中性、平常聊天时。"
                       "注意：收到任务请求时，必须先调用任务工具（如generate_presenton_ppt），完成任务后再调用本工具。严禁用本工具替代任务工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "enum": ["happy", "unhappy", "default"],
                    "description": "表情名称：happy（开心/正面）、unhappy（难过/遗憾/负面）、default（中性/正常）"
                }
            },
            "required": ["expression"]
        }
    }
}


def execute(arguments: dict) -> str:
    expression = arguments.get("expression", "default")
    # 返回特殊格式，前端 WebSocket 会拦截并切换 Spine 皮肤
    return f"[EXPRESSION:{expression}]"