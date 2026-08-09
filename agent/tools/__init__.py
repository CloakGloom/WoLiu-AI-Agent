"""
工具调度中心 —— 聚合所有子模块工具，统一对外暴露
目录结构：
  builtin/    → 内建工具（时间、天气、计算、迁移、状态）
  hardware/   → 硬件工具（按 pc/phone 分设备实现）
  custom/     → 用户自定义工具（音乐控制等）
  ai_custom/  → AI自定义工具（通过AI会话直接创建）
"""

import json
import os
import importlib
import time
import threading
from config import DEVICE_PC, DEVICE_MOBILE
from agent import database

# ==================== 工具进度回调（thread-local） ====================
#
# run_agent 在执行前通过 set_progress_callback 注册回调，
# 工具内部在耗时操作的关键节点调用 emit_progress 上报进度，
# 最终由服务器层推送到前端渲染为进度条。

_progress_ctx = threading.local()

# 活跃进度追踪（供 WebSocket 重连恢复）
_PROGRESS_SNAPSHOT = {}


def set_progress_callback(cb):
    """注册当前线程的工具进度回调（可为 None）"""
    _progress_ctx.cb = cb


def clear_progress_callback():
    """清除当前线程的工具进度回调"""
    _progress_ctx.cb = None


def emit_progress(tool: str, percent: float, message: str = "", **extra):
    """工具内部上报进度。percent 取值 0-100。无回调时静默忽略。"""
    cb = getattr(_progress_ctx, "cb", None)
    if not cb:
        return
    try:
        payload = {
            "tool": tool,
            "percent": round(max(0.0, min(100.0, float(percent))), 1),
            "message": message,
        }
        payload.update(extra)
        # 保存进度快照（WebSocket 重连时恢复）
        if round(percent) >= 100:
            _PROGRESS_SNAPSHOT.pop(tool, None)
        else:
            _PROGRESS_SNAPSHOT[tool] = payload
        cb(payload)
    except Exception:
        pass

# ==================== 禁用工具持久化 ====================

DISABLED_TOOLS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "user_prefs", "disabled_tools.json")

def _load_disabled_tools() -> set:
    """加载被禁用的工具名集合"""
    try:
        if os.path.exists(DISABLED_TOOLS_FILE):
            with open(DISABLED_TOOLS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("disabled", []))
    except Exception:
        pass
    return set()

def _save_disabled_tools(disabled: set):
    """保存被禁用的工具名集合"""
    os.makedirs(os.path.dirname(DISABLED_TOOLS_FILE), exist_ok=True)
    with open(DISABLED_TOOLS_FILE, "w", encoding="utf-8") as f:
        json.dump({"disabled": sorted(disabled)}, f, ensure_ascii=False, indent=2)

# 当前禁用的工具名集合
_disabled_tools = _load_disabled_tools()

# ==================== 导入所有工具模块 ====================

def _safe_import(module_path: str, alias_name: str):
    """
    安全导入工具模块。依赖缺失或 DLL 错误时返回 None 并记录警告。
    这允许 MCP Server 在不安装全部可选依赖的情况下加载可用工具。
    """
    try:
        return importlib.import_module(module_path)
    except Exception as e:
        print(f"[tools] 跳过 {alias_name}: {e}", file=__import__('sys').stderr)
        return None

def _safe_import_attr(module_path: str, attr_name: str):
    """安全导入模块的特定属性"""
    try:
        mod = importlib.import_module(module_path)
        return getattr(mod, attr_name)
    except Exception as e:
        print(f"[tools] 跳过 {module_path}.{attr_name}: {e}", file=__import__('sys').stderr)
        return None

datetime_tool = _safe_import("agent.tools.builtin.datetime_tool", "datetime_tool")
weather = _safe_import("agent.tools.builtin.weather", "weather")
calculator = _safe_import("agent.tools.builtin.calculator", "calculator")
web_search = _safe_import("agent.tools.builtin.web_search", "web_search")
web_fetch = _safe_import("agent.tools.builtin.web_fetch", "web_fetch")
migrate = _safe_import("agent.tools.builtin.migrate", "migrate")
status = _safe_import("agent.tools.builtin.status", "status")
diagnostics = _safe_import("agent.tools.builtin.diagnostics", "diagnostics")
switch = _safe_import("agent.tools.hardware.switch", "switch")
pc_mic = _safe_import("agent.tools.hardware.pc.microphone", "pc_mic")
pc_spk = _safe_import("agent.tools.hardware.pc.speaker", "pc_spk")
pc_cam = _safe_import("agent.tools.hardware.pc.camera", "pc_cam")
phone_mic = _safe_import("agent.tools.hardware.phone.microphone", "phone_mic")
phone_spk = _safe_import("agent.tools.hardware.phone.speaker", "phone_spk")
phone_cam = _safe_import("agent.tools.hardware.phone.camera", "phone_cam")
music_control = _safe_import("agent.tools.custom.music_control", "music_control")
character_expression = _safe_import("agent.tools.custom.character_expression", "character_expression")
image_generation = _safe_import("agent.tools.custom.image_generation", "image_generation")
paper_generator = _safe_import("agent.tools.custom.paper_generator", "paper_generator")
file_reader = _safe_import("agent.tools.custom.file_reader", "file_reader")
ppt_generator = _safe_import("agent.tools.custom.ppt_generator", "ppt_generator")
kimi_ppt = _safe_import("agent.tools.custom.kimi_ppt", "kimi_ppt")
presenton_bridge = _safe_import("agent.tools.custom.presenton_bridge", "presenton_bridge")
recall_context = _safe_import("agent.tools.custom.recall_context", "recall_context")
mock_interview = _safe_import("agent.tools.custom.mock_interview", "mock_interview")
tts = _safe_import("agent.tools.custom.tts", "tts")
jadeai_resume = _safe_import("agent.tools.custom.jadeai_resume", "jadeai_resume")
memory_management = _safe_import("agent.tools.custom.memory_management", "memory_management")
video_generation_i2v = _safe_import("agent.tools.custom.video_generation_i2v", "video_generation_i2v")
autolabel_train = _safe_import("agent.tools.custom.autolabel_train", "autolabel_train")
autolabel_predict = _safe_import("agent.tools.custom.autolabel_predict", "autolabel_predict")
autolabel_dataset = _safe_import("agent.tools.custom.autolabel_dataset", "autolabel_dataset")
modelscope_tool = _safe_import("agent.tools.custom.modelscope_tool", "modelscope_tool")
video_generation_t2v = _safe_import("agent.tools.custom.video_generation_t2v", "video_generation_t2v")

# ==================== 当前设备状态 ====================

_current_device = DEVICE_PC


def set_current_device(device: str):
    global _current_device
    _current_device = device


def get_current_device() -> str:
    return _current_device


# ==================== AI自定义工具自动扫描 ====================

_ai_custom_modules = []  # 存放动态加载的模块引用

def _scan_ai_custom_tools():
    """扫描 agent/tools/ai_custom/ 目录，动态加载所有 .py 工具模块"""
    _ai_custom_modules.clear()
    ai_custom_dir = os.path.join(os.path.dirname(__file__), "ai_custom")
    if not os.path.isdir(ai_custom_dir):
        return

    for fname in sorted(os.listdir(ai_custom_dir)):
        if fname.startswith("_") or not fname.endswith(".py"):
            continue
        mod_name = fname[:-3]  # 去掉 .py
        try:
            mod = importlib.import_module(f"agent.tools.ai_custom.{mod_name}")
            if hasattr(mod, "SCHEMA") and hasattr(mod, "execute"):
                _ai_custom_modules.append(mod)
                print(f"[AI自定义] 已加载工具: {mod_name}")
            else:
                print(f"[AI自定义] 跳过 {mod_name}: 缺少 SCHEMA 或 execute")
        except Exception as e:
            print(f"[AI自定义] 加载 {mod_name} 失败: {e}")

_scan_ai_custom_tools()


# ==================== 工具注册表 ====================

# 每个元组: (工具名, 模块, 是否需要传入 current_device)
_TOOL_REGISTRY = [
    ("get_current_time", datetime_tool, False),
    ("get_weather", weather, False),
    ("calculate", calculator, False),
    ("web_search", web_search, False),
    ("web_fetch", web_fetch, False),
    ("migrate_agent", migrate, True),
    ("get_agent_status", status, True),
    ("run_diagnostics", diagnostics, False),
    ("switch_hardware", switch, False),
    ("use_microphone", None, True),   # 按设备分发
    ("use_speaker", None, True),      # 按设备分发
    ("use_camera", None, True),       # 按设备分发
    ("music_control", music_control, False),
    ("set_expression", character_expression, False),
    ("generate_image", image_generation, False),
    ("generate_paper", paper_generator, False),
    ("read_document", file_reader, False),
    ("generate_ppt", ppt_generator, False),
    ("generate_kimi_ppt", kimi_ppt, False),
    ("generate_presenton_ppt", presenton_bridge, False),
    ("recall_context", recall_context, False),
    ("mock_interview", mock_interview, False),
    ("tts_speak", tts, False),
    ("jadeai_resume", jadeai_resume, False),
    ("manage_memory", memory_management, False),
    ("generate_video_i2v", video_generation_i2v, False),
    ("generate_video_t2v", video_generation_t2v, False),
    ("yolo_train", autolabel_train, False),
    ("yolo_predict", autolabel_predict, False),
    ("yolo_dataset_manage", autolabel_dataset, False),
    ("modelscope_model", modelscope_tool, False),
]

# 过滤掉导入失败的模块（模块为 None 且不是硬件工具）
_TOOL_REGISTRY = [
    (name, mod, nd) for name, mod, nd in _TOOL_REGISTRY
    if mod is not None or name in ("use_microphone", "use_speaker", "use_camera")
]

# 聚合所有 TOOLS 定义（只包含成功导入的模块）
def _safe_schema(mod, name, builtin_schema=None):
    """安全获取模块的 SCHEMA，模块为 None 时使用内置 schema 或跳过"""
    if mod is not None:
        return mod.SCHEMA
    return builtin_schema

TOOLS = list(filter(None, [
    _safe_schema(datetime_tool, "datetime_tool"),
    _safe_schema(weather, "weather"),
    _safe_schema(calculator, "calculator"),
    _safe_schema(web_search, "web_search"),
    _safe_schema(web_fetch, "web_fetch"),
    _safe_schema(migrate, "migrate"),
    _safe_schema(status, "status"),
    _safe_schema(diagnostics, "diagnostics"),
    _safe_schema(switch, "switch"),
    # 硬件工具的内联 SCHEMA
    {
        "type": "function",
        "tag": "设备",
        "function": {
            "name": "use_microphone",
            "description": "调用当前所在设备的麦克风进行录音",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration": {"type": "integer", "description": "录音时长（秒）"}
                },
                "required": ["duration"],
            },
        },
    },
    {
        "type": "function",
        "tag": "设备",
        "function": {
            "name": "use_speaker",
            "description": "调用当前所在设备的扬声器播放文本",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要通过扬声器播放的文本内容"}
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "tag": "设备",
        "function": {
            "name": "use_camera",
            "description": "调用当前所在设备的摄像头拍照",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    _safe_schema(music_control, "music_control"),
    _safe_schema(character_expression, "character_expression"),
    _safe_schema(image_generation, "image_generation"),
    _safe_schema(paper_generator, "paper_generator"),
    _safe_schema(file_reader, "file_reader"),
    _safe_schema(ppt_generator, "ppt_generator"),
    _safe_schema(kimi_ppt, "kimi_ppt"),
    _safe_schema(presenton_bridge, "presenton_bridge"),
    _safe_schema(recall_context, "recall_context"),
    _safe_schema(mock_interview, "mock_interview"),
    _safe_schema(tts, "tts"),
    _safe_schema(jadeai_resume, "jadeai_resume"),
    _safe_schema(memory_management, "memory_management"),
    _safe_schema(video_generation_i2v, "video_generation_i2v"),
    _safe_schema(video_generation_t2v, "video_generation_t2v"),
    _safe_schema(autolabel_train, "autolabel_train"),
    _safe_schema(autolabel_predict, "autolabel_predict"),
    _safe_schema(autolabel_dataset, "autolabel_dataset"),
    _safe_schema(modelscope_tool, "modelscope_tool"),
]))

# 追加 AI 自定义工具
for _mod in _ai_custom_modules:
    TOOLS.append(_mod.SCHEMA)

# 保存原始 TOOLS（含 tag，供 /api/tools 使用）
_RAW_TOOLS = list(TOOLS)

# 为 LLM 构建 TOOLS（去除 tag 字段，过滤禁用工具）
def _strip_tag(schema: dict) -> dict:
    """去除 SCHEMA 中的 tag 字段，返回纯 LLM 格式"""
    return {k: v for k, v in schema.items() if k != "tag"}

def _build_tools_for_llm() -> list:
    """构建发给 LLM 的工具列表，去除 tag 并过滤禁用工具"""
    result = []
    for tool in _RAW_TOOLS:
        name = tool.get("function", {}).get("name", "")
        if name in _disabled_tools:
            continue
        result.append(_strip_tag(tool))
    return result

TOOLS_FOR_LLM = _build_tools_for_llm()

# 构建名称→(模块, need_device) 的快速查找表
_EXECUTORS = {name: (mod, need_dev) for name, mod, need_dev in _TOOL_REGISTRY}
# 追加 AI 自定义工具到执行器
for _mod in _ai_custom_modules:
    _EXECUTORS[_mod.SCHEMA["function"]["name"]] = (_mod, False)


# ==================== 工具启用/禁用管理 ====================

def get_disabled_tools() -> list:
    """获取当前被禁用的工具名列表"""
    return sorted(_disabled_tools)

def toggle_tool(tool_name: str) -> dict:
    """切换工具启用/禁用状态，返回 {'name': ..., 'enabled': bool}"""
    global _disabled_tools, TOOLS_FOR_LLM
    if tool_name in _disabled_tools:
        _disabled_tools.discard(tool_name)
        enabled = True
    else:
        _disabled_tools.add(tool_name)
        enabled = False
    _save_disabled_tools(_disabled_tools)
    TOOLS_FOR_LLM = _build_tools_for_llm()
    return {"name": tool_name, "enabled": enabled}


# ==================== 工具执行 ====================

def _exec_hardware(tool_name: str, arguments: dict) -> str:
    """按当前设备分发硬件工具调用"""
    is_pc = (_current_device == DEVICE_PC)

    if tool_name == "use_microphone":
        duration = arguments.get("duration", 5)
        if is_pc:
            return pc_mic.PcMicrophone().record(duration)
        else:
            return phone_mic.PhoneMicrophone().record(duration)

    elif tool_name == "use_speaker":
        text = arguments.get("text", "")
        if is_pc:
            return pc_spk.PcSpeaker().play(text)
        else:
            return phone_spk.PhoneSpeaker().play(text)

    elif tool_name == "use_camera":
        if is_pc:
            return pc_cam.PcCamera().capture()
        else:
            return phone_cam.PhoneCamera().capture()

    return f"未知硬件工具：{tool_name}"


def execute_tool(tool_name: str, arguments: dict, timeout: float = 60.0) -> str:
    """
    统一工具调度入口，带超时熔断（默认 60 秒）。
    每个工具模块可在 execute() 上设置 ._timeout 属性自定义超时。
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
    from agent.logging_config import get_logger
    _tlog = get_logger("tools.execute")
    
    start_time = time.time()
    exec_status = "success"
    error_msg = None

    # 查询工具函数，获取自定义超时
    entry = None
    if tool_name not in ("use_microphone", "use_speaker", "use_camera"):
        entry = _EXECUTORS.get(tool_name)
        if entry is not None:
            mod_or_fn = entry[0]
            # 兼容两种注册方式：模块(module.execute) 和 直接函数(fn)
            if hasattr(mod_or_fn, 'execute'):
                exec_fn = mod_or_fn.execute
            else:
                exec_fn = mod_or_fn
            tool_timeout = getattr(exec_fn, "_timeout", timeout)
        else:
            tool_timeout = timeout
    else:
        tool_timeout = timeout

    def _do_exec():
        nonlocal exec_status, error_msg
        try:
            if tool_name in ("use_microphone", "use_speaker", "use_camera"):
                return _exec_hardware(tool_name, arguments)
            if entry is None:
                exec_status = "error"
                return f"未知工具：{tool_name}"
            mod_or_fn, need_device = entry
            if hasattr(mod_or_fn, 'execute'):
                fn = mod_or_fn.execute
                if need_device:
                    return fn(arguments, current_device=_current_device)
                return fn(arguments)
            else:
                return mod_or_fn(arguments)
        except TypeError as e:
            exec_status = "error"
            error_msg = str(e)
            return f"参数错误：{e}"
        except Exception as e:
            exec_status = "error"
            error_msg = str(e)
            _tlog.error("tool_exec_error", extra={"tool": tool_name, "error": str(e)})
            return f"工具执行异常：{e}"

    # 将主线程的进度回调注入工作线程（threading.local 不跨线程）
    _cb = getattr(_progress_ctx, 'cb', None)

    def _do_exec_with_progress():
        if _cb is not None:
            set_progress_callback(_cb)
        return _do_exec()

    _tlog.info("tool_exec_start", extra={"tool": tool_name, "timeout": tool_timeout})
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_do_exec_with_progress)
        try:
            result = future.result(timeout=tool_timeout)
        except FutureTimeout:
            exec_status = "error"
            error_msg = f"超时（{tool_timeout}秒）"
            result = f"工具 {tool_name} 执行超时（{tool_timeout}秒），已取消"
            _tlog.warning("tool_exec_timeout",
                          extra={"tool": tool_name, "timeout": tool_timeout,
                                 "elapsed_ms": int((time.time() - start_time) * 1000)})

    duration_ms = int((time.time() - start_time) * 1000)
    _tlog.info("tool_exec_done",
               extra={"tool": tool_name, "status": exec_status, "elapsed_ms": duration_ms})

    # 记录工具调用日志
    session_id = arguments.get("_session_id", "")
    if session_id:
        database.log_tool_call(
            session_id, tool_name,
            json.dumps(arguments, ensure_ascii=False),
            result, exec_status, duration_ms, error_msg
        )

    return result


# ==================== MCP 集成接口 ====================

def get_tool_registry() -> list[dict]:
    """
    导出工具注册表，供 MCP Server 使用。

    返回格式:
    [
        {
            "name": "tool_name",
            "schema": {...},         # 含 tag 的完整 OpenAI function schema
            "execute": callable,
            "need_device": bool,
            "timeout": float,
            "tag": str,
        },
        ...
    ]

    此接口供外部 MCP Server (agent.mcp_server) 批量注册工具时使用，
    也可被其他需要枚举工具信息的模块调用。
    """
    registry = []
    for tool in _RAW_TOOLS:
        name = tool.get("function", {}).get("name", "")
        if not name:
            continue

        exec_info = _EXECUTORS.get(name)

        # 硬件工具 (mod is None) —— 通过 _exec_hardware 分发
        if name in ("use_microphone", "use_speaker", "use_camera"):
            registry.append({
                "name": name,
                "schema": tool,
                "execute": lambda args, tn=name: _exec_hardware(tn, args),
                "need_device": True,
                "timeout": 120.0,
                "tag": tool.get("tag", ""),
            })
            continue

        # 标准工具
        if exec_info is None:
            continue

        mod, need_device = exec_info
        if mod is None:
            continue

        registry.append({
            "name": name,
            "schema": tool,
            "execute": mod.execute,
            "need_device": need_device,
            "timeout": getattr(mod.execute, "_timeout", 60.0),
            "tag": tool.get("tag", ""),
        })

    return registry