"""
Confucius4-TTS 反向代理模块
将 FastAPI 的 /tts/* 路径请求透明转发到 Confucius4-TTS 服务（localhost:8000）。

与 JadeAI 代理 (server/proxy.py) 共用 proxy_utils 架构模式：
- 全 HTTP 方法支持
- 流式响应兼容（/api/tts/stream 返回原始 PCM）
- 请求/响应头正确转发
- TTS 未就绪时返回 503
"""
import os as _os
from fastapi import Request
from server.proxy_utils import proxy_request
from agent.config import tts_url as _cfg_tts

TTS_BASE = _cfg_tts()

TTS_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                         "side-projects", "Confucius4-TTS")
TTS_PYTHON = _os.path.join(TTS_DIR, "python", "python.exe")


async def proxy_to_tts(request: Request, path: str):
    """FastAPI 路由处理器：反向代理请求到 Confucius4-TTS。

    挂在 /tts/{path:path} 上，所有 /tts/* 请求由此转发。

    Args:
        request: FastAPI Request 对象
        path: /tts/ 之后的路径部分，空字符串表示 /tts 或 /tts/
    """
    query_string = request.url.query if request.url.query else ""
    target = f"{TTS_BASE}/{path}" if path else f"{TTS_BASE}/"
    if query_string:
        target += f"?{query_string}"
    return await proxy_request(request, target, "localhost:8000", "tts-proxy", "Confucius4-TTS")
