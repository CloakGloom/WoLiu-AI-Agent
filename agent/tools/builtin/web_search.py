"""联网搜索工具（Exa AI Search API）"""

import os
import json
import requests

from agent.config import exa_api_url as _cfg_exa_url
EXA_API_KEY = os.environ.get("EXA_API_KEY", "")
EXA_API_URL = _cfg_exa_url()

SCHEMA = {
    "type": "function",
    "tag": "搜索",
    "function": {
        "name": "web_search",
        "description": "联网搜索最新信息，适用于查询实时新闻、最新动态、未知知识等。返回搜索结果摘要和链接。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或问题，如：今天的热点新闻、Python 3.13 新特性",
                }
            },
            "required": ["query"],
        },
    },
}


def execute(arguments: dict) -> str:
    query = arguments.get("query", "").strip()
    if not query:
        return "请提供搜索关键词"

    try:
        resp = requests.post(
            EXA_API_URL,
            headers={
                "x-api-key": EXA_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "numResults": 5,
                "type": "auto",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if not results:
            return f"未找到与「{query}」相关的结果"

        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "无标题")
            url = r.get("url", "")
            text = r.get("text", r.get("summary", ""))
            date = r.get("publishedDate", "")
            if len(text) > 300:
                text = text[:300] + "..."
            lines.append(f"{i}. {title}")
            if date:
                lines.append(f"   📅 {date[:10]}")
            lines.append(f"   {text}")
            lines.append(f"   🔗 {url}")
            lines.append("")

        return "\n".join(lines).strip()

    except requests.exceptions.Timeout:
        return "搜索超时，请稍后重试"
    except requests.exceptions.RequestException as e:
        return f"搜索失败（网络问题）：{e}"
    except Exception as e:
        return f"搜索失败：{e}"
