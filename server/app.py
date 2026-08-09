"""
电脑端主程序 —— FastAPI + WebSocket 服务器
负责：Web 页面路由、WebSocket 通信、Agent 调度、迁移协议

迁移自 Flask（2026-08-07）：
- HTTP 路由使用 FastAPI 原生装饰器，返回 dict 自动序列化为 JSON
- 文件上传使用 UploadFile，错误使用 JSONResponse 保留 {"error": ...} 结构
- WebSocket 使用原生 @app.websocket，阻塞调用（run_agent 等）走 run_in_threadpool
- 跨线程广播（音乐状态 / 自动回迁 / 状态）走 run_coroutine_threadsafe
"""

import asyncio
import json
import os
import sys
import random
import re
import subprocess
import threading
import time
import logging
from datetime import datetime

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles

from config import WS_HOST, WS_PORT, DEVICE_PC, DEVICE_MOBILE, MIGRATE_TIMEOUT
from agent.tools import set_current_device
from agent.core import run_agent
from agent import database
from agent.config import (
    load as _app_cfg, get as _cfg_get, project_root as _pr,
    # 服务 URL / 端口
    comfyui_url as _cfg_comfyui_url, tts_url as _cfg_tts_url,
    jadeai_url as _cfg_jadeai_url,
    ollama_exe as _cfg_ollama_exe, ollama_models_dir as _cfg_ollama_models_dir,
    ollama_port as _cfg_ollama_port, ollama_vision_model as _cfg_ollama_vision,
    ollama_url as _cfg_ollama_url,
    # HuggingFace 镜像
    hf_endpoint as _cfg_hf_endpoint,
    # TTS 类型
    tts_enabled as _cfg_tts_enabled,
    # Torch lib
    torch_lib_path as _cfg_torch_lib,
)

# 从统一配置 system_configs.yaml 读取外部服务路径，免除硬编码
_OLLAMA_EXE = _cfg_get("services.ollama.executable") or ""
_OLLAMA_MODELS = _cfg_get("services.ollama.models_dir") or ""
_TTS_DIR = _cfg_get("services.tts.project_dir") or ""
_PYTHON_EXE = _cfg_get("python.executable") or ""
_TORCH_LIB = _cfg_get("python.torch_lib") or ""

# 辅助：相对路径 → 绝对路径
def _abs(p: str) -> str:
    if not p:
        return p
    return str(_pr() / p) if not os.path.isabs(p) else p
from agent.rules.loader import get_max_history_turns
from agent.tools.custom import music_control
from agent.tools.builtin import migrate as migrate_tool
from agent.tools.builtin import diagnostics as diagnostics_tool
from agent.tools.custom.paper_generator import regenerate_document
from agent.tools import _RAW_TOOLS, _TOOL_REGISTRY, toggle_tool, get_disabled_tools
from server.shared import ensure_session, format_messages_for_ws, format_sessions_list, fallback_session, parse_json_body

# ==================== 路径 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

# ==================== 日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("server")
_autolabel_pid = None  # autolabel-dock GUI 进程 PID

# 自启动配置
AUTOSTART_CFG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "autostart.json")
_autostart = {}
try:
    with open(AUTOSTART_CFG, encoding="utf-8") as f:
        _autostart = json.load(f)
except Exception:
    pass

# ==================== FastAPI 应用 ====================
app = FastAPI(title="我流 Agent", version="2.0")

# ── MCP 启动初始化 ──
@app.on_event("startup")
async def startup_mcp():
    """服务启动时初始化 MCP 工具管理器 + 连接外部 MCP Server"""
    try:
        from agent.mcp_client import get_manager
        mgr = get_manager()
        mgr.initialize()
        await mgr.initialize_async()
        logger.info("MCP 工具管理器已初始化（含远程连接）")
    except Exception as e:
        logger.warning(f"MCP 初始化跳过: {e}")

@app.on_event("shutdown")
async def shutdown_mcp():
    """服务关闭时断开所有 MCP 连接"""
    try:
        from agent.mcp_client import get_manager
        await get_manager().shutdown()
        logger.info("MCP 连接已关闭")
    except Exception:
        pass

# ── 全局异常中间件 ──
@app.middleware("http")
async def global_exception_handler(request: Request, call_next):
    """统一异常捕获：任何未处理的异常都返回 500 并记录日志"""
    try:
        return await call_next(request)
    except Exception:
        logger.exception("unhandled_exception", extra={"path": str(request.url)})
        return JSONResponse(status_code=500, content={"error": "服务器内部错误，已自动记录"})

# ==================== 应用状态（线程/协程安全的有限状态机） ====================

from enum import Enum as _Enum

class AgentPhase(_Enum):
    IDLE_PC = "pc"
    IDLE_MOBILE = "mobile"
    MIGRATING = "migrating"

# 合法的状态转换映射
_VALID_TRANSITIONS = {
    AgentPhase.IDLE_PC:     {AgentPhase.MIGRATING},
    AgentPhase.IDLE_MOBILE: {AgentPhase.MIGRATING},
    AgentPhase.MIGRATING:   {AgentPhase.IDLE_PC, AgentPhase.IDLE_MOBILE},
}

class AppState:
    """全局应用状态容器 —— 有限状态机，所有状态变更必须走 transition()"""
    def __init__(self):
        self.lock = threading.Lock()
        self._phase = AgentPhase.IDLE_PC
        self.pc_ws = None
        self.mobile_ws = None
        self.migrate_timer = None
        self.current_session_id = None
        self.loop = None
        self._loop_handler_set = False

    @property
    def agent_location(self) -> str:
        """兼容旧代码：返回字符串表示"""
        return self._phase.value

    @agent_location.setter
    def agent_location(self, val: str):
        """兼容旧代码直接赋值（如 set_current_device 调用）"""
        phase_map = {"电脑": AgentPhase.IDLE_PC, "手机": AgentPhase.IDLE_MOBILE,
                     "pc": AgentPhase.IDLE_PC, "mobile": AgentPhase.IDLE_MOBILE,
                     "migrating": AgentPhase.MIGRATING}
        if val in phase_map:
            with self.lock:
                self._phase = phase_map[val]
                logger.info("agent_phase_changed", extra={"phase": self._phase.value})

    def transition(self, new_phase: AgentPhase) -> bool:
        """原子状态转换，只允许合法路径，返回是否成功"""
        with self.lock:
            if new_phase not in _VALID_TRANSITIONS.get(self._phase, set()):
                logger.warning("invalid_transition",
                               extra={"from": self._phase.value, "to": new_phase.value})
                return False
            self._phase = new_phase
            logger.info("agent_phase_transitioned",
                       extra={"from": self._phase.value, "to": new_phase.value})
            return True

    @property
    def phase(self) -> AgentPhase:
        with self.lock:
            return self._phase

state = AppState()


# ==================== WebSocket 发送助手 ====================

async def _send_ws(ws, obj):
    """在事件循环内向单个 WebSocket 发送 JSON 消息"""
    try:
        await ws.send_text(json.dumps(obj, ensure_ascii=False))
    except Exception:
        pass


def _safe_send(ws, obj):
    """线程安全的发送：把协程调度到主事件循环执行。
    可从任意线程（音乐回调、迁移定时器、Agent 工具回调）调用。"""
    if ws is None:
        return
    loop = state.loop
    if loop is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(_send_ws(ws, obj), loop)
    except Exception:
        pass


def _broadcast(obj):
    """向所有已连接的 WebSocket 客户端广播"""
    for ws in (state.pc_ws, state.mobile_ws):
        if ws:
            _safe_send(ws, obj)


def _broadcast_music_state(state_str: str):
    """广播音乐状态到所有已连接的 WebSocket 客户端"""
    _broadcast({"type": "music_state", "result": state_str})


# 注册音乐状态回调
music_control.set_state_callback(_broadcast_music_state)





async def _send_chunked_response(ws, reply: str, base_delay: float = 0.4):
    """将长回复拆分为多条消息发送，模拟真人聊天节奏（异步，不阻塞接收循环）"""
    if not reply or not ws:
        return

    # 剥离 AI 可能使用的 ||| 分隔符，替换为自然段落分隔
    reply = reply.replace('|||', '\n\n')

    chunks = []
    # 按段落拆分
    paragraphs = re.split(r'\n\s*\n', reply.strip())
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # 按自然句子边界拆分：句号、问号、感叹号、波浪号、省略号
        subs = re.split(r'(?<=[。！？?～…\n])\s*', para)
        for s in subs:
            s = s.strip()
            if not s:
                continue
            # 如果单句还是太长（>80字），按逗号/分号/冒号再拆
            if len(s) > 80:
                sub2 = re.split(r'(?<=[，,；;：:])\s*', s)
                chunks.extend(x.strip() for x in sub2 if x.strip())
            else:
                chunks.append(s)

    if not chunks:
        return

    # 如果只拆出 1 段且超过 60 字，强制按短句再切一轮
    if len(chunks) == 1 and len(chunks[0]) > 60:
        s = chunks[0]
        # 用所有常见分隔符切
        parts = re.split(r'(?<=[，,。！？?～…；;：:、])\s*', s)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) > 1:
            chunks = parts

    # 合并过短的相邻片段（2段加起来不到30字就拼一起）
    merged = []
    for ch in chunks:
        if merged and len(merged[-1]) + len(ch) < 30:
            merged[-1] += ch
        else:
            merged.append(ch)
    chunks = merged

    for i, chunk in enumerate(chunks):
        await _send_ws(ws, {
            "type": "response",
            "content": chunk,
            "chunk_index": i,
            "chunk_total": len(chunks),
        })
        if i < len(chunks) - 1:
            # 根据内容自然度计算延迟：短句快跟，段末多等，加随机抖动
            is_sentence_end = chunk and chunk[-1] in '。！？?'
            delay = base_delay + len(chunk) * 0.01 + random.uniform(-0.15, 0.2)
            if is_sentence_end:
                delay += 0.3
            await asyncio.sleep(max(0.15, delay))


def _send_status():
    """广播当前 Agent 状态"""
    status = "migrating" if state.agent_location == "migrating" else "online"
    _broadcast({
        "type": "status",
        "state.agent_location": state.agent_location,
        "status": status,
    })


def _migrate_timeout_cb(target_device: str):
    """迁移超时回调：回滚"""

    fail_ws = None
    with state.lock:
        if state.agent_location != "migrating":
            return

        if target_device == DEVICE_MOBILE:
            state.agent_location = DEVICE_PC
            fail_ws = state.pc_ws
        else:
            state.agent_location = DEVICE_MOBILE
            fail_ws = state.mobile_ws

        set_current_device(state.agent_location)
        database.update_current_device(state.agent_location)
        database.update_online_status(True)
        state.migrate_timer = None

    # 在锁外发送消息，避免锁内 I/O
    _send_status()
    if fail_ws:
        _safe_send(fail_ws, {
            "type": "response",
            "content": "迁移失败，请重试（目标设备未在 5 秒内确认）",
        })


def _start_migrate_timer(target_device: str):
    """启动迁移超时定时器"""
    _cancel_migrate_timer()
    state.migrate_timer = threading.Timer(MIGRATE_TIMEOUT, _migrate_timeout_cb, args=[target_device])
    state.migrate_timer.daemon = True
    state.migrate_timer.start()


def _cancel_migrate_timer():
    """取消迁移超时定时器"""
    if state.migrate_timer is not None:
        state.migrate_timer.cancel()
        state.migrate_timer = None


def _do_migrate(target_device: str, target_ws) -> str:
    """执行迁移"""

    with state.lock:
        if state.agent_location == "migrating":
            return "Agent 正在迁移中，请稍候..."

        if target_device == DEVICE_MOBILE and state.agent_location == DEVICE_MOBILE:
            return "Agent 已经在手机端了"
        if target_device == DEVICE_PC and state.agent_location == DEVICE_PC:
            return "Agent 已经在电脑端了"

        if target_ws is None:
            target_name = "手机端" if target_device == DEVICE_MOBILE else "电脑端"
            return f"{target_name}未连接，无法迁移"

        session_id = ensure_session(state)
        package = database.pack_migration_package(session_id, state.agent_location)
        try:
            _safe_send(target_ws, {
                "type": "migrate_data",
                "messages": package["messages"],
                "session_id": session_id,
            })
        except Exception as e:
            return f"迁移失败：无法发送数据 - {e}"

        state.agent_location = "migrating"
        database.set_migrating_status()
        _send_status()
        _start_migrate_timer(target_device)

        target_name = "手机" if target_device == DEVICE_MOBILE else "电脑"
        return f"迁移中… 正在将 Agent 迁移到{target_name}端..."


def _migrate_tool_cb(target_device: str) -> str:
    """迁移工具回调：根据目标设备选择对应的 WebSocket"""
    if target_device == DEVICE_MOBILE:
        return _do_migrate(DEVICE_MOBILE, state.mobile_ws)
    else:
        return _do_migrate(DEVICE_PC, state.pc_ws)


# 初始化迁移工具回调
migrate_tool.set_migrate_callback(_migrate_tool_cb)


def _mobile_diag_cb() -> dict:
    """诊断工具回调：返回移动端连接状态"""
    return {
        "connected": state.mobile_ws is not None,
        "state.agent_location": "手机" if state.agent_location == DEVICE_MOBILE else "电脑",
    }


# 初始化诊断工具回调
diagnostics_tool.set_mobile_status_callback(_mobile_diag_cb)


async def _on_mobile_disconnect():
    """手机端 WebSocket 断开时自动将 Agent 迁回电脑端"""

    with state.lock:
        if state.agent_location != DEVICE_MOBILE:
            return  # Agent 本来就不在手机端，无需处理

        # 自动迁回电脑端
        state.agent_location = DEVICE_PC
        set_current_device(DEVICE_PC)
        database.update_current_device(DEVICE_PC)
        database.update_online_status(True)
        _cancel_migrate_timer()

        logger.info("[自动回迁] 手机端已断开，Agent 自动回到电脑端")

    # 广播状态变更（在锁外执行）
    _send_status()

    # 记录系统事件到数据库
    session_id = ensure_session(state)

    # 异步让 AI 生成自然回复
    if state.pc_ws is not None:
        pc = state.pc_ws
        asyncio.create_task(_ai_auto_reply(pc, session_id))


async def _ai_auto_reply(ws, session_id: str):
    """让 AI 生成自然语言回复（用于手机断线等系统事件）"""
    prompt = (
        "（系统通知：手机端连接已断开，自动回到电脑端。"
        "请自然地告知用户这个情况。不要使用系统消息的格式，就像正常聊天一样。）"
    )
    try:
        messages = database.get_messages_as_openai_format(session_id, get_max_history_turns())
        messages.append({"role": "system", "content": prompt})
        reply = await run_in_threadpool(run_agent, messages, session_id=session_id)
        await _send_chunked_response(ws, reply)
    except Exception as e:
        # 如果 AI 调用失败，回退到简单通知
        await _send_ws(ws, {
            "type": "response",
            "content": "手机端已断开，我已自动回到电脑端。",
        })


def _handle_chat(user_message: str, client_type: str = "pc",
                 on_step: callable = None,
                 on_chunk: callable = None,
                 on_progress: callable = None) -> str:
    """处理用户消息（同步，运行在 threadpool 中）"""
    from agent.tools import clear_progress_callback

    text = user_message.strip()

    session_id = ensure_session(state)
    device = "电脑" if client_type == "pc" else "手机"
    database.save_message(session_id, "user", text, device)
    database.update_session_activity(session_id)

    try:
        messages = database.get_messages_as_openai_format(session_id, get_max_history_turns())
        reply = run_agent(messages, session_id=session_id,
                          on_step=on_step, on_chunk=on_chunk, on_progress=on_progress)
    except Exception as e:
        return f"Agent 调用失败：{e}"
    finally:
        # 无论成功或异常都清理 thread-local 进度回调（threadpool 线程复用）
        clear_progress_callback()
    return reply


# ==================== HTTP 路由 ====================

@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """JS/CSS 静态资源禁用强缓存：每次向服务器校验 ETag，
    避免前端更新后浏览器仍运行旧代码（无更新时返回 304，开销极低）"""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") and path.endswith((".js", ".css")):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/")
async def index():
    return FileResponse(os.path.join(TEMPLATES_DIR, "index.html"))


@app.get("/mobile")
async def mobile():
    return FileResponse(os.path.join(TEMPLATES_DIR, "mobile.html"))


@app.post("/api/open-papers-folder")
async def open_papers_folder():
    """在文件资源管理器中打开论文存放文件夹"""
    papers_dir = os.path.join(STATIC_DIR, "papers")
    os.makedirs(papers_dir, exist_ok=True)
    subprocess.Popen(["explorer", papers_dir])
    return {"ok": True}


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """上传文件到 data/uploads/ 目录"""
    filename = file.filename or ""
    if not filename:
        return JSONResponse(status_code=400, content={"error": "文件名为空"})

    upload_dir = os.path.join(BASE_DIR, "..", "data", "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    # 处理重名
    save_path = os.path.join(upload_dir, filename)
    if os.path.exists(save_path):
        name, ext = os.path.splitext(filename)
        filename = f"{name}_{datetime.now().strftime('%H%M%S')}{ext}"
        save_path = os.path.join(upload_dir, filename)

    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)
    size = os.path.getsize(save_path)
    return {
        "ok": True,
        "filename": filename,
        "path": f"uploads/{filename}",
        "size": size,
    }


@app.get("/api/tools")
async def list_tools():
    """返回所有已注册的工具库信息，按 tag 分类，含启用/禁用状态及 MCP 来源"""
    disabled = set(get_disabled_tools())

    # 工具名 → 模块源码文件的映射
    name_to_module = {}
    for name, mod, _ in _TOOL_REGISTRY:
        if mod:
            name_to_module[name] = mod.__file__
    from agent.tools import _ai_custom_modules
    for mod in _ai_custom_modules:
        name = mod.SCHEMA.get("function", {}).get("name", "")
        if name:
            name_to_module[name] = mod.__file__

    tools_list = []
    tags_set = set()
    for tool in _RAW_TOOLS:
        fn = tool.get("function", {})
        name = fn.get("name", "")
        desc = fn.get("description", "")
        tag = tool.get("tag", "其他")
        tags_set.add(tag)
        params = fn.get("parameters", {}).get("properties", {})
        required = fn.get("parameters", {}).get("required", [])

        # 提取参数列表
        param_list = []
        for pname, pinfo in params.items():
            param_list.append({
                "name": pname,
                "type": pinfo.get("type", "string"),
                "description": pinfo.get("description", ""),
                "required": pname in required,
                "enum": pinfo.get("enum", [])
            })

        # 源文件路径
        src_file = name_to_module.get(name, "")
        if src_file:
            try:
                src_file = os.path.relpath(src_file, os.path.join(BASE_DIR, ".."))
            except ValueError:
                pass

        tools_list.append({
            "name": name,
            "description": desc,
            "tag": tag,
            "enabled": name not in disabled,
            "parameters": param_list,
            "source": src_file.replace("\\", "/") if src_file else "",
            "mcp_source": "local",  # MCP 来源标记
        })

    # ── 追加远程 MCP 工具 ──
    try:
        from agent.mcp_client import get_manager
        mgr = get_manager()
        for tool_info in mgr.list_all_tools():
            if tool_info["source"] != "local":
                fn = tool_info["schema"].get("function", {})
                params = fn.get("parameters", {}).get("properties", {})
                required = fn.get("parameters", {}).get("required", [])
                param_list = []
                for pname, pinfo in params.items():
                    param_list.append({
                        "name": pname,
                        "type": pinfo.get("type", "string"),
                        "description": pinfo.get("description", ""),
                        "required": pname in required,
                        "enum": pinfo.get("enum", []),
                    })
                tools_list.append({
                    "name": tool_info["name"],
                    "description": fn.get("description", ""),
                    "tag": tool_info.get("tag", "远程"),
                    "enabled": True,
                    "parameters": param_list,
                    "source": "",
                    "mcp_source": tool_info["source"],
                })
                tags_set.add("远程")
    except Exception:
        pass

    return {
        "total": len(tools_list),
        "tools": tools_list,
        "tags": sorted(tags_set),
        "disabled": sorted(disabled),
    }


# ==================== MCP 服务模块 API ====================

@app.get("/api/mcp/modules")
async def list_mcp_modules():
    """列出所有 MCP 服务模块（仅已安装的）"""
    try:
        from agent.mcp_client import get_manager
        return {"modules": get_manager().list_modules(), "total": 0}
    except Exception as e:
        return {"modules": [], "total": 0, "error": str(e)}


@app.post("/api/mcp/scan")
async def scan_mcp_modules():
    """重新扫描 MCP 模块目录"""
    try:
        from agent.mcp_modules import scan_modules
        scan_modules(force=True)
        from agent.mcp_client import get_manager
        get_manager().reload()
        return {"ok": True, "message": "模块列表已刷新"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/mcp/resources")
async def list_mcp_resources():
    """列出 MCP Resources（论文模板、配置、记忆、工具源码等）"""
    resources = [
        {
            "uri": "paper://templates/academic",
            "name": "学术论文 LaTeX 模板",
            "description": "标准学术论文 LaTeX 模板",
            "mime_type": "text/x-latex",
        },
        {
            "uri": "paper://templates/markdown",
            "name": "Markdown 论文模板",
            "description": "轻量级 Markdown 论文模板",
            "mime_type": "text/markdown",
        },
        {
            "uri": "config://system",
            "name": "系统配置",
            "description": "当前运行配置（脱敏）",
            "mime_type": "application/json",
        },
        {
            "uri": "config://tools",
            "name": "工具清单",
            "description": "当前启用的所有工具列表",
            "mime_type": "application/json",
        },
        {
            "uri": "memory://session/{session_id}",
            "name": "会话记忆摘要",
            "description": "指定会话的长期记忆摘要（需替换 {session_id}）",
            "mime_type": "application/json",
        },
        {
            "uri": "memory://stats",
            "name": "记忆统计",
            "description": "ChromaDB 长期记忆统计",
            "mime_type": "application/json",
        },
        {
            "uri": "tools://source/{tool_name}",
            "name": "工具源码",
            "description": "指定工具的 Python 源码（需替换 {tool_name}）",
            "mime_type": "text/x-python",
        },
        {
            "uri": "project://structure",
            "name": "项目目录结构",
            "description": "项目目录结构概览",
            "mime_type": "application/json",
        },
    ]
    return {"total": len(resources), "resources": resources}


@app.get("/api/mcp/prompts")
async def list_mcp_prompts():
    """列出 MCP Prompts 提示模板"""
    prompts = [
        {
            "name": "code_review",
            "description": "代码审查 —— 正确性/性能/安全/最佳实践",
            "arguments": [
                {"name": "code", "type": "string", "description": "待审查的代码", "required": True},
                {"name": "language", "type": "string", "description": "编程语言", "required": False},
            ],
        },
        {
            "name": "paper_writing",
            "description": "学术论文写作助手 —— 大纲/章节/润色",
            "arguments": [
                {"name": "topic", "type": "string", "description": "论文主题", "required": True},
                {"name": "style", "type": "string", "description": "风格: academic/technical/review", "required": False},
                {"name": "section", "type": "string", "description": "章节: abstract/introduction/method/experiment/conclusion/all", "required": False},
            ],
        },
        {
            "name": "ppt_outline",
            "description": "PPT 大纲生成 —— 从文字描述到结构化幻灯片",
            "arguments": [
                {"name": "content", "type": "string", "description": "要转化为 PPT 的内容", "required": True},
                {"name": "slides", "type": "integer", "description": "目标页数", "required": False},
            ],
        },
        {
            "name": "daily_report",
            "description": "日报/周报生成 —— 从工作记录中提取要点",
            "arguments": [
                {"name": "notes", "type": "string", "description": "工作记录/聊天记录", "required": True},
                {"name": "period", "type": "string", "description": "daily 或 weekly", "required": False},
            ],
        },
        {
            "name": "feature_doc",
            "description": "功能开发文档模板 —— 需求/设计/接口/测试",
            "arguments": [
                {"name": "feature", "type": "string", "description": "功能描述", "required": True},
            ],
        },
        {
            "name": "debug_analysis",
            "description": "Bug 调试分析 —— 从错误日志到根因定位",
            "arguments": [
                {"name": "error_log", "type": "string", "description": "错误日志/堆栈", "required": True},
                {"name": "context", "type": "string", "description": "相关上下文说明", "required": False},
            ],
        },
    ]
    return {"total": len(prompts), "prompts": prompts}


@app.get("/api/mcp/modules/{module_id}")
async def get_mcp_module(module_id: str):
    """获取指定模块状态"""
    from agent.mcp_client import get_manager
    status = get_manager().get_module_status(module_id)
    if status is None:
        return JSONResponse(status_code=404, content={"error": f"模块 '{module_id}' 不存在"})
    return status


@app.post("/api/tools/toggle")
async def toggle_tool_api(request: Request):
    """切换工具启用/禁用状态"""
    data = await parse_json_body(request)
    tool_name = data.get("name", "").strip()
    if not tool_name:
        return JSONResponse(status_code=400, content={"error": "缺少 name 参数"})
    result = toggle_tool(tool_name)
    # 通知 MCP 管理器刷新工具列表
    try:
        from agent.mcp_client import get_manager
        get_manager().reload()
    except Exception:
        pass
    return result


@app.get("/api/autostart")
async def get_autostart():
    """获取自启动配置"""
    return _autostart


@app.post("/api/autostart/{service}")
async def set_autostart(service: str):
    """切换某个服务的自启动状态"""
    if service not in ("comfyui", "tts", "jadeai", "ollama", "autolabel"):
        return JSONResponse(status_code=400, content={"error": "无效的服务"})
    _autostart[service] = not _autostart.get(service, False)
    try:
        with open(AUTOSTART_CFG, "w", encoding="utf-8") as f:
            json.dump(_autostart, f, indent=4)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    return {"service": service, "enabled": _autostart[service]}


@app.get("/api/paper-source")
async def paper_source(request: Request):
    """获取论文的原始源文件内容（支持 Markdown 和 LaTeX）"""
    name = (request.query_params.get("name", "") or "").strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": "缺少 name 参数"})
    if ".." in name or "/" in name or "\\" in name:
        return JSONResponse(status_code=400, content={"error": "无效的文件名"})

    # 源文件在 data/papers/ 下
    src_dir = os.path.join(BASE_DIR, "..", "data", "papers")

    # 先尝试 .tex（LaTeX），再尝试 .md（Markdown）
    fmt = "markdown"
    src_path = ""
    for ext, f in [(".tex", "latex"), (".md", "markdown")]:
        p = os.path.join(src_dir, f"{name}{ext}")
        if os.path.exists(p):
            src_path = p
            fmt = f
            break

    if not src_path:
        return JSONResponse(status_code=404, content={"error": "源文件不存在"})

    with open(src_path, "r", encoding="utf-8") as f:
        raw = f.read()

    # 分离标题和内容
    title = ""
    content = raw
    if fmt == "latex":
        # 从 LaTeX 中提取标题
        m = re.search(r'\\title\{([^}]+)\}', raw)
        if m:
            title = m.group(1).strip()
        # 返回完整 LaTeX 源码作为内容
    else:
        if raw.startswith("# "):
            lines = raw.split("\n", 1)
            title = lines[0][2:].strip()
            content = lines[1].strip() if len(lines) > 1 else ""

    return {"title": title, "content": content, "name": name, "format": fmt}


@app.post("/api/regenerate-paper")
async def regenerate_paper(request: Request):
    """用编辑后的内容重新生成论文 PDF"""
    data = await parse_json_body(request)
    if not data:
        return JSONResponse(status_code=400, content={"error": "请求体格式错误"})
    name = (data.get("name", "") or "").strip()
    title = (data.get("title", "") or "").strip()
    content = (data.get("content", "") or "").strip()
    fmt = (data.get("format", "markdown") or "").strip()
    if not name or not title:
        return JSONResponse(status_code=400, content={"error": "缺少 name 或 title 参数"})
    if ".." in name or "/" in name or "\\" in name:
        return JSONResponse(status_code=400, content={"error": "无效的文件名"})

    result = regenerate_document(name, title, content, fmt)
    return result


@app.get("/static/papers/{filename:path}")
async def serve_paper(filename: str):
    """提供论文 PDF 文件，强制内联显示（不触发下载）"""
    if ".." in filename or "/" in filename or "\\" in filename:
        return JSONResponse(status_code=400, content={"error": "无效的文件名"})
    papers_dir = os.path.join(STATIC_DIR, "papers")
    path = os.path.join(papers_dir, filename)
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "文件不存在"})
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )


def _ensure_pptx_pdf(pptx_path: str, pdf_path: str) -> bool:
    """尝试将 PPTX 转换为 PDF（同步，运行在 threadpool 中）。返回是否成功。"""
    # 尝试用 PowerShell + PowerPoint COM 转换
    try:
        ps_cmd = (
            f'$ppt=New-Object -ComObject PowerPoint.Application;'
            f'$ppt.Visible=$false;'
            f'$pres=$ppt.Presentations.Open("{pptx_path}");'
            f'$pres.SaveAs("{pdf_path}",32);'
            f'$pres.Close();'
            f'$ppt.Quit();'
            f'[Runtime.InteropServices.Marshal]::ReleaseComObject($ppt)'
        )
        subprocess.run(["powershell", "-Command", ps_cmd], timeout=120,
                       capture_output=True,
                       creationflags=0x08000000 if os.name == "nt" else 0)
    except Exception:
        pass

    # 如果 COM 不可用，尝试 WSL LibreOffice
    if not os.path.exists(pdf_path):
        try:
            wsl_pptx = "/mnt/i/Agent/server/static/papers/" + os.path.basename(pptx_path)
            wsl_out = "/mnt/i/Agent/server/static/papers/"
            subprocess.run(
                ["wsl", "libreoffice", "--headless", "--convert-to", "pdf", "--outdir", wsl_out, wsl_pptx],
                timeout=120, capture_output=True
            )
        except Exception:
            pass

    return os.path.exists(pdf_path)


@app.get("/api/pptx-preview/{filename:path}")
async def pptx_preview(filename: str):
    """将 PPTX 转 PDF 后返回，供在线预览"""
    if ".." in filename or "/" in filename or "\\" in filename:
        return JSONResponse(status_code=400, content={"error": "无效的文件名"})

    papers_dir = os.path.join(STATIC_DIR, "papers")
    pptx_path = os.path.join(papers_dir, filename)
    if not os.path.exists(pptx_path):
        return JSONResponse(status_code=404, content={"error": "PPTX 文件不存在"})

    # 检查是否已有缓存的 PDF
    pdf_name = filename.rsplit(".", 1)[0] + ".pdf"
    pdf_path = os.path.join(papers_dir, pdf_name)
    if not os.path.exists(pdf_path):
        ok = await run_in_threadpool(_ensure_pptx_pdf, pptx_path, pdf_path)
        if not ok:
            return JSONResponse(status_code=500,
                                content={"error": "无法转换 PPTX，请确认已安装 PowerPoint 或 LibreOffice"})

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )


# ==================== WebSocket 路由 ====================

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    """统一的 WebSocket 入口 —— 消息分发到对应的 handler"""
    await websocket.accept()
    state.loop = asyncio.get_running_loop()

    # 静默吞掉 WebSocket 客户端非优雅断开时的 ConnectionResetError
    # SelctorEventLoop 策略已从源头规避，此 handler 作为兜底保险
    if not state._loop_handler_set:
        _prev_handler = state.loop.get_exception_handler()

        def _silent_handler(_loop, context):
            exc = context.get("exception")
            if isinstance(exc, ConnectionResetError):
                return
            # 其余异常走默认处理
            if _prev_handler is not None:
                _prev_handler(_loop, context)
            else:
                _loop.default_exception_handler(context)

        state.loop.set_exception_handler(_silent_handler)
        state._loop_handler_set = True

    client_type = None
    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # 发送 keepalive ping，防止长时间无消息时断连
                try:
                    if websocket.client_state.name == "CONNECTED":
                        await websocket.send_text('{"type":"ping"}')
                except Exception:
                    break
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            msg_type = msg.get("type")
            handler = _HANDLERS.get(msg_type)
            if handler:
                try:
                    client_type = await handler(websocket, msg, client_type)
                except Exception as e:
                    # 单个 handler 异常不应杀死整个 WS 连接循环
                    logger.exception(f"[WebSocket] 处理 {msg_type} 异常: {e}")
                    await _send_ws(websocket, {"type": "error", "content": f"处理 {msg_type} 失败，请重试"})
            else:
                logger.info(f"[WebSocket] 未知消息类型: {msg_type}")

    except WebSocketDisconnect:
        logger.info("[WebSocket] 客户端断开")
    except Exception as e:
        logger.info(f"[WebSocket] 连接异常: {e}")
    finally:
        if client_type == "pc":
            state.pc_ws = None
        elif client_type == "mobile":
            state.mobile_ws = None
            await _on_mobile_disconnect()
        logger.info(f"[WebSocket] {client_type} 已断开")


async def _handle_register(ws, msg, client_type):
    """客户端注册：绑定 WS 连接，发送历史消息和会话列表"""

    ct = msg.get("client_type")
    if ct == "pc":
        state.pc_ws = ws
    elif ct == "mobile":
        state.mobile_ws = ws
    else:
        await _send_ws(ws, {"type": "error", "content": "未知客户端类型"})
        return None

    is_online = (
        (ct == "pc" and state.agent_location == DEVICE_PC) or
        (ct == "mobile" and state.agent_location == DEVICE_MOBILE)
    )
    await _send_ws(ws, {
        "type": "status",
        "state.agent_location": state.agent_location,
        "status": "online" if is_online else "offline",
    })

    session_id = ensure_session(state)
    messages = database.get_all_messages(session_id)
    if messages:
        formatted = format_messages_for_ws(messages)
        await _send_ws(ws, {"type": "history", "messages": formatted})

    # 恢复活跃进度条（刷新页面后不丢失）
    from agent.tools import _PROGRESS_SNAPSHOT
    for tool_name, p in list(_PROGRESS_SNAPSHOT.items()):
        await _send_ws(ws, {"type": "progress", "tool": tool_name,
                            "percent": p.get("percent", 0),
                            "message": p.get("message", "")})

    sessions = database.get_active_sessions()
    await _send_ws(ws, {
        "type": "session_list",
        "sessions": format_sessions_list(sessions),
        "current": session_id,
    })
    return ct


async def _handle_switch_session(ws, msg, client_type):
    """切换会话：验证目标会话，加载历史消息"""
    target = msg.get("session_id", "")
    if target:
        target = fallback_session(target, state)
        state.current_session_id = target
        messages = database.get_all_messages(target)
        formatted = format_messages_for_ws(messages)
        await _send_ws(ws, {"type": "history", "messages": formatted})
        sessions = database.get_active_sessions()
        await _send_ws(ws, {
            "type": "session_list",
            "sessions": format_sessions_list(sessions),
            "current": target,
        })
    return client_type


async def _handle_chat_msg(ws, msg, client_type):
    """处理用户对话消息"""
    if client_type is None:
        await _send_ws(ws, {"type": "error", "content": "请先注册客户端类型"})
        return client_type

    if (client_type == "pc" and state.agent_location != DEVICE_PC) or \
       (client_type == "mobile" and state.agent_location != DEVICE_MOBILE):
        await _send_ws(ws, {"type": "response", "content": "Agent 当前不在本设备上，无法对话"})
        return client_type

    if state.agent_location == "migrating":
        await _send_ws(ws, {"type": "response", "content": "Agent 正在迁移中，请稍候..."})
        return client_type

    content = msg.get("content", "")

    # ── 流式增量缓冲：减少 WS 消息数量，同时保持实时感 ──
    _stream_buf = {"text": "", "started": False}

    def _flush_stream(force: bool = False):
        buf = _stream_buf["text"]
        if not buf:
            return
        if force or len(buf) >= 8:
            if not _stream_buf["started"]:
                _safe_send(ws, {"type": "stream_start"})
                _stream_buf["started"] = True
            _safe_send(ws, {"type": "stream_delta", "delta": buf})
            _stream_buf["text"] = ""

    def _on_chunk(delta: str):
        _stream_buf["text"] += delta
        _flush_stream()

    def _on_progress(p: dict):
        _safe_send(ws, {"type": "progress", **p})

    reply = await run_in_threadpool(
        _handle_chat, content, client_type,
        on_step=lambda step: _safe_send(ws, {"type": "process", "step": step}),
        on_chunk=_on_chunk,
        on_progress=_on_progress,
    )
    # 刷新剩余缓冲，并发送完整结果（含图片/论文标记）供前端最终渲染
    _flush_stream(force=True)
    await _send_ws(ws, {"type": "stream_done", "content": reply})
    return client_type


async def _handle_migrate_ack(ws, msg, client_type):
    """处理设备迁移确认"""
    with state.lock:
        if state.agent_location != "migrating":
            return client_type
        _cancel_migrate_timer()
        if msg.get("status") == "ok":
            if client_type == "mobile":
                state.agent_location = DEVICE_MOBILE
            elif client_type == "pc":
                state.agent_location = DEVICE_PC
            set_current_device(state.agent_location)
            database.update_current_device(state.agent_location)
            database.update_online_status(True)

    _send_status()
    await _send_ws(ws, {"type": "migrate_ack", "status": "ok"})
    return client_type


async def _handle_music_control(ws, msg, client_type):
    """处理音乐播放控制"""
    mc_action = msg.get("action", "")
    if mc_action in ("pause", "resume", "next", "prev", "seek", "status"):
        args = {"action": mc_action}
        if mc_action == "seek":
            args["seek_seconds"] = msg.get("seek_seconds", 0)
        result = await run_in_threadpool(music_control.execute, args)
        await _send_ws(ws, {"type": "music_state", "result": result})
    return client_type


async def _handle_comfyui_status(ws, msg, client_type):
    """查询 ComfyUI 运行状态"""
    from agent.utils import is_port_open
    running = await run_in_threadpool(is_port_open)
    await _send_ws(ws, {"type": "comfyui_status", "running": running})
    return client_type


async def _handle_comfyui_start(ws, msg, client_type):
    """启动 ComfyUI（后台异步，不阻塞等待）"""
    from agent.tools.custom.image_generation import _start_comfyui
    result = _start_comfyui()
    await _send_ws(ws, {"type": "comfyui_start_result", "success": "失败" not in result,
                       "message": result})
    return client_type

async def _handle_comfyui_restart(ws, msg, client_type):
    """重启 ComfyUI（杀进程树 + 重新启动）"""
    logger.info("[comfyui_restart] 收到重启请求，开始处理...")
    from agent.tools.custom import image_generation as ig
    from agent.utils import is_port_open

    target_pid = None
    if ig._comfyui_proc is not None:
        target_pid = ig._comfyui_proc.pid
        logger.info(f"[comfyui_restart] 进程引用 PID={target_pid}")

    if target_pid is None:
        logger.info("[comfyui_restart] 通过端口查找占用 8188 的进程...")
        try:
            result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=5)
            for line in result.stdout.splitlines():
                if ":8188" in line and "LISTENING" in line:
                    target_pid = int(line.strip().split()[-1])
                    logger.info(f"[comfyui_restart] 找到 PID={target_pid}")
                    break
        except Exception as e:
            logger.info(f"[comfyui_restart] 端口查找失败: {e}")

    for round_num in range(3):
        if target_pid is not None:
            logger.info(f"[comfyui_restart] 第{round_num+1}轮: 终止 PID={target_pid}")
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(target_pid)], capture_output=True, timeout=15)
            except Exception as e:
                logger.info(f"[comfyui_restart] taskkill 失败: {e}")

        await run_in_threadpool(time.sleep, 2)

        if not await run_in_threadpool(is_port_open):
            logger.info("[comfyui_restart] 端口已释放")
            break

        logger.info("[comfyui_restart] 端口仍占用，扫描残留进程...")
        target_pid = None
        try:
            result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=5)
            for line in result.stdout.splitlines():
                if ":8188" in line and "LISTENING" in line:
                    target_pid = int(line.strip().split()[-1])
                    logger.info(f"[comfyui_restart] 发现残留 PID={target_pid}")
                    break
        except Exception as e:
            logger.info(f"[comfyui_restart] 扫描失败: {e}")

        if target_pid is None:
            logger.info("[comfyui_restart] 端口占用但 netstat 找不到 LISTENING 进程（可能在 TIME_WAIT）")
            break

    ig._comfyui_proc = None
    port_free = not await run_in_threadpool(is_port_open)
    logger.info(f"[comfyui_restart] 最终端口状态: {'已释放' if port_free else '仍占用'}")

    if port_free:
        result = await run_in_threadpool(ig._ensure_comfyui_running)
    else:
        result = "端口 8188 仍被占用，请手动执行 netstat -ano | findstr 8188 检查"
    logger.info(f"[comfyui_restart] 重启结果: success={result == ''}, message={result}")
    await _send_ws(ws, {"type": "comfyui_restart_result", "success": result == "",
                       "message": result if result else "ComfyUI 已重启"})
    return client_type


async def _handle_tts_status(ws, msg, client_type):
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as c:
            _ttsu = _cfg_tts_url()
            r = await c.get(f"{_ttsu}/docs")
        await _send_ws(ws, {"type": "tts_status", "running": True, "message": "TTS 在线"})
    except Exception:
        await _send_ws(ws, {"type": "tts_status", "running": False, "message": "TTS 未启动"})
    return client_type


async def _handle_tts_restart(ws, msg, client_type):
    logger.info("[tts_restart] 收到重启请求")
    import subprocess as _sp
    # 杀掉现有 TTS 进程
    try:
        _sp.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10)
        r = _sp.run(["cmd", "/c", 'netstat -ano | findstr :8000 | findstr LISTENING'], capture_output=True, text=True, timeout=10)
        for line in r.stdout.strip().split("\n"):
            parts = line.strip().split()
            if parts and parts[-1].isdigit():
                pid = int(parts[-1])
                _sp.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                logger.info(f"[tts_restart] 已终止 PID={pid}")
    except Exception as e:
        logger.info(f"[tts_restart] 查找/终止进程异常: {e}")
    # 启动新的 TTS
    try:
        from server.proxy_tts import TTS_DIR, TTS_PYTHON
        import os as _os
        env = _os.environ.copy()
        env["HF_ENDPOINT"] = _cfg_hf_endpoint()
        _sp.Popen([TTS_PYTHON, "server.py", "--port", "8000"], cwd=TTS_DIR, env=env,
                  stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        logger.info("[tts_restart] 已启动新 TTS 进程")
        await _send_ws(ws, {"type": "tts_restart_result", "success": True,
                           "message": "TTS 正在重启，约需 30-60 秒"})
    except Exception as e:
        await _send_ws(ws, {"type": "tts_restart_result", "success": False,
                           "message": f"TTS 重启失败: {e}"})
    return client_type


async def _handle_jadeai_status(ws, msg, client_type):
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{_cfg_jadeai_url()}/jade/")
        await _send_ws(ws, {"type": "jadeai_status", "running": True, "message": "JadeAI 在线"})
    except Exception:
        await _send_ws(ws, {"type": "jadeai_status", "running": False, "message": "JadeAI 未启动"})
    return client_type


async def _handle_jadeai_restart(ws, msg, client_type):
    logger.info("[jadeai_restart] 收到重启请求")
    import subprocess as _sp
    # 杀进程
    try:
        r = _sp.run(["cmd", "/c", 'netstat -ano | findstr :3000 | findstr LISTENING'], capture_output=True, text=True, timeout=10)
        for line in r.stdout.strip().split("\n"):
            parts = line.strip().split()
            if parts and parts[-1].isdigit():
                pid = int(parts[-1])
                _sp.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                logger.info(f"[jadeai_restart] 已终止 PID={pid}")
    except Exception as e:
        logger.info(f"[jadeai_restart] 终止异常: {e}")
    # 重启
    try:
        import shutil
        pnpm = shutil.which("pnpm")
        if pnpm:
            _sp.Popen([pnpm, "dev"], cwd=_abs("side-projects/JadeAI-0.4.1"),
                      stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            logger.info("[jadeai_restart] 已启动新 JadeAI 进程")
            await _send_ws(ws, {"type": "jadeai_restart_result", "success": True,
                               "message": "JadeAI 正在重启，约需 20-40 秒"})
        else:
            await _send_ws(ws, {"type": "jadeai_restart_result", "success": False,
                               "message": "pnpm 未安装"})
    except Exception as e:
        await _send_ws(ws, {"type": "jadeai_restart_result", "success": False,
                           "message": f"JadeAI 重启失败: {e}"})
    return client_type


async def _handle_gpu_release(ws, msg, client_type):
    """释放 GPU 显存：仅卸载模型，不杀服务进程"""
    from agent.tools import _PROGRESS_SNAPSHOT
    _PROGRESS_SNAPSHOT.clear()  # 清除残留进度条
    released = []
    import subprocess as _sp

    # 0. ComfyUI 卸载模型（保留进程）
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{_cfg_comfyui_url()}/api/free",
                            json={"unload_models": True, "free_memory": True})
            if r.status_code == 200:
                released.append("ComfyUI 模型")
    except Exception:
        pass

    # 1. 卸载 Ollama 模型（服务保持运行，下次自动加载）
    try:
        _sp.run([OLLAMA_EXE, "stop", OLLAMA_VISION_MODEL],
                capture_output=True, timeout=10)
        released.append("Ollama 模型")
    except Exception:
        pass

    # 2. ChatTTS 卸载模型（调用其 API）
    try:
        import urllib.request
        _ttsu = _cfg_tts_url()
        urllib.request.urlopen(f"{_ttsu}/api/unload", timeout=5)
        released.append("ChatTTS 模型")
    except Exception:
        pass

    # 3. 清 CUDA 缓存
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            released.append("CUDA cache")
    except Exception:
        pass

    result = "已释放: " + (", ".join(released) if released else "无需释放（GPU 已空闲）")
    logger.info(f"[gpu_release] {result}")
    await _send_ws(ws, {"type": "gpu_release_result", "success": True, "message": result})
    # 通知前端清除所有进度条
    for tool_name in list(_PROGRESS_SNAPSHOT.keys()):
        await _send_ws(ws, {"type": "progress", "tool": tool_name, "percent": 100, "message": "已完成"})
        _PROGRESS_SNAPSHOT.pop(tool_name, None)
    return client_type


async def _handle_shutdown(ws, msg, client_type):
    """优雅退出：根据用户选择保留/关闭后台服务，然后退出主程序"""
    keep = msg.get("keep_services", [])
    import subprocess as _sp
    import agent.tools.custom.image_generation as ig

    if "comfyui" not in keep:
        if ig._comfyui_proc:
            try: ig._comfyui_proc.terminate(); ig._comfyui_proc.wait(timeout=5)
            except Exception: pass
            ig._comfyui_proc = None
        await _kill_port(8188)
    if "chattts" not in keep:
        await _kill_port(8001)
    if "tts" not in keep:
        await _kill_port(8000)
    if "ollama" not in keep:
        try:
            _sp.run(["taskkill", "/F", "/IM", "ollama.exe"], capture_output=True, timeout=10)
        except Exception:
            pass
    if "jadeai" not in keep:
        await _kill_port(3000)

    await _send_ws(ws, {"type": "shutdown_result", "success": True,
                       "message": "程序即将退出"})

    # 异步退出，给 WS 消息发送留时间
    def _exit():
        import time, os
        time.sleep(0.8)
        os._exit(0)
    import threading
    threading.Thread(target=_exit, daemon=True).start()
    return client_type


async def _kill_port(port: int) -> bool:
    """杀掉指定端口的进程，返回是否成功。"""
    import subprocess as _sp
    try:
        r = _sp.run(["cmd", "/c", f"netstat -ano | findstr :{port} | findstr LISTENING"],
                   capture_output=True, text=True, timeout=10)
        for line in r.stdout.strip().split("\n"):
            parts = line.strip().split()
            if parts and parts[-1].isdigit():
                _sp.run(["taskkill", "/F", "/PID", parts[-1]], capture_output=True)
                logger.info(f"[stop:{port}] killed PID={parts[-1]}")
        return True
    except Exception as e:
        logger.info(f"[stop:{port}] error: {e}")
        return False


async def _handle_comfyui_stop(ws, msg, client_type):
    import agent.tools.custom.image_generation as ig
    import torch
    # 1. 先杀主进程
    if ig._comfyui_proc:
        try:
            ig._comfyui_proc.terminate()
            ig._comfyui_proc.wait(timeout=5)
        except Exception:
            try: ig._comfyui_proc.kill()
            except Exception: pass
        ig._comfyui_proc = None
    # 2. 清端口残留
    await _kill_port(8188)
    # 3. 清 CUDA 缓存
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception: pass
    await _send_ws(ws, {"type": "comfyui_stop_result", "success": True, "message": "ComfyUI 已关闭，显存已释放"})
    return client_type


async def _handle_tts_stop(ws, msg, client_type):
    await _kill_port(8000)
    await _send_ws(ws, {"type": "tts_stop_result", "success": True, "message": "TTS 已关闭"})
    return client_type


async def _handle_jadeai_stop(ws, msg, client_type):
    await _kill_port(3000)
    await _send_ws(ws, {"type": "jadeai_stop_result", "success": True, "message": "JadeAI 已关闭"})
    return client_type


# ==================== Ollama 本地视觉模型 ====================
OLLAMA_EXE = _OLLAMA_EXE or _cfg_ollama_exe()
OLLAMA_MODELS_DIR = _OLLAMA_MODELS or _cfg_ollama_models_dir()
OLLAMA_PORT = _cfg_ollama_port()
OLLAMA_VISION_MODEL = _cfg_ollama_vision()


async def _handle_ollama_status(ws, msg, client_type):
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"http://localhost:{OLLAMA_PORT}/api/version")
        await _send_ws(ws, {"type": "ollama_status", "running": True,
                           "message": f"Ollama 在线 (v{r.json().get('version', '?')})"})
    except Exception:
        await _send_ws(ws, {"type": "ollama_status", "running": False, "message": "Ollama 未启动"})
    return client_type


async def _handle_ollama_start(ws, msg, client_type):
    logger.info("[ollama_start] 收到启动请求")
    import subprocess as _sp
    if not os.path.isfile(OLLAMA_EXE):
        await _send_ws(ws, {"type": "ollama_start_result", "success": False,
                           "message": f"未找到 Ollama: {OLLAMA_EXE}"})
        return client_type
    try:
        env = os.environ.copy()
        env["OLLAMA_MODELS"] = OLLAMA_MODELS_DIR
        env["OLLAMA_HOST"] = f"127.0.0.1:{OLLAMA_PORT}"
        _sp.Popen([OLLAMA_EXE, "serve"], env=env, creationflags=_sp.CREATE_NO_WINDOW,
                  stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        logger.info("[ollama_start] 已启动 Ollama 进程")
        await _send_ws(ws, {"type": "ollama_start_result", "success": True,
                           "message": "Ollama 正在启动（视觉模型 qwen3-vl:4b 按需加载）"})
    except Exception as e:
        await _send_ws(ws, {"type": "ollama_start_result", "success": False,
                           "message": f"Ollama 启动失败: {e}"})
    return client_type


async def _handle_ollama_stop(ws, msg, client_type):
    import subprocess as _sp
    try:
        _sp.run(["taskkill", "/F", "/IM", "ollama.exe"], capture_output=True, timeout=10)
    except Exception as e:
        logger.info(f"[ollama_stop] error: {e}")
    await _send_ws(ws, {"type": "ollama_stop_result", "success": True, "message": "Ollama 已关闭"})
    return client_type


async def _handle_autolabel_status(ws, msg, client_type):
    global _autolabel_pid
    running = _autolabel_pid is not None
    await _send_ws(ws, {"type": "autolabel_status", "running": running,
                        "message": "AutoLabel GUI 已运行" if running else "AutoLabel 未启动"})
    return client_type


async def _handle_autolabel_start(ws, msg, client_type):
    global _autolabel_pid
    logger.info("[autolabel_start] 启动 AutoLabel Dock GUI")
    import subprocess as _sp
    try:
        import os as _os
        log_dir = _os.path.dirname(AUTOSTART_CFG)  # .../config/
        err_path = _os.path.join(_os.path.dirname(log_dir), "autolabel_crash.log")
        err_fd = open(err_path, "a")
        env = _os.environ.copy()
        torch_lib = _TORCH_LIB or _cfg_torch_lib()
        if torch_lib and torch_lib not in env.get("PATH", ""):
            env["PATH"] = torch_lib + _os.pathsep + env.get("PATH", "")
        python_exe = _PYTHON_EXE or sys.executable
        p = _sp.Popen(
            [python_exe, "main.py"],
            cwd=_abs("side-projects/autolabel-dock-main"),
            stdout=err_fd, stderr=err_fd,
            env=env,
        )
        _autolabel_pid = p.pid
        await _send_ws(ws, {"type": "autolabel_start_result", "success": True})
    except Exception as e:
        await _send_ws(ws, {"type": "autolabel_start_result", "success": False,
                           "message": f"启动失败: {e}"})
    return client_type


async def _handle_autolabel_stop(ws, msg, client_type):
    global _autolabel_pid
    import subprocess as _sp
    if _autolabel_pid:
        try:
            _sp.run(["taskkill", "/F", "/PID", str(_autolabel_pid)], capture_output=True, timeout=10)
        except Exception:
            pass
        _autolabel_pid = None
    await _send_ws(ws, {"type": "autolabel_stop_result", "success": True})
    return client_type


# 消息类型 → 处理函数 映射表
_HANDLERS = {
    "register":          _handle_register,
    "switch_session":    _handle_switch_session,
    "chat":              _handle_chat_msg,
    "migrate_ack":       _handle_migrate_ack,
    "music_control":     _handle_music_control,
    "comfyui_status":    _handle_comfyui_status,
    "comfyui_start":     _handle_comfyui_start,
    "comfyui_restart":   _handle_comfyui_restart,
    "tts_start":         _handle_tts_restart,
    "tts_status":        _handle_tts_status,
    "tts_restart":       _handle_tts_restart,
    "gpu_release":       _handle_gpu_release,
    "shutdown":          _handle_shutdown,
    "jadeai_start":      _handle_jadeai_restart,
    "jadeai_status":     _handle_jadeai_status,
    "jadeai_restart":    _handle_jadeai_restart,
    "comfyui_stop":      _handle_comfyui_stop,
    "tts_stop":          _handle_tts_stop,
    "jadeai_stop":       _handle_jadeai_stop,
    "ollama_status":     _handle_ollama_status,
    "ollama_start":      _handle_ollama_start,
    "ollama_stop":       _handle_ollama_stop,
    "autolabel_status":  _handle_autolabel_status,
    "autolabel_start":   _handle_autolabel_start,
    "autolabel_stop":    _handle_autolabel_stop,
}


# ==================== 文件格式转换 API ====================


@app.post("/api/convert/detect")
async def api_convert_detect(filepath: str = ""):
    from tools.file_converter import detect_format
    return detect_format(filepath)


@app.post("/api/convert/ext-detect")
async def api_convert_ext_detect(data: dict):
    from tools.file_converter import detect_format_from_ext
    return detect_format_from_ext(data.get("ext", ""))


@app.post("/api/convert")
async def api_convert(data: dict):
    from tools.file_converter import convert
    filepath = data.get("filepath", "")
    target = data.get("target", "")
    if not filepath or not target:
        return {"success": False, "error": "缺少 filepath 或 target"}
    # Resolve relative paths from data/uploads/
    import os as _o
    if not _o.path.isabs(filepath):
        filepath = _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))), "data", filepath)
    result = convert(filepath, target)
    if result.get("success") and "output" in result:
        output_path = result["output"]
        # Convert absolute path to relative for frontend display
        from pathlib import Path
        project_root = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
        try:
            rel = str(Path(output_path).relative_to(project_root))
        except ValueError:
            rel = output_path
        result["relative_path"] = rel.replace("\\", "/")
        result["folder"] = str(Path(output_path).parent)
        result["folder_rel"] = str(Path(rel).parent).replace("\\", "/")
    return result


# ==================== 文件下载 ====================
@app.get("/api/files/{path:path}")
async def api_download_file(path: str):
    """下载 converted_files 中的文件"""
    import os as _o
    from fastapi.responses import FileResponse
    project_root = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
    full_path = _o.path.join(project_root, path)
    if not _o.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(full_path)


# ==================== TTS 语音合成代理（逐句） ====================
@app.post("/api/tts/speak")
async def api_tts_speak(data: dict):
    """接收 {text, lang, reference} → 调 TTS → 返回 WAV 音频
    优先 ChatTTS(8001)，不可用时回退 Confucius4(8000)
    """
    text = data.get("text", "").strip()
    lang = data.get("lang", "zh")
    reference = data.get("reference", "")
    if not text or not reference:
        return {"error": "缺少 text 或 reference"}
    import os as _o, httpx as _h
    if not _o.path.isfile(reference):
        return {"error": f"参考音频不存在: {reference}"}

    async def _call_tts(url: str):
        async with _h.AsyncClient(timeout=60) as c:
            with open(reference, "rb") as rf:
                files = {"reference": (_o.path.basename(reference), rf, "audio/mpeg")}
                r = await c.post(url, data={"text": text, "lang": lang}, files=files)
            if r.status_code == 200:
                from fastapi.responses import Response
                return Response(content=r.content, media_type="audio/wav",
                    headers={"X-Duration-Sec": r.headers.get("X-Duration-Sec", "?")})
            return None

    # 优先 ChatTTS（快），不可用时回退 Confucius4
    _tts_url = _cfg_tts_url()
    try:
        result = await _call_tts(f"{_tts_url}/api/tts")
        if result is not None:
            return result
    except Exception:
        pass

    return {"error": "所有 TTS 后端不可用"}


@app.get("/api/tts/detect-ref")
async def api_tts_detect_ref():
    """扫描 data/uploads/ 目录，返回找到的第一个音频文件路径作为 TTS 参考音色"""
    import os as _o, glob as _g
    up = _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "data", "uploads")
    if not _o.path.isdir(up):
        return {"ref": None}
    for ext in ("*.mp3", "*.wav", "*.m4a", "*.flac"):
        files = _g.glob(_o.path.join(up, ext))
        if files:
            return {"ref": _o.path.abspath(files[0])}
    return {"ref": None}


# ==================== TTS 语音合成工作室 ====================
@app.get("/tts/studio")
async def tts_studio():
    from fastapi.responses import FileResponse
    import os as _o
    return FileResponse(_o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "templates", "tts.html"))


# ==================== Confucius4-TTS 反向代理 ====================
from server.proxy_tts import proxy_to_tts
from server.proxy_utils import proxy_request


@app.api_route("/tts/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"])
async def tts_proxy(request: Request, path: str = ""):
    """代理所有 /tts/* 请求到 Confucius4-TTS 服务（localhost:8000）"""
    return await proxy_to_tts(request, path)


# ==================== ChatTTS 反向代理 ====================
@app.api_route("/chattts/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"])
async def chattts_proxy(request: Request, path: str = ""):
    """代理所有 /chattts/* 请求到 ChatTTS 服务（localhost:8001）"""
    qs = request.url.query.decode() if request.url.query else ""
    _tts_url = _cfg_tts_url()
    target = f"{_tts_url}/{path}" if path else f"{_tts_url}/"
    if qs:
        target += f"?{qs}"
    return await proxy_request(request, target, f"{_tts_url.replace('http://','')}", "chattts-proxy", "ChatTTS")


# ==================== JadeAI 反向代理 ====================
# 所有 /jade/* 请求透明转发到 JadeAI Next.js 服务（localhost:3000）
# JadeAI 配置了 basePath="/jade"，因此路径无需重写
from server.proxy import proxy_to_jade


@app.api_route("/jade/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def jade_proxy(request: Request, path: str = ""):
    """代理所有 /jade/* 请求到 JadeAI Next.js 服务（localhost:3000）"""
    return await proxy_to_jade(request, path)


# ==================== 独立 DELETE 端点（直达 app，不依赖 APIRouter） ====================
# 注意：/batch 必须在 /{session_id} 之前注册，否则 batch 会被路径参数捕获

@app.delete("/api/sessions/batch")
async def app_batch_delete_sessions(request: Request):
    """批量删除会话（直接注册在 app 上）"""
    data = await parse_json_body(request)
    ids = data.get("session_ids", [])
    if not ids:
        return JSONResponse(status_code=400, content={"error": "没有指定会话"})
    logger.info(f"[app.batch_delete] 收到批量删除请求: {ids}")
    
    for sid in ids:
        database.delete_session(sid)
        if state.current_session_id == sid:
            state.current_session_id = fallback_session(sid, state)
    
    sessions = database.get_active_sessions()
    logger.info(f"[app.batch_delete] 批量删除完成，剩余会话数: {len(sessions)}")
    
    return {
        "status": "deleted",
        "count": len(ids),
        "new_current": state.current_session_id,
        "sessions": sessions,
    }


@app.delete("/api/sessions/{session_id}")
async def app_delete_session(session_id: str):
    """删除指定会话（直接注册在 app 上，确保万无一失）"""
    logger.info(f"[app.delete_session] 收到删除请求: session_id={session_id}")
    database.delete_session(session_id)
    logger.info(f"[app.delete_session] 数据库删除完成: session_id={session_id}")
    
    if state.current_session_id == session_id:
        state.current_session_id = fallback_session(session_id, state)
        logger.info(f"[app.delete_session] 当前会话被删，回退到 {state.current_session_id}")
    
    sessions = database.get_active_sessions()
    logger.info(f"[app.delete_session] 剩余会话数: {len(sessions)}")
    
    return {
        "status": "deleted",
        "session_id": session_id,
        "new_current": state.current_session_id,
        "sessions": sessions,
    }


# ==================== 注册 API 路由（APIRouter） ====================
from server.api import api_router
app.include_router(api_router)

# ==================== 静态文件 ====================
# 注意：/static/papers 由上面的显式路由以 inline PDF 方式提供，
# 其余静态资源（script.js / mobile.js / spine 等）走 StaticFiles 挂载。
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
