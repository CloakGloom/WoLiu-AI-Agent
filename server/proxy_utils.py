"""
反向代理共享工具 —— proxy.py 和 proxy_tts.py 共用
"""
import logging
import httpx
from fastapi import Request
from fastapi.responses import StreamingResponse

# ── 需要从请求中剥离的 hop-by-hop 头（RFC 2616 §13.5.1） ──
HOP_BY_HOP_REQUEST = frozenset({
    "host", "connection", "transfer-encoding", "te", "trailer",
    "upgrade", "proxy-connection", "keep-alive",
})

# ── 不传回客户端的响应头 ──
SKIP_RESPONSE_HEADERS = frozenset({
    "transfer-encoding", "connection", "keep-alive",
})


def filter_headers(headers: dict, skip_set: frozenset) -> dict:
    """过滤掉 hop-by-hop 头，保留其余"""
    return {
        k: v for k, v in headers.items()
        if k.lower() not in skip_set
    }


async def proxy_request(
    request: Request,
    target: str,
    host: str,
    logger_name: str,
    error_service_name: str,
) -> StreamingResponse:
    """通用反向代理处理器。

    Args:
        request: FastAPI Request 对象
        target: 目标 URL
        host: 目标 Host 头（如 "localhost:3000"）
        logger_name: 日志记录器名称
        error_service_name: 错误消息中的服务名称

    Returns:
        StreamingResponse: 流式代理响应
    """
    logger = logging.getLogger(logger_name)
    req_headers = filter_headers(dict(request.headers), HOP_BY_HOP_REQUEST)
    req_headers["host"] = host
    body = await request.body()

    logger.debug(f"[{logger_name}] {request.method} {target}")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            proxy_resp = await client.request(
                method=request.method,
                url=target,
                headers=req_headers,
                content=body,
                follow_redirects=True,
            )
    except httpx.ConnectError:
        return StreamingResponse(
            iter([f"{error_service_name} service is not running".encode()]),
            status_code=503,
            media_type="text/plain",
        )
    except httpx.TimeoutException:
        return StreamingResponse(
            iter([f"{error_service_name} request timed out".encode()]),
            status_code=504,
            media_type="text/plain",
        )
    except Exception as exc:
        logger.error(f"[{logger_name}] error: {exc}")
        return StreamingResponse(
            iter([f"Proxy error: {str(exc)}".encode()]),
            status_code=502,
            media_type="text/plain",
        )

    resp_headers = filter_headers(dict(proxy_resp.headers), SKIP_RESPONSE_HEADERS)

    async def stream_body():
        try:
            async for chunk in proxy_resp.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await proxy_resp.aclose()

    media_type = proxy_resp.headers.get("content-type")

    return StreamingResponse(
        stream_body(),
        status_code=proxy_resp.status_code,
        headers=resp_headers,
        media_type=media_type,
    )
