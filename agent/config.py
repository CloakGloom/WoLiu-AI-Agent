"""
统一配置加载器。
启动时自动加载 config.yaml，合并 config.local.yaml 覆盖项，并展开 ${ENV_VAR} 占位符。
所有需要运行时配置的模块都应通过本模块的函数获取配置值，不再硬编码。
"""
import os
import re
from pathlib import Path
from typing import Any
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG: dict[str, Any] = {}
_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")

_SEARCH_FILES = [
    _PROJECT_ROOT / "config.yaml",
    _PROJECT_ROOT / "config.local.yaml",
]


def _resolve_env_vars(value: Any) -> Any:
    """递归展开 ${ENV_VAR} 占位符。"""
    if isinstance(value, str):
        def replacer(m: re.Match) -> str:
            return os.environ.get(m.group(1), m.group(0))
        return _ENV_VAR_RE.sub(replacer, value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(v) for v in value]
    return value


def load(force_reload: bool = False) -> dict[str, Any]:
    global _CONFIG
    if _CONFIG and not force_reload:
        return _CONFIG
    merged: dict[str, Any] = {}
    for path in _SEARCH_FILES:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                _deep_merge(merged, data)
    _CONFIG = _resolve_env_vars(merged)
    return _CONFIG


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def get(key: str, default: Any = None) -> Any:
    """用点号路径获取配置值，如 get('server.port')。"""
    cfg = load()
    parts = key.split(".")
    for part in parts:
        if isinstance(cfg, dict) and part in cfg:
            cfg = cfg[part]
        else:
            return default
    return cfg


# ═══════════════════════════════════════════════════════
# 便捷函数（所有模块统一通过这里获取配置）
# ═══════════════════════════════════════════════════════

def project_root() -> Path:
    return _PROJECT_ROOT


def data_dir() -> Path:
    d = get("project.data_dir", "data")
    p = Path(d)
    return p if p.is_absolute() else _PROJECT_ROOT / p


def output_dir() -> Path:
    d = get("project.output_dir", "converted_files")
    p = Path(d)
    return p if p.is_absolute() else _PROJECT_ROOT / p


def get_python_exe() -> str:
    """返回 Python 可执行文件路径，优先 config.yaml，其次 sys.executable。"""
    exe = get("python.executable", "")
    if exe and not exe.startswith("${"):
        return str(exe) if Path(exe).is_absolute() else str(_PROJECT_ROOT / exe)
    return "python"


def get_base_python() -> str:
    """系统级 Python，用于创建虚拟环境。"""
    exe = get("python.base_python", "")
    if exe and not exe.startswith("${"):
        return exe
    return "python"


# ── Web 服务 ──

def server_host() -> str:
    return str(get("server.host", "0.0.0.0"))


def server_port() -> int:
    return int(get("server.port", 8081))


def ws_port() -> int:
    return int(get("server.ws_port", 8765))


# ── LLM ──

def llm_api_key() -> str:
    return str(get("llm.api_key", os.environ.get("SILICONFLOW_API_KEY", "")))


def llm_base_url() -> str:
    return str(get("llm.base_url", "https://api.siliconflow.cn/v1"))


def llm_model() -> str:
    return str(get("llm.model", "Pro/deepseek-ai/DeepSeek-V3"))


def llm_provider() -> str:
    return str(get("llm.provider", "siliconflow"))


def llm_max_tokens() -> int:
    return int(get("llm.max_tokens", 4096))


def llm_temperature() -> float:
    return float(get("llm.temperature", 0.7))


# ── 视觉模型 ──

def vision_api_key() -> str:
    return str(get("vision.api_key", os.environ.get("VISION_API_KEY", "")))


def vision_base_url() -> str:
    return str(get("vision.base_url", os.environ.get("VISION_BASE_URL", "https://api.openai.com/v1")))


def vision_model() -> str:
    return str(get("vision.model", os.environ.get("VISION_MODEL", "mimo-v2.5")))


# ── ComfyUI ──

def comfyui_url() -> str:
    s = get("services.comfyui", {})
    return f"http://{s.get('host', '127.0.0.1')}:{s.get('port', 8188)}"


def comfyui_enabled() -> bool:
    return bool(get("services.comfyui.enabled", True))


# ── TTS ──

def tts_url() -> str:
    t = get("services.tts.type", "chattts")
    if t == "confucius4":
        s = get("services.tts.confucius4", {})
        return f"http://{s.get('host', '127.0.0.1')}:{s.get('port', 8000)}"
    s = get("services.tts.chattts", {})
    return f"http://{s.get('host', '127.0.0.1')}:{s.get('port', 8001)}"


def tts_enabled() -> bool:
    return bool(get("services.tts.enabled", False))


# ── Ollama ──

def ollama_url() -> str:
    s = get("services.ollama", {})
    return f"http://{s.get('host', '127.0.0.1')}:{s.get('port', 11434)}"


def ollama_exe() -> str:
    return str(get("services.ollama.executable", ""))


def ollama_models_dir() -> str:
    return str(get("services.ollama.models_dir", ""))


def ollama_port() -> int:
    return int(get("services.ollama.port", 11434))


def ollama_vision_model() -> str:
    return str(get("services.ollama.vision_model", "qwen3-vl:4b"))


def ollama_enabled() -> bool:
    return bool(get("services.ollama.enabled", False))


# ── JadeAI ──

def jadeai_url() -> str:
    s = get("services.jadeai", {})
    return f"http://{s.get('host', '127.0.0.1')}:{s.get('port', 3000)}"


def jadeai_enabled() -> bool:
    return bool(get("services.jadeai.enabled", False))


# ── 微信桥接 ──

def weixin_enabled() -> bool:
    return bool(get("services.weixin_bridge.enabled", True))


def weixin_proxy_port() -> int:
    return int(get("services.weixin_bridge.proxy_port", 17890))


# ── 迁移 ──

def migrate_timeout() -> int:
    return int(get("migration.timeout_seconds", 5))


# ── HF 镜像 ──

def hf_endpoint() -> str:
    return str(get("apis.huggingface_mirror", "https://hf-mirror.com"))


# ── 外部 API URL ──

def exa_api_url() -> str:
    return str(get("apis.exa_search", "https://api.exa.ai/search"))


def jina_reader_url() -> str:
    return str(get("apis.jina_reader", "https://r.jina.ai"))


def weather_api_url() -> str:
    return str(get("apis.weather", "https://uapis.cn/api/v1/misc/weather"))


# ── 微信 ──

def weixin_ilink_base() -> str:
    return str(get("weixin.ilink_base", "https://ilinkai.weixin.qq.com"))


def weixin_cdn_base() -> str:
    return str(get("weixin.cdn_base", "https://novac2c.cdn.weixin.qq.com/c2c"))


# ── 模型下载 ──

def model_url_minimax_h3() -> str:
    return str(get("models.minimax_h3", "https://huggingface.co/Comfy-Org/MiniMax-H3"))


def model_url_z_image_turbo(part: str = "unet") -> str:
    return str(get(f"models.z_image_turbo.{part}", ""))


# ── 外部工具搜索 ──

def find_external_tool(keys: list[str]) -> str | None:
    """按顺序在 external.xxx_paths 中搜索第一个存在的可执行文件。"""
    for key in keys:
        candidates = get(f"external.{key}", [])
        if isinstance(candidates, list):
            for p in candidates:
                if Path(p).exists():
                    return p
    return None


def find_ffmpeg() -> str | None:
    return find_external_tool(["ffmpeg_paths"])


def find_pdflatex() -> str | None:
    return find_external_tool(["latex_paths"])


def find_mpv() -> str | None:
    return find_external_tool(["mpv_paths"])


def find_node() -> str | None:
    return find_external_tool(["node_paths"])


def find_ncm_cli() -> str | None:
    return find_external_tool(["ncm_cli_paths"])


def modelscope_cache_dir() -> str:
    return str(get("external.modelscope_cache", "D:/Downloads/models"))


# ── 自启动 ──

def autostart(service: str) -> bool:
    return bool(get(f"autostart.{service}", False))


# ── 生成参数 ──

def video_timeout() -> int:
    return int(get("generation.video_timeout", 1800))


# ── WebSocket 设备标识 ──

def device_pc() -> str:
    return "pc"


def device_mobile() -> str:
    return "mobile"


# ── Torch lib 路径 ──

def torch_lib_path() -> str:
    p = get("python.torch_lib", "")
    if p:
        return p
    # 自动检测
    try:
        import torch
        lib_dir = Path(torch.__file__).parent / "lib"
        if lib_dir.exists():
            return str(lib_dir)
    except Exception:
        pass
    return ""


# 启动时加载
load()
