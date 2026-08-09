"""
AI 记忆管理工具 —— 查看、搜索、删除长期记忆（ChromaDB 向量库）

提供完整的记忆生命周期管理能力：
- 列出所有记忆（可按会话过滤）
- 语义搜索记忆
- 删除指定记忆或按会话批量清除
- 获取记忆统计信息
"""
from typing import Optional

from agent.memory.long_term import _get_retriever
from agent.memory.long_term.vector_store import VectorStore

SCHEMA = {
    "type": "function",
    "tag": "记忆",
    "function": {
        "name": "manage_memory",
        "description": (
            "管理 AI 长期记忆（向量数据库）。支持操作："
            "list（列出记忆）、search（语义搜索）、delete（删除）、"
            "stats（统计信息）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "search", "delete", "stats"],
                    "description": (
                        "操作类型：list=列出所有记忆，search=语义搜索记忆，"
                        "delete=删除记忆，stats=获取记忆统计信息"
                    ),
                },
                "query": {
                    "type": "string",
                    "description": (
                        "搜索或删除时的关键词/查询文本。"
                        "search: 使用语义搜索匹配相关记忆；"
                        "delete: 当 action=delete 时，若提供则删除匹配的记忆"
                    ),
                },
                "session_id": {
                    "type": "string",
                    "description": "限定操作的会话 ID（可选）。用于按会话过滤或删除。",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回结果数量上限（默认 20）",
                },
                "memory_id": {
                    "type": "string",
                    "description": "要删除的特定记忆 ID（仅 action=delete 时有效）",
                },
            },
            "required": ["action"],
        },
    },
}


def execute(action: str, query: Optional[str] = None,
            session_id: Optional[str] = None,
            limit: int = 20,
            memory_id: Optional[str] = None,
            **kwargs) -> str:
    """执行记忆管理操作"""

    store = _get_retriever().store

    if action == "stats":
        return _handle_stats(store)

    elif action == "list":
        return _handle_list(store, session_id, limit)

    elif action == "search":
        return _handle_search(store, query, session_id, limit)

    elif action == "delete":
        return _handle_delete(store, query, session_id, memory_id)

    else:
        return f"未知操作: {action}，支持的操作: list, search, delete, stats"


def _handle_stats(store: VectorStore) -> str:
    """获取记忆统计"""
    total = store.count()
    lines = [f"记忆总数: {total} 条"]
    return "\n".join(lines)


def _handle_list(store: VectorStore, session_id: str, limit: int) -> str:
    """列出记忆"""
    try:
        results = store.collection.get(
            limit=limit,
            include=["metadatas", "documents"],
            where={"session_id": session_id} if session_id else None,
        )
    except Exception as e:
        return f"列出记忆失败: {e}"

    if not results or not results.get("ids"):
        scope = f"会话 {session_id} 中" if session_id else ""
        return f"{scope}没有找到记忆。"

    lines = [f"共 {len(results['ids'])} 条记忆："]
    for i, mid in enumerate(results["ids"], 1):
        meta = results["metadatas"][i - 1] if results.get("metadatas") else {}
        doc = results["documents"][i - 1] if results.get("documents") else ""
        preview = doc[:80] + "..." if len(doc) > 80 else doc
        lines.append(f"  [{i}] ID={mid} | 会话={meta.get('session_id', '?')} | {preview}")

    return "\n".join(lines)


def _handle_search(store: VectorStore, query: str, session_id: str, limit: int) -> str:
    """语义搜索记忆"""
    if not query:
        return "请提供搜索关键词"

    results = store.search(query, top_k=limit, threshold=0.3)

    if not results:
        return f"未找到与「{query}」相关的记忆"

    lines = [f"搜索「{query}」找到 {len(results)} 条相关记忆："]
    for i, item in enumerate(results, 1):
        meta = item.get("metadata", {})
        similarity = item.get("similarity", 0)
        doc = item.get("document", "")
        preview = doc[:100] + "..." if len(doc) > 100 else doc
        lines.append(f"  [{i}] 相似度={similarity:.2f} | 会话={meta.get('session_id', '?')}")
        lines.append(f"      {preview}")

    return "\n".join(lines)


def _handle_delete(store: VectorStore, query: str, session_id: str,
                   memory_id: str) -> str:
    """删除记忆"""
    if memory_id:
        try:
            store.collection.delete(ids=[memory_id])
            return f"已删除记忆 {memory_id}"
        except Exception as e:
            return f"删除记忆 {memory_id} 失败: {e}"

    if session_id:
        try:
            store.delete_by_session(session_id)
            return f"已删除会话 {session_id} 的所有记忆"
        except Exception as e:
            return f"删除会话记忆失败: {e}"

    if query:
        # 搜索匹配的记忆并删除
        results = store.search(query, top_k=10, threshold=0.3)
        if not results:
            return f"未找到与「{query}」匹配的记忆"
        # 获取对应的 ID
        try:
            search_results = store.collection.query(
                query_texts=[query],
                n_results=min(10, store.count()),
                include=[],
            )
            ids = search_results["ids"][0] if search_results.get("ids") else []
            if ids:
                store.collection.delete(ids=ids)
                return f"已删除 {len(ids)} 条与「{query}」匹配的记忆"
            return "未找到可删除的记忆"
        except Exception as e:
            return f"批量删除失败: {e}"

    return "请指定 memory_id、session_id 或 query 来决定删除哪些记忆"
