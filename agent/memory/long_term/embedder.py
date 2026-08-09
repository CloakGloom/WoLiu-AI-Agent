"""
Embedding 模型封装
将文本转换为向量
"""
import os
from sentence_transformers import SentenceTransformer
from .config import get_rag_config

class Embedder:
    def __init__(self):
        config = get_rag_config()
        model_name = config.get("embedding_model", "paraphrase-multilingual-MiniLM-L12-v2")
        # 优先使用本地缓存，避免 HuggingFace 网络问题
        self.model = SentenceTransformer(
            model_name,
            local_files_only=os.environ.get("HF_HUB_OFFLINE", "1") == "1"
        )
        self.dimension = self.model.get_embedding_dimension()

    def encode(self, text: str) -> list:
        """将单条文本转换为向量"""
        if not text or not text.strip():
            return []
        return self.model.encode(text).tolist()

    def encode_batch(self, texts: list) -> list:
        """批量转换"""
        if not texts:
            return []
        return self.model.encode(texts).tolist()

    def get_dimension(self) -> int:
        return self.dimension