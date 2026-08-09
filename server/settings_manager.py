"""
系统设置管理器 —— 读写独立的 config/settings.json
密钥安全：所有 api_key 字段自动写入 .env，settings.json 永远不存真实密钥。
设置保存时自动同步 .env，加载时从 .env 回注。
"""

import json, os, re
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from agent.config import project_root

SETTINGS_FILE = project_root() / "config" / "settings.json"
ENV_FILE      = project_root() / ".env"

# ── api_key 字段到环境变量的映射 ──
# 格式：section.field → ENV_VAR_NAME
_KEY_MAP = {
    "llm.api_key":          "LLM_API_KEY",
    "vision.api_key":       "VISION_API_KEY",
    "ai_painting.api_key":  "AI_PAINTING_API_KEY",
    "search.api_key":       "SEARCH_API_KEY",
    "web_loader.api_key":   "WEB_LOADER_API_KEY",
    "tts.api_key":          "TTS_API_KEY",
}

_DEFAULTS: dict[str, Any] = {
    "llm": {
        "provider": "siliconflow",
        "api_key": "",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro",
        "temperature": 0.7,
        "max_tokens": 4096,
    },
    "vision": {
        "api_key": "",
        "base_url": "",
        "model": "",
    },
    "memory": {
        "enabled": True,
        "chromadb_path": "data/chroma_db",
        "embedding_model": "BAAI/bge-m3",
        "max_entries": 100,
    },
    "generation": {
        "image_to_video_width": 1024,
        "image_to_video_height": 576,
        "text_to_video_width": 1024,
        "text_to_video_height": 576,
        "video_fps": 24,
        "timeout_seconds": 120,
    },
    "tools": {},
    "files": {
        "max_upload_size_mb": 100,
        "allowed_extensions": [
            "txt", "pdf", "docx", "pptx", "xlsx", "csv",
            "png", "jpg", "jpeg", "gif", "webp",
            "mp3", "wav", "mp4", "webm",
            "zip", "rar", "7z",
            "py", "js", "html", "css", "json", "xml", "yaml", "yml", "toml", "md",
        ],
        "output_dir": "converted_files",
        "data_dir": "data",
    },
    "network": {
        "host": "0.0.0.0",
        "http_port": 8000,
        "ws_port": 8001,
        "cors_origins": ["*"],
        "search_api_url": "",
        "mcp_enabled": False,
    },
    "logging": {
        "level": "INFO",
        "directory": "logs",
        "max_files": 30,
    },
    "ai_painting": {
        "provider": "siliconflow",
        "api_key": "",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "stabilityai/stable-diffusion-3.5-large",
    },
    "search": {
        "provider": "tavily",
        "api_key": "",
        "base_url": "https://api.tavily.com/search",
    },
    "web_loader": {
        "provider": "jina",
        "api_key": "",
        "base_url": "https://r.jina.ai",
    },
    "tts": {
        "provider": "siliconflow",
        "api_key": "",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "FunAudioLLM/CosyVoice2-0.5B",
    },
}


# ═══════════════════════════════════════════════════════════
#  .env 读写
# ═══════════════════════════════════════════════════════════

def _read_env() -> dict[str, str]:
    """读取 .env 中的键值对"""
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        return env
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r'^([A-Za-z_]\w+)\s*=\s*(.*)', line)
                if m:
                    env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except Exception:
        pass
    return env


def _write_env_key(env_var: str, value: str):
    """写入或更新 .env 中某个 KEY=VALUE"""
    if not value:
        # 空值 → 把 KEY= 写入空值行，不删掉
        pass

    lines: list[str] = []
    if ENV_FILE.exists():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    else:
        lines = []

    found = False
    for i, line in enumerate(lines):
        m = re.match(rf'^({re.escape(env_var)}\s*=\s*).*', line.strip(), re.IGNORECASE)
        if m:
            lines[i] = f"{env_var}={value}\n" if value else f"# {env_var}=\n"
            found = True
            break

    if not found and value:
        lines.append(f"{env_var}={value}\n")

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _delete_env_key(env_var: str):
    """从 .env 中删除指定 KEY 行"""
    if not ENV_FILE.exists():
        return
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    lines = [l for l in lines if not re.match(rf'^{re.escape(env_var)}\s*=', l.strip(), re.IGNORECASE)]
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)


# ═══════════════════════════════════════════════════════════
#  公共 API
# ═══════════════════════════════════════════════════════════

def _ensure_file() -> None:
    if not SETTINGS_FILE.exists():
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        cleaned = _strip_keys(deepcopy(_DEFAULTS))
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, indent=2, ensure_ascii=False)


def load_all() -> dict[str, Any]:
    """读取完整设置：settings.json + .env 注入密钥"""
    _ensure_file()
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    merged = _deep_merge(deepcopy(_DEFAULTS), data)
    _inject_from_env(merged)
    return merged


def update(data: dict[str, Any]) -> dict[str, Any]:
    """批量更新设置，自动同步 .env"""
    current = load_all()
    _shallow_merge(current, data)
    _split_save(current)
    return current


def reset() -> dict[str, Any]:
    """恢复默认：清空 settings.json 和 .env 中的 KEY"""
    cleaned = _strip_keys(deepcopy(_DEFAULTS))
    _save(cleaned)
    for env_var in _KEY_MAP.values():
        _delete_env_key(env_var)
    return deepcopy(_DEFAULTS)


def export_yaml() -> str:
    current = load_all()
    safe = _strip_keys(current)
    return yaml.dump(safe, allow_unicode=True, default_flow_style=False, sort_keys=False)


def import_yaml(yaml_str: str) -> dict[str, Any]:
    try:
        imported = yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        raise ValueError(f"YAML 解析失败：{e}")
    if not isinstance(imported, dict):
        raise ValueError("YAML 内容必须是键值对字典")
    safe = _strip_keys(deepcopy(imported))
    current = load_all()
    _shallow_merge(current, safe)
    _split_save(current)
    return current


def get_defaults() -> dict[str, Any]:
    return deepcopy(_DEFAULTS)


# ═══════════════════════════════════════════════════════════
#  内部
# ═══════════════════════════════════════════════════════════

def _save(data: dict[str, Any]) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _split_save(data: dict[str, Any]):
    """保存：api_key → .env，其余 → settings.json（空 key）"""
    safe = deepcopy(data)
    for section, content in list(safe.items()):
        if isinstance(content, dict) and "api_key" in content:
            env_var = _KEY_MAP.get(f"{section}.api_key")
            if env_var:
                val = content.get("api_key", "")
                _write_env_key(env_var, val)
            content["api_key"] = ""  # settings.json 永远不存
    _save(safe)


def _strip_keys(data: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(data)
    for section, content in result.items():
        if isinstance(content, dict) and "api_key" in content:
            content["api_key"] = ""
    return result


def _inject_from_env(data: dict[str, Any]):
    env = _read_env()
    for section_field, env_var in _KEY_MAP.items():
        if env_var in env and env[env_var]:
            section, field = section_field.split(".", 1)
            if section in data and isinstance(data[section], dict):
                data[section][field] = env[env_var]


def _deep_merge(base: dict, override: dict) -> dict:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _shallow_merge(base: dict, override: dict) -> dict:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            base[k] = v
        else:
            base[k] = v
    return base
