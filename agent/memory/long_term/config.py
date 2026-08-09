"""
RAG模块配置
从 config/rules_config.json 读取
"""
import json
import os

DEFAULT_CONFIG = {
    "rag": {
        "enabled": True,
        "top_k": 3,
        "threshold": 0.3,
        "min_turns_before_retrieval": 10,
        "collection_name": "agent_memory",
        "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2"
    }
}

def get_rag_config():
    """读取RAG配置，如文件不存在则使用默认值"""
    # agent/memory/long_term/config.py -> agent/memory/long_term -> agent/memory -> agent -> project_root
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    config_path = os.path.join(base_dir, "config", "rules_config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("rag", DEFAULT_CONFIG["rag"])
    return DEFAULT_CONFIG["rag"]