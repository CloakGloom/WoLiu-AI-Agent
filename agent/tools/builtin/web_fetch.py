"""网页内容获取工具（Jina Reader API）"""

import os
import requests

from agent.config import jina_reader_url as _cfg_jina
JINA_API_KEY = os.environ.get("JINA_API_KEY", "")
JINA_READER_URL = _cfg_jina()

SCHEMA = {
    "type": "function",
    "tag": "获取",
    "function": {
        "name": "web_fetch",
        "description": "读取指定网页的正文内容，返回干净的文本。适用于需要阅读文章详情、提取网页信息的场景。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要读取的网页链接",
                }
            },
            "required": ["url"],
        },
    },
}


def execute(arguments: dict) -> str:
    url = arguments.get("url", "").strip()
    if not url:
        return "请提供要读取的网页链接"

    # 自动补全协议
    if not url.startswith("http"):
        url = "https://" + url

    try:
        resp = requests.get(
            f"{JINA_READER_URL}/{url}",
            headers={
                "Authorization": f"Bearer {JINA_API_KEY}",
                "Accept": "text/markdown",
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.text.strip()

        if not content:
            return "该网页无有效内容"

        # 截断过长内容
        if len(content) > 8000:
            content = content[:8000] + "\n\n...（内容过长，已截断）"

        return content

    except requests.exceptions.Timeout:
        return "读取超时，请稍后重试"
    except requests.exceptions.RequestException as e:
        return f"读取失败（网络问题）：{e}"
    except Exception as e:
        return f"读取失败：{e}"
