"""
ChromaDB 向量存储封装
"""
import os
import chromadb
from chromadb.config import Settings
from typing import List, Dict, Optional
from .embedder import Embedder
from .config import get_rag_config

class VectorStore:
    def __init__(self):
        config = get_rag_config()
        self.collection_name = config.get("collection_name", "agent_memory")
        self.embedder = Embedder()

        # 持久化目录
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        persist_dir = os.path.join(base_dir, "data", "memory_store", "chroma_db")
        os.makedirs(persist_dir, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False)
        )

        # 获取或创建 collection
        self.collection = self._get_or_create_collection()

    def _get_or_create_collection(self):
        """获取或创建 collection"""
        try:
            return self.client.get_collection(self.collection_name)
        except Exception:
            return self.client.create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}
            )

    def add(self, doc_id: str, document: str, metadata: Dict):
        """插入单条文档（使用 upsert 避免重复 ID 错误）"""
        embedding = self.embedder.encode(document)
        if not embedding:
            return

        self.collection.upsert(
            ids=[doc_id],
            documents=[document],
            embeddings=[embedding],
            metadatas=[metadata]
        )

    def add_batch(self, documents: List[Dict]):
        """批量插入文档"""
        if not documents:
            return

        ids = [d["id"] for d in documents]
        docs = [d["document"] for d in documents]
        metadatas = [d["metadata"] for d in documents]
        embeddings = self.embedder.encode_batch(docs)

        self.collection.upsert(
            ids=ids,
            documents=docs,
            embeddings=embeddings,
            metadatas=metadatas
        )

    def search(self, query: str, top_k: int = 3, threshold: float = 0.6) -> List[Dict]:
        """
        检索最相似的文档片段
        返回：[{"document": "...", "metadata": {...}, "distance": 0.3}]
        """
        query_embedding = self.embedder.encode(query)
        if not query_embedding:
            return []

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"]
        )

        if not results["ids"] or not results["ids"][0]:
            return []

        items = []
        for i, doc_id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i] if results["distances"] else 1.0
            # 距离越小越相似，用 (1 - distance) 转为相似度
            similarity = 1 - distance if distance <= 1 else 0
            if similarity >= threshold:
                items.append({
                    "document": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "similarity": similarity
                })

        return items

    def delete_by_session(self, session_id: str):
        """删除指定会话的所有记忆"""
        self.collection.delete(where={"session_id": session_id})

    def count(self) -> int:
        """获取记忆总数"""
        return self.collection.count()