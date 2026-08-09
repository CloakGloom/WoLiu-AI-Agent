"""
上下文回溯工具 —— 当用户说"结合之前的XX"时，让 AI 能翻看历史记录和已生成文档
"""
import os
import json
import re
from agent import database

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
PAPERS_DIR = os.path.join(ROOT, "data", "papers")
OUTPUT_DIR = os.path.join(ROOT, "server", "static", "papers")

SCHEMA = {
    "type": "function",
    "tag": "搜索",
    "function": {
        "name": "recall_context",
        "description": "查找历史对话或已生成文档。需要之前成果时使用，keyword 为搜索词，source 为来源（auto/history/documents）。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，如'热点''论文''AI''2025'等。用尽可能简短的关键词。"
                },
                "source": {
                    "type": "string",
                    "enum": ["auto", "history", "documents"],
                    "description": "搜索来源：auto=自动搜索全部，history=只看历史对话中的搜索结果和AI回复，documents=只看已生成的论文/文档文件。默认 auto。"
                }
            },
            "required": ["query"]
        }
    }
}


def execute(arguments: dict) -> str:
    query = arguments.get("query", "").strip()
    source = arguments.get("source", "auto")

    if not query:
        return "请提供搜索关键词（query 参数）。"

    results = []

    if source in ("auto", "history"):
        history_results = _search_history(query)
        if history_results:
            results.append(history_results)

    if source in ("auto", "documents"):
        doc_results = _search_documents(query)
        if doc_results:
            results.append(doc_results)

    if not results:
        return f"未找到与「{query}」相关的历史内容或文档。请尝试更具体的关键词。"

    return "\n\n".join(results)


def _search_history(query: str) -> str:
    """搜索当前会话的消息历史，提取搜索结果和 AI 回复"""
    sessions = database.get_active_sessions()
    if not sessions:
        return ""

    session_id = sessions[0]["session_id"]
    messages = database.get_all_messages(session_id)
    if not messages:
        return ""

    keywords = query.lower().split()
    matched = []

    for m in messages:
        if m["role"] == "tool":
            content = m.get("content", "")
            if content and len(content) > 50:
                # 跳过 recall_context 自身的输出，避免递归自我引用
                if content.startswith("## 历史对话中与「") or content.startswith("## 已生成的文档中与「"):
                    continue
                for kw in keywords:
                    if kw in content.lower():
                        matched.append(_truncate(content, 3000))
                        break
        elif m["role"] == "assistant":
            content = m.get("content", "")
            if content and not m.get("tool_calls"):
                for kw in keywords:
                    if kw in content.lower():
                        matched.append(_truncate(content, 2000))
                        break

    if not matched:
        return ""

    lines = [f"## 历史对话中与「{query}」相关的内容\n"]
    for i, item in enumerate(matched, 1):
        lines.append(f"### 匹配项 {i}\n{item}\n")

    return "\n".join(lines)


def _search_documents(query: str) -> str:
    """搜索已生成的论文和文档文件"""
    found = []
    seen_names = set()  # 按基础文件名去重（跨 data/papers 和 server/static/papers）

    for d in [PAPERS_DIR, OUTPUT_DIR]:
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            fpath = os.path.join(d, fname)
            if not os.path.isfile(fpath):
                continue
            # 文件名匹配
            if query.lower() in fname.lower():
                base_name = os.path.splitext(fname)[0]
                if base_name in seen_names:
                    continue
                seen_names.add(base_name)
                ext = os.path.splitext(fname)[1].lower()
                if ext == ".md":
                    content = _read_text_file(fpath)
                    found.append(f"### 文件: {fname}\n```markdown\n{_truncate(content, 4000)}\n```")
                elif ext == ".tex":
                    content = _read_text_file(fpath)
                    found.append(f"### 文件: {fname}\n```latex\n{_truncate(content, 4000)}\n```")
                elif ext == ".pdf":
                    found.append(f"### 文件: {fname}\n（PDF 文件，{_file_size(fpath)}，路径: {d}\\{fname}）")
                elif ext == ".pptx":
                    found.append(f"### 文件: {fname}\n（PPT 文件，{_file_size(fpath)}，路径: {d}\\{fname}）")
                elif ext == ".docx":
                    found.append(f"### 文件: {fname}\n（Word 文件，{_file_size(fpath)}，路径: {d}\\{fname}）")

    if not found:
        return ""

    return "## 已生成的文档中与「" + query + "」匹配的文件\n\n" + "\n\n".join(found)


def _read_text_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        try:
            with open(path, "r", encoding="gbk") as f:
                return f.read()
        except Exception:
            return f"（无法读取文件内容: {path}）"


def _file_size(path: str) -> str:
    size = os.path.getsize(path)
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n\n...（内容过长，已截断，可指定更精确的关键词获取完整内容）"