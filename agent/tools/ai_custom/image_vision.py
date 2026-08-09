"""图片视觉分析工具（拍照后调用 mimo-v2.5 视觉模型分析图片内容）"""

import base64
import requests
from config import VISION_API_KEY, VISION_BASE_URL, VISION_MODEL

SCHEMA = {
    "type": "function",
    "function": {
        "name": "analyze_image",
        "description": "分析图片内容，返回图片的详细描述。当用户上传图片或拍照后需要分析图片内容时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "image_url": {
                    "type": "string",
                    "description": "图片的完整URL地址，例如 http://192.168.1.100:5000/uploads/xxx.jpg",
                },
                "question": {
                    "type": "string",
                    "description": "对图片的具体问题，默认为'请详细描述这张图片的内容'",
                },
            },
            "required": ["image_url"],
        },
    },
}


def _download_image(image_url: str) -> tuple:
    """下载图片并转为 base64 data URL，返回 (data_url, error)"""
    try:
        resp = requests.get(image_url, timeout=15)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        b64 = base64.b64encode(resp.content).decode("utf-8")
        return f"data:{content_type};base64,{b64}", None
    except requests.exceptions.Timeout:
        return None, "下载图片超时"
    except requests.exceptions.ConnectionError:
        return None, "无法连接到图片服务器"
    except Exception as e:
        return None, f"下载图片失败：{str(e)}"


def execute(arguments: dict) -> str:
    """调用视觉模型分析图片"""
    image_url = arguments.get("image_url", "").strip()
    question = arguments.get("question", "请详细描述这张图片的内容").strip()

    if not image_url:
        return "错误：未提供图片URL"

    if not VISION_API_KEY:
        return "错误：未配置视觉分析API密钥，请在.env中设置VISION_API_KEY"

    # 下载图片转 base64（避免外部API无法访问局域网URL）
    data_url, error = _download_image(image_url)
    if error:
        return f"错误：{error}"

    headers = {
        "Authorization": f"Bearer {VISION_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "max_tokens": 1000,
    }

    try:
        resp = requests.post(
            f"{VISION_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content
    except requests.exceptions.Timeout:
        return "错误：视觉分析请求超时，请重试"
    except requests.exceptions.ConnectionError:
        return "错误：无法连接到视觉分析API，请检查网络"
    except requests.exceptions.HTTPError as e:
        try:
            detail = resp.json()
            return f"错误：视觉分析API返回错误（{resp.status_code}）：{detail}"
        except Exception:
            return f"错误：视觉分析API返回错误（{resp.status_code}）"
    except Exception as e:
        return f"错误：视觉分析失败：{str(e)}"