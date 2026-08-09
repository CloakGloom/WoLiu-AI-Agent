"""
API 路由（APIRouter）—— 手机端调用的 REST API
端点：/api/sessions, /api/agent/status, /api/agent/migrate

迁移自 Flask Blueprint（2026-08-07）：使用 FastAPI APIRouter，
阻塞调用（run_agent）走 run_in_threadpool，错误用 JSONResponse 保留 {"error": ...} 结构。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool

from agent import database
from agent.core import run_agent
from agent.rules.loader import get_max_history_turns
from config import DEVICE_PC, DEVICE_MOBILE

# 共享状态与迁移函数（来自 server.app 单例）
from server.app import state, _do_migrate
from server.shared import parse_json_body, fallback_session

# Pydantic 请求校验（自动生成 OpenAPI 文档，/docs 可调试）
from server.schemas import (
    ChatRequest, CreateSessionRequest, PinSessionRequest,
    RenameSessionRequest, BatchDeleteRequest, RuleUpdateRequest,
    PersonalityUpdateRequest, ToolToggleRequest, MigrateRequest,
)

api_router = APIRouter(prefix="/api")


# ==================== 会话管理 ====================

@api_router.get("/sessions")
async def get_sessions():
    """获取所有活跃会话列表"""
    sessions = database.get_active_sessions()
    return {"sessions": sessions}


@api_router.post("/sessions")
async def create_session(body: CreateSessionRequest):
    """创建新会话"""
    session_id = database.create_session(body.device)
    state.current_session_id = session_id
    return {"session_id": session_id, "status": "created"}


@api_router.delete("/sessions/current/messages")
async def clear_messages():
    """清空当前会话的所有消息"""
    session_id = state.current_session_id
    if session_id:
        database.delete_session_messages(session_id)
        return {"status": "cleared", "session_id": session_id}
    return JSONResponse(status_code=404, content={"error": "没有活跃会话"})


# 注意：删除会话已迁移到 server/app.py @app.delete("/api/sessions/{session_id}")，返回 sessions 列表
# 注意：批量删除已迁移到 server/app.py 的 @app.delete("/api/sessions/batch")，返回 sessions 列表


@api_router.put("/sessions/{session_id}/pin")
async def pin_session(session_id: str, body: PinSessionRequest):
    """置顶/取消置顶会话"""
    database.pin_session(session_id, body.pinned)
    return {"status": "ok", "session_id": session_id, "pinned": body.pinned}


@api_router.put("/sessions/{session_id}/rename")
async def rename_session(session_id: str, body: RenameSessionRequest):
    """重命名会话"""
    database.rename_session(session_id, body.title)
    return {"status": "ok", "session_id": session_id, "title": body.title}


@api_router.post("/sessions/{session_id}/duplicate")
async def duplicate_session(session_id: str):
    """复制会话"""
    new_id = database.duplicate_session(session_id)
    if new_id is None:
        return JSONResponse(status_code=404, content={"error": "会话不存在"})
    return {"status": "ok", "session_id": new_id}


@api_router.delete("/messages/{message_id}")
async def delete_message(message_id: int):
    """删除单条消息"""
    database.delete_message(message_id)
    return {"status": "deleted", "message_id": message_id}


@api_router.put("/messages/{message_id}")
async def update_message(message_id: int, request: Request):
    """编辑消息内容"""
    data = await parse_json_body(request)
    content = data.get("content", "")
    rerun = data.get("rerun", False)  # 是否触发 AI 重新回复

    if rerun:
        # 获取消息所属会话
        session_id = database.get_message_session(message_id)
        if not session_id:
            return JSONResponse(status_code=404, content={"error": "消息不存在"})

        # 保存当前 AI 回复为分支（含用户旧消息内容，方便切换时显示）
        next_msg = database.get_next_assistant_message(session_id, message_id)
        old_user_content = database.get_message_content(message_id) or ""
        if next_msg:
            database.add_branch(message_id, next_msg["content"], 
                               process_steps=next_msg.get("process_steps"),
                               user_content=old_user_content)

        # 更新用户消息
        database.update_message(message_id, content)

        # 删除后续消息
        database.delete_messages_after(session_id, message_id)

        # 重新生成 AI 回复
        messages = database.get_messages_as_openai_format(session_id, get_max_history_turns())
        reply = await run_in_threadpool(run_agent, messages, session_id=session_id)

        return {"status": "updated", "message_id": message_id, "reply": reply}

    database.update_message(message_id, content)
    return {"status": "updated", "message_id": message_id}


@api_router.get("/messages/{message_id}/branches")
async def get_message_branches(message_id: int):
    """获取消息的所有历史分支"""
    branches = database.get_branches(message_id)
    return branches


@api_router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str):
    """获取指定会话的完整消息历史"""
    messages = database.get_all_messages(session_id)
    return {
        "session_id": session_id,
        "messages": messages,
    }


@api_router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, body: ChatRequest):
    """发送消息并获取 Agent 回复"""
    device = body.device or "手机"

    if state.agent_location == "migrating":
        return JSONResponse(status_code=503, content={"error": "Agent 正在迁移中，请稍候"})

    if state.agent_location != "mobile" and device == "手机":
        return JSONResponse(status_code=403, content={"error": "Agent 当前不在手机端，无法对话"})

    database.save_message(session_id, "user", body.content, device)
    database.update_session_activity(session_id)

    try:
        messages = database.get_messages_as_openai_format(session_id, get_max_history_turns())
        reply = await run_in_threadpool(run_agent, messages, session_id=session_id)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Agent 调用失败：{e}"})

    return {
        "session_id": session_id,
        "reply": reply,
        "role": "assistant",
    }


# ==================== Agent 状态 ====================

@api_router.get("/agent/status")
async def get_agent_status():
    """获取 Agent 当前状态"""
    status_data = database.get_agent_status()
    return {
        "current_device": state.agent_location,
        "is_online": status_data.get("is_online", 1) == 1,
        "last_online_at": status_data.get("last_online_at"),
        "last_migration_at": status_data.get("last_migration_at"),
        "session_id": state.current_session_id,
    }


@api_router.post("/agent/migrate")
async def trigger_migrate(body: MigrateRequest):
    """发起迁移指令"""
    if body.target_device == "手机":
        result = _do_migrate(DEVICE_MOBILE, state.mobile_ws)
    else:
        result = _do_migrate(DEVICE_PC, state.pc_ws)
    return {"result": result}


# ==================== 记忆管理 ====================

from agent.memory.long_term import _get_retriever


@api_router.get("/memory/stats")
async def get_memory_stats():
    """获取记忆统计信息"""
    store = _get_retriever().store
    return {"total": store.count()}


@api_router.get("/memory/list")
async def list_memories(session_id: str = None, limit: int = 50):
    """列出记忆（可按会话过滤）"""
    store = _get_retriever().store
    try:
        results = store.collection.get(
            limit=limit,
            include=["metadatas", "documents"],
            where={"session_id": session_id} if session_id else None,
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

    if not results or not results.get("ids"):
        return {"memories": [], "total": 0}

    memories = []
    for i, mid in enumerate(results["ids"]):
        meta = results["metadatas"][i] if results.get("metadatas") else {}
        memories.append({
            "id": mid,
            "document": results["documents"][i] if results.get("documents") else "",
            "session_id": meta.get("session_id", ""),
            "turn": meta.get("turn", 0),
        })

    return {"memories": memories, "total": len(memories)}


@api_router.post("/memory/search")
async def search_memories(request: Request):
    """语义搜索记忆"""
    data = await parse_json_body(request)
    query = data.get("query", "").strip()
    limit = data.get("limit", 10)
    session_id = data.get("session_id")

    if not query:
        return JSONResponse(status_code=400, content={"error": "缺少搜索关键词"})

    store = _get_retriever().store
    results = store.search(query, top_k=limit, threshold=0.3)

    return {"query": query, "results": results, "total": len(results)}


@api_router.delete("/memory/{memory_id}")
async def delete_memory(memory_id: str):
    """删除指定记忆"""
    store = _get_retriever().store
    try:
        store.collection.delete(ids=[memory_id])
        return {"status": "deleted", "memory_id": memory_id}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@api_router.delete("/memory/session/{session_id}")
async def delete_session_memories(session_id: str):
    """删除指定会话的所有记忆"""
    store = _get_retriever().store
    try:
        store.delete_by_session(session_id)
        return {"status": "deleted", "session_id": session_id}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
