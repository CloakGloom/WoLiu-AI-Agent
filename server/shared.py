"""
server/app.py 和 server/api.py 共享的工具函数
打破循环导入，提取重复代码
"""
from typing import Optional
from fastapi import Request

from agent import database


async def parse_json_body(request: Request) -> dict:
    """安全解析 JSON 请求体，解析失败返回空字典"""
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def ensure_session(state) -> str:
    """确保存在活跃会话（从 DB 查询，服务重启后也能复用）"""
    if state.current_session_id is None:
        sessions = database.get_active_sessions()
        if sessions:
            state.current_session_id = sessions[0]["session_id"]
        else:
            state.current_session_id = database.create_session("电脑")
    return state.current_session_id


def format_messages_for_ws(messages: list) -> list:
    """将数据库消息格式化为 WebSocket 传输格式"""
    return [
        {
            "message_id": m["message_id"],
            "role": m["role"],
            "content": m["content"],
            "process_steps": m.get("process_steps"),
            "branches": m.get("branches"),
        }
        for m in messages
        if m["role"] in ("user", "assistant")
    ]


def format_sessions_list(sessions: list) -> list:
    """将数据库会话列表格式化为前端传输格式"""
    return [
        {
            "session_id": s["session_id"],
            "device": s["device"],
            "message_count": s["message_count"],
            "updated_at": s["updated_at"],
            "created_at": s.get("created_at", ""),
            "pinned": s.get("pinned", 0),
            "title": s.get("title", ""),
        }
        for s in sessions
    ]


def fallback_session(target: str, state) -> str:
    """会话回退：验证目标并返回有效的 session_id"""
    session = database.get_session(target)
    if session:
        return target
    sessions = database.get_active_sessions()
    if sessions:
        return sessions[0]["session_id"]
    return database.create_session("电脑")
