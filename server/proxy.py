"""
JadeAI 反向代理模块
将 FastAPI 的 /jade/* 路径请求透明转发到 JadeAI Next.js 服务（localhost:3000）。

特性：
- 全 HTTP 方法支持（GET/POST/PUT/DELETE/PATCH/OPTIONS/HEAD）
- 流式响应兼容（SSE 事件流 → 用于 AI 对话）
- 二进制文件传输（PDF 导出）
- 请求头/响应头正确转发（剥离 hop-by-hop 头）
- 查询参数原样透传
- JadeAI 未就绪时返回 503，超时返回 504

内部端口约定：
- JadeAI（Next.js dev / production）监听 localhost:3000
- FastAPI（我流 Agent）监听 0.0.0.0:8765，对外暴露 /jade/
- 使用 Next.js basePath="/jade"，路径无需重写
"""
from fastapi import Request
from server.proxy_utils import proxy_request
from agent.config import jadeai_url as _cfg_jadeai

# JadeAI Next.js 内部服务地址
JADEAI_BASE = _cfg_jadeai()


def _build_target(path: str, query_string: str) -> str:
    """构造 JadeAI 目标 URL。

    示例：
      path="", query=""  → http://localhost:3000/jade/
      path="dashboard", query=""  → http://localhost:3000/jade/dashboard
      path="api/resume", query="id=1" → http://localhost:3000/jade/api/resume?id=1
    """
    base = f"{JADEAI_BASE}/jade"
    target = f"{base}/{path}" if path else f"{base}/"
    if query_string:
        target += f"?{query_string}"
    return target


async def proxy_to_jade(request: Request, path: str):
    """FastAPI 路由处理器：反向代理请求到 JadeAI。

    Args:
        request: FastAPI Request 对象
        path: /jade/ 之后的路径部分（不含前导斜杠），空字符串表示 /jade 或 /jade/
    """
    query_string = request.url.query if request.url.query else ""
    target = _build_target(path, query_string)
    return await proxy_request(request, target, "localhost:3000", "jade-proxy", "JadeAI")
