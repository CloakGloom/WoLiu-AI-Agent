"""
共享配置 —— 电脑端和手机端通用
敏感信息通过 .env 文件注入，不写入代码
"""

import os

# 确保 .env 被加载（无论从哪个入口启动）
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
except ImportError:
    pass

# ==================== LLM API 配置 ====================
API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
API_BASE_URL = os.environ.get("API_BASE_URL", "https://api.openai.com/v1").strip()
MODEL_NAME = os.environ.get("MODEL_NAME", "deepseek-v4-flash-200k")

# ==================== WebSocket 服务器配置 ====================
WS_HOST = "0.0.0.0"
try:
    from agent.config import ws_port as _cfg_ws_port, migrate_timeout as _cfg_migrate_to
    WS_PORT = _cfg_ws_port()
except Exception:
    WS_PORT = 8765

# ==================== 设备标识 ====================
DEVICE_PC = "pc"
DEVICE_MOBILE = "mobile"

# ==================== 视觉分析 API 配置（拍照分析） ====================
VISION_API_KEY = os.environ.get("VISION_API_KEY", "").strip()
VISION_BASE_URL = os.environ.get("VISION_BASE_URL", "https://api.openai.com/v1").strip()
VISION_MODEL = os.environ.get("VISION_MODEL", "mimo-v2.5")

# ==================== 迁移超时（秒） ====================
try:
    MIGRATE_TIMEOUT = _cfg_migrate_to()
except Exception:
    MIGRATE_TIMEOUT = 5