"""
长期记忆模块 —— RAG（检索增强生成）
基于 ChromaDB + sentence-transformers 实现跨会话历史信息检索

对外接口：
    retrieve_context(query, session_id) -> list[str]  检索相关记忆
    store_conversation(session_id, user_msg, assistant_msg)  存储对话
    get_memory_count() -> int  获取记忆总数
"""

from .retriever import Retriever
from .config import get_rag_config

# 全局单例（延迟初始化，避免首次 import 就加载模型）
_retriever = None

def _get_retriever() -> Retriever:
    """延迟初始化检索器"""
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever


def retrieve_context(query: str, session_id: str = None) -> list:
    """
    检索与查询相关的历史对话片段
    返回格式化文本列表，每条格式为 "用户说：xxx\nAI回复：xxx"
    """
    return _get_retriever().retrieve(query, session_id)


def store_conversation(session_id: str, user_msg: str, assistant_msg: str):
    """
    存储一轮对话到向量库（长期记忆）
    """
    _get_retriever().store_conversation(session_id, user_msg, assistant_msg)


def get_memory_count() -> int:
    """获取当前记忆总数"""
    return _get_retriever().store.count()