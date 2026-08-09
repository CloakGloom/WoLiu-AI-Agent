"""
文本分块策略
将对话按轮次分块，每块包含 User + Assistant
"""
from typing import List, Dict
import hashlib
import time

def chunk_conversation(
    user_msg: str,
    assistant_msg: str,
    session_id: str,
    turn_number: int
) -> Dict[str, str]:
    """
    将一轮对话转换为一个文档块
    返回：{"id": "唯一ID", "document": "文本内容", "metadata": {...}}
    """
    document = f"用户说：{user_msg}\nAI回复：{assistant_msg}"

    # 生成唯一ID
    unique_str = f"{session_id}_{turn_number}_{time.time()}"
    doc_id = hashlib.md5(unique_str.encode()).hexdigest()

    metadata = {
        "session_id": session_id,
        "turn_number": turn_number,
        "timestamp": int(time.time())
    }

    return {
        "id": doc_id,
        "document": document,
        "metadata": metadata
    }