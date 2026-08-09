"""
agent.mcp_server.server —— FastMCP 实例 + 工具注册 + 启动入口

用法:
    python -m agent.mcp_server              # stdio 模式 (默认)
    python -m agent.mcp_server --sse 8080   # SSE 模式
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastmcp import FastMCP

# ── 全局 FastMCP 实例 ──
mcp = FastMCP(
    name="AI-Agent",
    instructions="""
AI Agent 本地工具服务器。

提供以下类别的工具:
- 系统: 时间、天气、计算、迁移、诊断、状态
- 搜索: 网页搜索、内容抓取
- 设备: 麦克风、扬声器、摄像头控制 (按 PC/手机分发)
- 绘画: AI 图片生成、视频生成 (ComfyUI)
- 文档: 论文生成、PPT 生成、文件读取、格式转换
- 记忆: 上下文召回、长期记忆管理
- 工具: 音乐控制、模拟面试、TTS 语音合成、简历生成
- AI: YOLO 训练/预测/数据集管理、ModelScope 模型
    """.strip(),
)

# 线程池用于同步工具执行
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mcp-tool-")

# 合法的 Python 标识符检测
_VALID_IDENT = re.compile(r"^[a-zA-Z_]\w*$")


def _safe_param_name(name: str) -> str:
    """确保参数名是合法 Python 标识符，必要时加下划线后缀"""
    if _VALID_IDENT.match(name):
        return name
    return f"_{name.replace('-', '_').replace('.', '_')}"


def _get_current_device() -> str:
    """读取当前设备（由 set_current_device 设置）"""
    from agent.tools import get_current_device
    return get_current_device()


def _build_wrapper(
    tool_name: str,
    execute_fn,
    parameters_schema: dict,
    need_device: bool = False,
    timeout: float = 60.0,
):
    """
    根据 JSON Schema 动态生成具名参数的 async wrapper 函数。

    FastMCP 3.x 不支持 **kwargs，因此必须根据 schema 的 properties
    生成带精确参数名的函数。这里通过 exec() 动态构造。
    """
    properties = parameters_schema.get("properties", {})
    required_orig = set(parameters_schema.get("required", []))
    param_names = [_safe_param_name(p) for p in properties.keys()]

    # 构建 original_name → safe_name 映射
    name_map = dict(zip(properties.keys(), param_names))
    # 将 required 集合转换为 safe 名称
    required = {name_map.get(r, r) for r in required_orig}

    safe_tool_name = _safe_param_name(tool_name)

    if not param_names:
        # 无参数工具
        code = textwrap.dedent(f"""\
        async def _{safe_tool_name}():
            import json, asyncio
            from agent.mcp_server.server import _executor as _ex, _get_current_device as _gd
            args = {{}}
            if {need_device}:
                args['current_device'] = _gd()
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
        # 构建参数列表：必选参数在前，可选参数在后（Python 语法要求）
        required_params = [p for p in param_names if p in required]
        optional_params = [p for p in param_names if p not in required]

        param_strs = list(required_params)  # 无默认值
        param_strs.extend(f"{p}=None" for p in optional_params)  # 有默认值

        # 构建 args 字典的字面量（映射 safe_name → original_name，用于注册表恢复）
        args_parts = ", ".join(f"'{orig}': {safe}" for orig, safe in zip(properties.keys(), param_names))
        param_list = ", ".join(param_strs)

        code = textwrap.dedent(f"""\
        async def _{safe_tool_name}({param_list}):
            import json, asyncio
            from agent.mcp_server.server import _executor as _ex, _get_current_device as _gd
            args = {{{args_parts}}}
            if {need_device}:
                args['current_device'] = _gd()
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

    # 执行动态代码
    ns: dict[str, Any] = {"_exec_fn_": execute_fn, "__builtins__": __builtins__}
    exec(code, ns)
    wrapper = ns[f"_{safe_tool_name}"]

    # 设置函数元数据
    wrapper.__name__ = tool_name
    wrapper.__qualname__ = tool_name
    wrapper.__doc__ = f"MCP wrapper for {tool_name}"
    return wrapper


def register_all_tools():
    """
    从 agent.tools 的工具注册表批量注册到 MCP Server。

    通过 get_tool_registry() 获取所有工具信息，
    为每个工具创建 MCP wrapper 并注册到 FastMCP 实例。
    """
    from agent.tools import get_tool_registry

    registry = get_tool_registry()
    registered = 0
    skipped = 0

    for entry in registry:
        tool_name = entry["name"]
        schema = entry["schema"]
        execute_fn = entry["execute"]
        need_device = entry["need_device"]
        timeout = entry["timeout"]
        tag = entry["tag"]

        func_info = schema.get("function", {})
        description = func_info.get("description", "")
        parameters = func_info.get("parameters", {})

        # ── 构建 MCP wrapper（具名参数版本） ──
        try:
            wrapper_fn = _build_wrapper(
                tool_name=tool_name,
                execute_fn=execute_fn,
                parameters_schema=parameters,
                need_device=need_device,
                timeout=timeout,
            )
        except Exception as e:
            print(f"[MCP] 构建 wrapper 失败 {tool_name}: {e}", file=sys.stderr)
            skipped += 1
            continue

        # ── 注册到 FastMCP ──
        try:
            tool_obj = mcp.add_tool(wrapper_fn)

            # 覆盖自动生成的 schema，使用我们已有的精确 JSON Schema
            tool_obj.name = tool_name
            tool_obj.title = tool_name
            tool_obj.description = description
            tool_obj.parameters = parameters

            # 设置标签（用于前端分类展示）
            if tag:
                tool_obj.tags = {tag}

            registered += 1
        except Exception as e:
            print(f"[MCP] 注册工具失败 {tool_name}: {e}", file=sys.stderr)
            skipped += 1

    print(f"[MCP] 已注册 {registered} 个工具 (跳过 {skipped} 个)", file=sys.stderr)
    return registered


def main():
    """MCP Server 启动入口"""
    import argparse

    parser = argparse.ArgumentParser(description="AI Agent MCP Server")
    parser.add_argument(
        "--sse",
        nargs="?",
        const=8080,
        type=int,
        default=None,
        help="以 SSE 模式启动，可选指定端口 (默认 8080)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="SSE 模式绑定的主机地址 (默认 127.0.0.1)",
    )
    args = parser.parse_args()

    # 注册所有工具 + 高级特性
    registered = register_all_tools()
    if registered == 0:
        print("[MCP] 警告: 未注册任何工具，请检查工具注册表", file=sys.stderr)

    # Phase 4: Resources / Prompts / Sampling
    try:
        from agent.mcp_server.resources import register_resources
        register_resources(mcp)
    except Exception as e:
        print(f"[MCP] Resources 注册失败: {e}", file=sys.stderr)

    try:
        from agent.mcp_server.prompts import register_prompts
        register_prompts(mcp)
    except Exception as e:
        print(f"[MCP] Prompts 注册失败: {e}", file=sys.stderr)

    try:
        from agent.mcp_server.sampling import register_sampling_tools
        sampling_count = register_sampling_tools(mcp)
        print(f"[MCP] Sampling 工具已注册 ({sampling_count} 个)", file=sys.stderr)
    except Exception as e:
        print(f"[MCP] Sampling 注册失败: {e}", file=sys.stderr)

    # 启动
    if args.sse is not None:
        print(f"[MCP] SSE 模式启动: http://{args.host}:{args.sse}/sse", file=sys.stderr)
        mcp.run(transport="sse", host=args.host, port=args.sse)
    else:
        print("[MCP] stdio 模式启动", file=sys.stderr)
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
