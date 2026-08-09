"""
检索器：封装检索逻辑，返回格式化结果
"""
from typing import List
from .vector_store import VectorStore
from .config import get_rag_config

class Retriever:
    def __init__(self):
        self.store = VectorStore()
        self.config = get_rag_config()

    def retrieve(self, query: str, session_id: str = None) -> List[str]:
        """
        检索相关记忆，返回格式化文本列表
        """
        top_k = self.config.get("top_k", 3)
        threshold = self.config.get("threshold", 0.6)

        results = self.store.search(query, top_k=top_k, threshold=threshold)

        if not results:
            return []

        # 格式化返回
        formatted = []
        for item in results:
            text = item["document"]
            formatted.append(text)

        return formatted

    def store_conversation(self, session_id: str, user_msg: str, assistant_msg: str, turn_number: int = None):
        """
        存储一轮对话到向量库
        """
        import time
        if turn_number is None:
            turn_number = int(time.time() % 100000)

        from .chunker import chunk_conversation
        chunk = chunk_conversation(user_msg, assistant_msg, session_id, turn_number)
        self.store.add(chunk["id"], chunk["document"], chunk["metadata"])