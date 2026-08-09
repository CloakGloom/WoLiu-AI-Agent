"""
agent.mcp_server.resources —— MCP Resources 资源端点

暴露可被 LLM 直接读取的结构化数据:
- 论文模板 (LaTeX / Markdown)
- 系统配置快照
- 会话记忆摘要
- 工具模块源码
- 项目目录结构
"""

import json
import os


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def register_resources(mcp):
    """将 Resources 注册到 FastMCP 实例"""

    root = _project_root()

    # ── 1. 论文 LaTeX 模板 ──
    @mcp.resource(
        uri="paper://templates/academic",
        name="学术论文模板",
        description="标准学术论文 LaTeX 模板，含标题/摘要/章节/参考文献结构",
        mime_type="text/x-latex",
    )
    def academic_paper_template() -> str:
        return r"""\documentclass[12pt,a4paper]{article}
\usepackage[UTF8]{ctex}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{hyperref}
\usepackage{booktabs}

\title{论文标题}
\author{作者}
\date{\today}

\begin{document}
\maketitle

\begin{abstract}
在此撰写摘要，概述研究背景、方法、主要结果和结论。
\end{abstract}

\section{引言}
研究背景与意义...

\section{相关工作}
前人研究成果...

\section{方法}
研究方法与技术路线...

\section{实验}
实验设置与结果分析...

\section{结论}
总结与展望...

\bibliographystyle{plain}
\bibliography{references}
\end{document}"""

    @mcp.resource(
        uri="paper://templates/markdown",
        name="Markdown 论文模板",
        description="轻量级 Markdown 论文模板，适合快速草稿和 AI 辅助写作",
        mime_type="text/markdown",
    )
    def markdown_paper_template() -> str:
        return """# 论文标题

> **作者** | **日期**

## 摘要

本文研究了...

**关键词**：关键字1, 关键字2, 关键字3

---

## 1 引言

研究背景与动机...

## 2 相关工作

### 2.1 子领域一

### 2.2 子领域二

## 3 方法

### 3.1 整体架构

### 3.2 核心算法

## 4 实验

| 方法 | 指标1 | 指标2 |
|------|-------|-------|
| Baseline | 0.85 | 0.72 |
| Ours | 0.92 | 0.81 |

## 5 结论

## 参考文献

[1] Author. Title. Venue, Year.
"""

    # ── 2. 系统配置资源 ──
    @mcp.resource(
        uri="config://system",
        name="系统配置",
        description="当前 AI Agent 运行配置（脱敏）",
        mime_type="application/json",
    )
    def system_config() -> str:
        """返回脱敏后的系统配置"""
        try:
            import yaml
            config_path = os.path.join(root, "config.yaml")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                # 脱敏：移除 API key
                _redact(data, ["api_key", "password", "secret", "token"])
                return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e), "note": "配置读取失败"})
        return json.dumps({"note": "config.yaml 不存在"})

    @mcp.resource(
        uri="config://tools",
        name="工具清单",
        description="当前启用的所有工具列表（含来源与参数）",
        mime_type="application/json",
    )
    def tools_manifest() -> str:
        """返回工具清单"""
        try:
            from agent.mcp_client import get_manager
            mgr = get_manager()
            return json.dumps(mgr.list_all_tools(), ensure_ascii=False, indent=2)
        except Exception:
            from agent.tools import get_tool_registry
            items = []
            for t in get_tool_registry():
                items.append({
                    "name": t["name"],
                    "tag": t["tag"],
                    "source": "local",
                })
            return json.dumps(items, ensure_ascii=False, indent=2)

    # ── 3. 记忆资源 ──
    @mcp.resource(
        uri="memory://session/{session_id}",
        name="会话记忆摘要",
        description="指定会话的长期记忆摘要（RAG 检索结果）",
        mime_type="application/json",
    )
    def session_memory(session_id: str) -> str:
        """返回会话记忆摘要"""
        try:
            from agent.memory.long_term import retrieve_context
            chunks = retrieve_context("", session_id, top_k=10)
            return json.dumps({
                "session_id": session_id,
                "chunks": chunks,
                "count": len(chunks),
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e), "session_id": session_id})

    @mcp.resource(
        uri="memory://stats",
        name="记忆统计",
        description="ChromaDB 长期记忆存储统计信息",
        mime_type="application/json",
    )
    def memory_stats() -> str:
        """记忆统计"""
        try:
            from agent.memory.long_term import _get_retriever
            retriever = _get_retriever()
            return json.dumps({
                "total_documents": retriever.collection.count() if retriever else 0,
            })
        except Exception as e:
            return json.dumps({"error": str(e), "note": "记忆系统未初始化"})

    # ── 4. 工具源码资源 ──
    @mcp.resource(
        uri="tools://source/{tool_name}",
        name="工具源码",
        description="指定工具的 Python 源码（只读）",
        mime_type="text/x-python",
    )
    def tool_source(tool_name: str) -> str:
        """返回工具源码"""
        try:
            from agent.tools import get_tool_registry
            for t in get_tool_registry():
                if t["name"] == tool_name:
                    mod = t.get("execute", None)
                    if mod and hasattr(mod, "__globals__"):
                        f = mod.__globals__.get("__file__", "")
                    elif hasattr(mod, "__code__"):
                        f = getattr(mod.__code__, "co_filename", "")
                    else:
                        f = ""
                    if f and os.path.exists(f):
                        with open(f, "r", encoding="utf-8") as src:
                            return src.read()
                    return f"# 源码文件未找到: {tool_name}"
            return f"# 工具 '{tool_name}' 不在注册表中"
        except Exception as e:
            return f"# 错误: {e}"

    # ── 5. 项目结构资源 ──
    @mcp.resource(
        uri="project://structure",
        name="项目目录结构",
        description="AI Agent 项目的目录结构概览（agent/, server/, tools/ 等）",
        mime_type="application/json",
    )
    def project_structure() -> str:
        """返回项目结构"""
        dirs = ["agent", "server", "client", "config", "tools", "side-projects", "data"]
        result = {}
        for d in dirs:
            p = os.path.join(root, d)
            if os.path.isdir(p):
                items = os.listdir(p)
                result[d] = [i for i in sorted(items) if not i.startswith(".")][:20]
                if len(items) > 20:
                    result[d].append(f"... 及 {len(items) - 20} 项")
        return json.dumps(result, ensure_ascii=False, indent=2)

    print(f"[MCP] Resources 已注册", file=__import__('sys').stderr)


def _redact(data, keys_to_hide, parent_key=""):
    """递归隐藏敏感字段"""
    if isinstance(data, dict):
        for k, v in list(data.items()):
            if any(sensitive in k.lower() for sensitive in keys_to_hide):
                data[k] = "***REDACTED***"
            elif isinstance(v, (dict, list)):
                _redact(v, keys_to_hide, k)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                _redact(item, keys_to_hide, parent_key)
