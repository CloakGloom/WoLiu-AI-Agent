"""
agent.mcp_server.sampling —— MCP Sampling 采样能力

允许 MCP Tool 在执行过程中反向请求 LLM 进行审查/分析/生成。

FastMCP 3.x 通过 Context.sample() 支持此功能。
Context 通过函数参数类型注解自动注入。

由于我们的工具是动态生成的 wrapper，这里提供:
1. 带 Context 注入的工具包装器
2. 几个示范性 Sampling Tool
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any


# ── 辅助工具：在 wrapper 中注入 Context ──

def _build_sampling_capable_wrapper(
    tool_name: str,
    execute_fn,
    parameters_schema: dict,
    need_device: bool = False,
    timeout: float = 60.0,
):
    """
    构建带 Context 注入的 wrapper（用于支持 Sampling 的工具）。

    与 server.py 中的 _build_wrapper 类似，但额外接受 ctx: Context 参数。
    FastMCP 会自动注入 Context 对象给标注了 Context 类型的参数。
    """
    import textwrap
    import re as _re

    properties = parameters_schema.get("properties", {})
    required_orig = set(parameters_schema.get("required", []))
    param_names = [_safe_param_name(p) for p in properties.keys()]
    name_map = dict(zip(properties.keys(), param_names))
    required = {name_map.get(r, r) for r in required_orig}
    safe_tool_name = _safe_param_name(tool_name)

    if not param_names:
        # 无参数 + ctx
        code = textwrap.dedent(f"""\
        async def _{safe_tool_name}(ctx=None):
            import json
            from agent.mcp_server.server import _executor as _ex, _get_current_device as _gd
            from agent.mcp_server.sampling import _resolve_sampling_ctx
            args = {{}}
            if {need_device}:
                args['current_device'] = _gd()
            # 注入 ctx 到 argument
            args['_mcp_context'] = _resolve_sampling_ctx(ctx)
            loop = asyncio.get_running_loop()
            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(_ex, _exec_fn_, args), {timeout}
                )
            except asyncio.TimeoutError:
                return "工具 '{tool_name}' 执行超时 ({timeout}秒)"
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False, default=str)
        """)
    else:
        required_params = [p for p in param_names if p in required]
        optional_params = [p for p in param_names if p not in required]
        param_strs = list(required_params)
        param_strs.extend(f"{p}=None" for p in optional_params)
        param_strs.append("ctx=None")  # Context 参数
        args_parts = ", ".join(f"'{orig}': {safe}" for orig, safe in zip(properties.keys(), param_names))
        param_list = ", ".join(param_strs)

        code = textwrap.dedent(f"""\
        async def _{safe_tool_name}({param_list}):
            import json
            from agent.mcp_server.server import _executor as _ex, _get_current_device as _gd
            from agent.mcp_server.sampling import _resolve_sampling_ctx
            args = {{{args_parts}}}
            if {need_device}:
                args['current_device'] = _gd()
            # 注入 ctx
            args['_mcp_context'] = _resolve_sampling_ctx(ctx)
            loop = asyncio.get_running_loop()
            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(_ex, _exec_fn_, args), {timeout}
                )
            except asyncio.TimeoutError:
                return "工具 '{tool_name}' 执行超时 ({timeout}秒)"
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False, default=str)
        """)

    ns: dict[str, Any] = {"_exec_fn_": execute_fn, "__builtins__": __builtins__}
    exec(code, ns)
    wrapper = ns[f"_{safe_tool_name}"]
    wrapper.__name__ = tool_name
    wrapper.__qualname__ = tool_name
    wrapper.__doc__ = f"MCP wrapper (sampling-capable) for {tool_name}"
    return wrapper


def _resolve_sampling_ctx(ctx) -> SamplingContext | None:
    """将 FastMCP Context 包装为 SamplingContext"""
    if ctx is None:
        return None
    try:
        return SamplingContext(ctx)
    except Exception:
        return None


def _safe_param_name(name: str) -> str:
    import re as _re
    if _re.match(r"^[a-zA-Z_]\w*$", name):
        return name
    return f"_{name.replace('-', '_').replace('.', '_')}"


# ── SamplingContext: 工具内可调用的 LLM 接口 ──

class SamplingContext:
    """
    工具在执行期间可通过此类反向调用 LLM。

    用法示例（在工具 execute() 内）:

        def execute(args):
            ctx = args.get("_mcp_context")
            if ctx:
                review = await ctx.sample(
                    messages="审查这段内容的质量",
                    max_tokens=200,
                )
                if "问题" in review:
                    ...
    """

    def __init__(self, fastmcp_context):
        self._ctx = fastmcp_context

    async def sample(
        self,
        messages: str | list,
        *,
        system_prompt: str | None = None,
        max_tokens: int = 500,
        temperature: float = 0.7,
    ) -> str:
        """
        向 LLM 发送一次采样请求并等待响应。

        Args:
            messages: 消息内容（字符串或消息列表）
            system_prompt: 可选的系统提示
            max_tokens: 最大返回 token 数
            temperature: 采样温度

        Returns:
            LLM 的文本响应
        """
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        result = await self._ctx.sample(
            messages=messages,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        # SamplingResult 的 content 是文本内容
        if hasattr(result, "content"):
            return result.content
        elif hasattr(result, "text"):
            return result.text
        return str(result)


# ── 示范性 Sampling Tool ──

def register_sampling_tools(mcp):
    """注册自带 Sampling 能力的演示工具"""

    @mcp.tool(
        name="self_review_content",
        description=(
            "生成内容并自动自我审查。先调用 LLM 生成内容，再调用 LLM 审查质量，"
            "最后返回审查后的内容。适用于需要质量保证的场景。"
        ),
    )
    async def self_review_content(
        topic: str,
        style: str = "技术文档",
        ctx: Any = None,
    ) -> str:
        """生成 → 自审查 → 修正内容"""
        sampling = _resolve_sampling_ctx(ctx)

        if sampling is None:
            return f"# 关于 {topic} 的内容\n\n(Sampling 能力不可用，请通过 MCP 协议连接以启用自审查)"

        # Step 1: 生成
        generated = await sampling.sample(
            messages=f"请以'{style}'风格撰写关于'{topic}'的内容，约 300 字。",
            max_tokens=500,
        )

        # Step 2: 审查
        review = await sampling.sample(
            messages=f"请审查以下内容，指出问题并评分(0-100):\n\n{generated}",
            system_prompt="你是内容质量审查专家。只需返回: 评分(数字) + 问题列表 + 改进建议。",
            max_tokens=300,
        )

        # Step 3: 根据审查意见修正
        prompt = (
            f"请根据以下审查意见修正内容:\n\n"
            f"原始内容:\n{generated}\n\n"
            f"审查意见:\n{review}\n\n"
            f"要求: 保持主题和风格不变，仅修正指出的问题。"
        )
        revised = await sampling.sample(messages=prompt, max_tokens=600)

        return (
            f"## 审查意见\n{review}\n\n"
            f"---\n\n"
            f"## 修正后内容\n{revised}"
        )

    @mcp.tool(
        name="smart_summarize",
        description=(
            "智能摘要：先将内容拆分，逐段总结，再全局汇总。"
            "适合超长文本的层次化摘要。"
        ),
    )
    async def smart_summarize(
        text: str,
        max_words: int = 200,
        ctx: Any = None,
    ) -> str:
        """层次化摘要：分片 → 逐段摘要 → 全局汇总"""
        sampling = _resolve_sampling_ctx(ctx)

        if sampling is None:
            # 简单回退
            return f"## 摘要\n{text[:max_words]}..."

        # 如果文本不长，直接摘要
        if len(text) < 2000:
            result = await sampling.sample(
                messages=f"请用不超过 {max_words} 字总结以下内容:\n\n{text}",
                max_tokens=max_words * 2,
            )
            return f"## 摘要（{max_words}字）\n{result}"

        # 长文本：分片处理
        chunk_size = 1500
        chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
        chunk_summaries = []

        for i, chunk in enumerate(chunks[:5]):  # 最多 5 片
            summary = await sampling.sample(
                messages=f"用一句话总结以下片段的核心内容:\n\n{chunk}",
                max_tokens=100,
            )
            chunk_summaries.append(f"片段{i+1}: {summary.strip()}")

        # 全局汇总
        final = await sampling.sample(
            messages=(
                f"以下是长文本的各片段摘要，请用不超过 {max_words} 字做全局总结:\n\n"
                + "\n".join(chunk_summaries)
            ),
            max_tokens=max_words * 2,
        )

        return (
            f"## 智能摘要（{len(chunks)} 片段 → 全局汇总）\n{final}\n\n"
            f"---\n\n## 片段摘要\n" + "\n".join(chunk_summaries)
        )

    print(f"[MCP] Sampling 工具已注册", file=sys.stderr)
    return 2  # registered count
