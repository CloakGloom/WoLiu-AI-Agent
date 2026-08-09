"""
agent.mcp_server.prompts —— MCP Prompts 提示模板

标准化常用场景的 Prompt 模板，LLM 客户端可动态选择/组合:
- 代码审查
- 论文写作
- PPT 大纲生成
- 日报/周报
- 功能开发文档
"""

import json
import os


def register_prompts(mcp):
    """将 Prompts 注册到 FastMCP 实例"""

    # ── 1. 代码审查 ──
    @mcp.prompt(
        name="code_review",
        description="代码审查 —— 检查正确性/性能/安全/最佳实践",
    )
    def prompt_code_review(code: str, language: str = "python") -> list[dict]:
        return [
            {
                "role": "system",
                "content": (
                    f"你是一位资深的 {language} 代码审查专家。请对以下代码进行全面审查。"
                    "使用以下评分标准: 优秀(90+)/良好(75-89)/需改进(<75)"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"请审查以下 {language} 代码:\n\n```{language}\n{code}\n```\n\n"
                    "请逐项分析:\n"
                    "1. **正确性** —— 逻辑是否正确，边界情况是否处理\n"
                    "2. **性能** —— 是否有性能瓶颈或优化空间\n"
                    "3. **安全性** —— 是否存在注入、泄露、权限等风险\n"
                    "4. **最佳实践** —— 命名/结构/注释是否符合 {language} 社区规范\n"
                    "5. **改进建议** —— 给出具体的改进方案和示例代码\n\n"
                    "最后给出综合评分和一句话总结。"
                ),
            },
        ]

    # ── 2. 论文写作 ──
    @mcp.prompt(
        name="paper_writing",
        description="学术论文写作助手 —— 大纲/章节/润色",
    )
    def prompt_paper_writing(
        topic: str,
        style: str = "academic",
        section: str = "all",
    ) -> list[dict]:
        section_guide = {
            "abstract": "撰写的摘要，要求 200-300 字，包含背景、方法、结果、结论四要素",
            "introduction": "撰写的引言，需包含研究背景、现有问题、本文贡献三部分",
            "related": "撰写的相关工作综述，分类总结前人研究并指出不足",
            "method": "撰写的方法章节，详细描述算法/架构/实验设计",
            "experiment": "撰写的实验章节，描述实验设置、结果和分析",
            "conclusion": "撰写的结论，总结贡献并展望未来方向",
            "all": "撰写完整论文大纲，按标准学术论文结构组织",
        }
        task = section_guide.get(section, section_guide["all"])

        return [
            {
                "role": "system",
                "content": (
                    f"你是一位{style}论文写作专家。"
                    "请使用学术规范的语言，注重逻辑严密性和引用准确性。"
                ),
            },
            {
                "role": "user",
                "content": f"主题: {topic}\n\n请为此主题{task}。",
            },
        ]

    # ── 3. PPT 大纲生成 ──
    @mcp.prompt(
        name="ppt_outline",
        description="PPT 演示文稿大纲生成 —— 从文字描述到结构化幻灯片",
    )
    def prompt_ppt_outline(content: str, slides: int = 10) -> list[dict]:
        return [
            {
                "role": "system",
                "content": (
                    "你是一位专业的演示文稿设计师。"
                    "请将输入内容转化为结构化的 PPT 大纲，每页包含标题和 3-5 个要点。"
                    "注意视觉节奏：封面 → 目录 → 问题 → 方案 → 数据 → 总结。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"请将以下内容整理为 {slides} 页 PPT 大纲:\n\n{content}\n\n"
                    "格式要求:\n"
                    "1. 每页包含: 页码、标题、要点列表\n"
                    "2. 建议配图类型（图表/流程图/照片）\n"
                    "3. 关键数据用 **加粗** 标注"
                ),
            },
        ]

    # ── 4. 日报/周报 ──
    @mcp.prompt(
        name="daily_report",
        description="日报生成 —— 从聊天记录/工作记录中提取要点",
    )
    def prompt_daily_report(
        notes: str,
        period: str = "daily",
    ) -> list[dict]:
        period_cn = "日报" if period == "daily" else "周报"

        return [
            {
                "role": "system",
                "content": f"你是一位效率助手。请根据用户的工作记录整理{period_cn}。",
            },
            {
                "role": "user",
                "content": (
                    f"请根据以下记录生成一份{period_cn}:\n\n{notes}\n\n"
                    "格式:\n"
                    "## 今日完成\n- ...\n"
                    "## 进行中\n- ...\n"
                    "## 遇到的问题\n- ...\n"
                    "## 明日计划\n- ..."
                ),
            },
        ]

    # ── 5. 功能文档 ──
    @mcp.prompt(
        name="feature_doc",
        description="功能开发文档模板 —— 需求/设计/接口/测试",
    )
    def prompt_feature_doc(feature: str) -> list[dict]:
        return [
            {
                "role": "system",
                "content": "你是一位技术文档工程师。请用简洁精确的语言撰写功能文档。",
            },
            {
                "role": "user",
                "content": (
                    f"为以下功能撰写开发文档:\n\n{feature}\n\n"
                    "结构:\n"
                    "## 需求概述\n## 设计方案\n## API 接口\n## 数据库变更\n## 测试要点\n## 上线检查清单"
                ),
            },
        ]

    # ── 6. 调试分析 ──
    @mcp.prompt(
        name="debug_analysis",
        description="Bug 调试分析 —— 从错误日志到根因定位",
    )
    def prompt_debug_analysis(error_log: str, context: str = "") -> list[dict]:
        return [
            {
                "role": "system",
                "content": "你是一位资深调试工程师。请从错误日志出发，定位根因并给出修复方案。",
            },
            {
                "role": "user",
                "content": (
                    f"## 错误日志\n```\n{error_log}\n```\n\n"
                    f"## 相关上下文\n{context}\n\n"
                    "请分析:\n"
                    "1. 错误类型与直接原因\n"
                    "2. 可能的根因（列出 2-3 个）\n"
                    "3. 验证方法\n"
                    "4. 推荐修复方案（含代码示例）"
                ),
            },
        ]

    print(f"[MCP] Prompts 已注册", file=__import__('sys').stderr)
