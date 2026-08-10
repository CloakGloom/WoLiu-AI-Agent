"""
ReAct Agent 循环 —— 电脑端和手机端通用
使用 OpenAI SDK 调用 LLM API
集成数据库、记忆系统和规则
"""

import json
import re as _re
from openai import OpenAI
from config import API_KEY, API_BASE_URL, MODEL_NAME
from agent.tools import get_current_device, \
    set_progress_callback, clear_progress_callback
from agent import database
from agent.rules.loader import build_system_prompt, get_max_iterations
from agent.memory.long_term import retrieve_context, store_conversation
from agent.memory.long_term.config import get_rag_config
from agent.personality import apply_filter, record_event

# 延迟初始化 OpenAI 客户端（避免导入时 API_KEY 未设置导致崩溃）
_client = None


def _get_client():
    """获取 OpenAI 客户端（延迟初始化）"""
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=API_BASE_URL,
            api_key=API_KEY,
        )
    return _client


def call_llm(messages: list):
    """调用 LLM API"""
    from agent.mcp_client import get_manager
    return _get_client().chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.7,
        tools=get_manager().get_tools_for_llm(),
        tool_choice="auto",
    )


def _call_llm_stream(messages: list, on_chunk=None):
    """流式调用 LLM，实时通过 on_chunk 回调内容增量。

    返回 (content, tool_calls)：
      - content: 完整文本内容
      - tool_calls: [{"id":..,"function":{"name":..,"arguments":..}}] 或 None
    若端点不支持流式，自动回退到非流式调用。
    """
    from agent.mcp_client import get_manager
    try:
        stream = _get_client().chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.7,
            tools=get_manager().get_tools_for_llm(),
            tool_choice="auto",
            stream=True,
        )
        content_parts = []
        tc_acc = {}  # index -> {id, name, arguments}
        for chunk in stream:
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                content_parts.append(piece)
                if on_chunk:
                    try:
                        on_chunk(piece)
                    except Exception:
                        pass
            tcs = getattr(delta, "tool_calls", None)
            if tcs:
                for tc in tcs:
                    idx = getattr(tc, "index", 0) or 0
                    e = tc_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if getattr(tc, "id", None):
                        e["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            e["name"] += fn.name
                        if getattr(fn, "arguments", None):
                            e["arguments"] += fn.arguments

        content = "".join(content_parts)
        if tc_acc:
            tool_calls = [
                {
                    "id": tc_acc[i]["id"] or f"call_{i}",
                    "function": {
                        "name": tc_acc[i]["name"],
                        "arguments": tc_acc[i]["arguments"],
                    },
                }
                for i in sorted(tc_acc.keys())
            ]
            return content, tool_calls
        return content, None
    except Exception as stream_err:
        # 回退到非流式调用
        try:
            completion = call_llm(messages)
            msg = completion.choices[0].message
            tool_calls = None
            if msg.tool_calls:
                tool_calls = [
                    {
                        "id": tc.id,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
            content = msg.content or ""
            if content and on_chunk:
                try:
                    on_chunk(content)
                except Exception:
                    pass
            return content, tool_calls
        except Exception as fallback_err:
            # 回退也失败，返回错误消息
            error_content = f"[LLM调用失败] 流式: {stream_err}; 非流式: {fallback_err}"
            if on_chunk:
                try:
                    on_chunk(error_content)
                except Exception:
                    pass
            return error_content, None


def run_agent(messages: list, session_id: str = None,
              max_iterations: int = None,
              on_step: callable = None,
              on_chunk: callable = None,
              on_progress: callable = None) -> str:
    """
    ReAct Agent 主循环：
    1. 构建 System Prompt（含规则）
    2. 调用 LLM（流式）
    3. 如果有 tool_calls → 执行工具 → 将结果追加到 messages → 回到步骤 2
    4. 如果没有 tool_calls → 返回最终回复

    on_step 回调用于实时推送过程步骤，参数为 dict:
      {"type": "thinking"}
      {"type": "tool_call", "name": "xxx", "arguments": {...}}
      {"type": "tool_result", "name": "xxx", "content": "..."}
    on_chunk 回调用于流式推送最终回复的文本增量，参数为 str。
    on_progress 回调用于推送工具执行进度，参数为 dict:
      {"tool": "xxx", "percent": 0-100, "message": "..."}
    """
    if max_iterations is None:
        max_iterations = get_max_iterations()

    # 初始化 MCP 工具管理器（幂等）
    from agent.mcp_client import get_manager

    # 注册工具进度回调（thread-local，供工具内部 emit_progress 使用）
    set_progress_callback(on_progress)

    # 当前设备名称（保存消息时使用，避免重复计算）
    device_name = "电脑" if get_current_device() == "pc" else "手机"

    # ── RAG 长期记忆检索 ──
    rag_config = get_rag_config()
    rag_enabled = rag_config.get("enabled", True)
    history_chunks = []

    # 提取最后一条用户消息用于 RAG 检索
    last_user_msg = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user_msg = m.get("content", "")
            break

    if rag_enabled and last_user_msg:
        try:
            history_chunks = retrieve_context(last_user_msg, session_id)
        except Exception as e:
            print(f"[RAG] 检索失败: {e}")
            history_chunks = []

    # 构建完整的 messages 列表（含 system prompt + RAG 记忆）
    system_prompt = build_system_prompt()
    full_messages = [{"role": "system", "content": system_prompt}]

    if history_chunks:
        memory_text = "\n".join(history_chunks)
        full_messages.append({
            "role": "system",
            "content": f"[历史记忆参考]\n{memory_text}\n\n请参考以上历史信息回答用户的问题。"
        })

    full_messages += messages

    iteration = 0
    steps = []  # 收集过程步骤，用于持久化

    while iteration < max_iterations:
        iteration += 1
        if on_step:
            on_step({"type": "thinking"})
        steps.append({"type": "thinking"})
        # 流式调用 LLM：内容增量实时通过 on_chunk 推送
        try:
            content_delta, tool_calls = _call_llm_stream(full_messages, on_chunk)
        except Exception as e:
            clear_progress_callback()
            return f"抱歉，LLM 调用出现异常：{str(e)[:300]}"

        # 检查是否有 tool_calls
        if tool_calls:
            # 追加 assistant 消息（含 tool_calls）
            assistant_msg = {
                "role": "assistant",
                "content": content_delta,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }
                    for tc in tool_calls
                ],
            }
            full_messages.append(assistant_msg)

            # 保存 assistant 消息到数据库
            if session_id:
                database.save_message(
                    session_id, "assistant", content_delta or "",
                    device_name, tool_calls=json.dumps(assistant_msg["tool_calls"], ensure_ascii=False)
                )

            # 逐个执行工具调用
            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    arguments = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, TypeError, KeyError) as e:
                    # LLM 返回的 JSON 参数不完整或格式错误（流式模式下常见）
                    tool_result = f"工具参数解析失败: {str(e)[:200]}"
                    if on_step:
                        on_step({"type": "tool_call", "name": tool_name, "arguments": {}})
                    steps.append({"type": "tool_call", "name": tool_name, "arguments": {}})
                    if on_step:
                        on_step({"type": "tool_result", "name": tool_name, "content": tool_result})
                    steps.append({"type": "tool_result", "name": tool_name, "content": tool_result})
                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": tool_result,
                    }
                    full_messages.append(tool_msg)
                    if session_id:
                        database.save_message(
                            session_id, "tool", tool_result, device_name,
                            tool_call_id=tc["id"]
                        )
                    continue

                if on_step:
                    on_step({"type": "tool_call", "name": tool_name, "arguments": arguments})
                steps.append({"type": "tool_call", "name": tool_name, "arguments": arguments})
                # 注入 session_id 用于日志
                if session_id:
                    arguments["_session_id"] = session_id
                try:
                    tool_result = get_manager().call_tool(tool_name, arguments)
                    # 标记 GPU 服务使用（供空闲回收线程判断）
                    # 使用字典映射代替脆弱切片
                    _gpu_tool_map = {
                        "generate_image": "comfyui",
                        "generate_video_i2v": "comfyui",
                        "generate_video_t2v": "comfyui",
                        "tts_speak": "chattts",
                    }
                    gpu_service = _gpu_tool_map.get(tool_name)
                    if gpu_service:
                        try:
                            from run_server import _mark_gpu_used as _mgu
                            _mgu(gpu_service)
                        except Exception:
                            pass
                except Exception as e:
                    # 捕获 execute_tool 内部未处理的异常，确保 tool_result 被赋值
                    tool_result = f"工具执行失败: {str(e)}"
                finally:
                    # 单个工具结束后重置其进度到 100%，避免进度条残留
                    if on_progress:
                        try:
                            on_progress({"tool": tool_name, "percent": 100, "message": ""})
                        except Exception:
                            pass

                if on_step:
                    on_step({"type": "tool_result", "name": tool_name, "content": tool_result})
                steps.append({"type": "tool_result", "name": tool_name, "content": tool_result})

                # 截断过长的工具结果，防止 context 膨胀（保留前后各 3000 字符）
                truncated = tool_result
                if len(tool_result) > 8000:
                    truncated = tool_result[:3000] + "\n\n... [中间内容已截断，完整结果已保存] ...\n\n" + tool_result[-3000:]

                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": truncated,
                }
                full_messages.append(tool_msg)

                # 保存 tool 结果到数据库
                if session_id:
                    database.save_message(
                        session_id, "tool", tool_result, device_name,
                        tool_call_id=tc["id"]
                    )

            # 继续循环，让 LLM 处理工具结果
            continue

        else:
            # 最终文本回复
            content = content_delta or ""

            # 清除 LLM 可能自行生成的 [IMAGE:...] / [PAPER:...] / [VIDEO:...] 标记（避免重复）
            # 统一由下面的工具结果注入逻辑来添加
            content = _re.sub(r'\[IMAGE:[^\]]*\]', '', content)
            content = _re.sub(r'\[PAPER:[^\]]*\]', '', content)
            content = _re.sub(r'\[VIDEO:[^\]]*\]', '', content)
            content = content.strip()
            # 从工具结果中收集所有标记（支持多篇论文/多张图片/多个视频），注入到 LLM 回复之前
            injected_images = []
            injected_papers = []
            injected_videos = []
            seen_img = set()
            seen_paper = set()
            seen_video = set()
            for step in steps:
                if step.get("type") == "tool_result":
                    sc = step.get("content", "")
                    for m in _re.finditer(r'\[IMAGE:[^\]]*\]', sc):
                        tag = m.group(0)
                        if tag not in seen_img:
                            seen_img.add(tag)
                            injected_images.append(tag)
                    for m in _re.finditer(r'\[PAPER:[^\]]*\]', sc):
                        tag = m.group(0)
                        if tag not in seen_paper:
                            seen_paper.add(tag)
                            injected_papers.append(tag)
                    for m in _re.finditer(r'\[VIDEO:[^\]]*\]', sc):
                        tag = m.group(0)
                        if tag not in seen_video:
                            seen_video.add(tag)
                            injected_videos.append(tag)
            for img in injected_images:
                content = img + "\n" + content
            for paper in injected_papers:
                content = paper + "\n" + content
            for video in injected_videos:
                content = video + "\n" + content

            # ── 人格过滤 ──
            try:
                content = apply_filter(content)
            except Exception:
                pass

            full_messages.append({"role": "assistant", "content": content})

            # 保存最终回复到数据库（含过程步骤）
            if session_id:
                steps_json = json.dumps(steps, ensure_ascii=False) if steps else None
                database.save_message(session_id, "assistant", content, device_name,
                                      process_steps=steps_json)

            # ── RAG 长期记忆存储 ──
            if rag_enabled and session_id and last_user_msg:
                try:
                    store_conversation(session_id, last_user_msg, content)
                except Exception as e:
                    print(f"[RAG] 存储失败: {e}")

            # ── 人格演化事件采集 ──
            if session_id and last_user_msg:
                try:
                    record_event(
                        user_msg=last_user_msg,
                        assistant_msg=content,
                        turn_count=iteration,
                        session_id=session_id,
                    )
                except Exception as e:
                    print(f"[Personality] 演化事件记录失败: {e}")

            clear_progress_callback()
            return content

    clear_progress_callback()
    return "抱歉，Agent 达到了最大迭代次数，请重试。"