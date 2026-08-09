"""
Presenton 桥接工具 —— 调用 Presenton API 生成专业 PPT
"""
import os
import re
import sys
import json
import base64
import hashlib
import asyncio
import time
import shutil
import subprocess
import platform
import logging
from pathlib import Path
from typing import Optional

import requests

from agent.tools import emit_progress

ROOT = Path(__file__).resolve().parent.parent.parent.parent
OUTPUT_DIR = ROOT / "server" / "static" / "papers"
os.makedirs(OUTPUT_DIR, exist_ok=True)

PRESENTON_DIR = ROOT / "side-projects" / "presenton-electron-v0.9.3-beta"
PRESENTON_SERVER_DIR = PRESENTON_DIR / "servers" / "fastapi"
PRESENTON_NEXTJS_DIR = PRESENTON_DIR / "servers" / "nextjs"
PRESENTON_APP_DATA = ROOT / "data" / "presenton_data"
PRESENTON_DB_URL = f"sqlite+aiosqlite:///{PRESENTON_APP_DATA.as_posix()}/presenton.db"
PRESENTON_PORT = 18001
PRESENTON_URL = f"http://127.0.0.1:{PRESENTON_PORT}"
NEXTJS_PORT = 3000  # Presenton 前端端口（JadeAI 已迁至 3002，二者端口错开，可同时运行）
NEXTJS_URL = f"http://127.0.0.1:{NEXTJS_PORT}"
PRESENTON_PYTHON = str(PRESENTON_SERVER_DIR / ".venv" / "Scripts" / "python.exe")

_IS_WINDOWS = platform.system() == "Windows"
_server_proc: Optional[subprocess.Popen] = None

# ==================== PPT 配图：ComfyUI 工作流（Z-Image-Turbo 写实风） ====================
# Presenton 的 ComfyUI 接入要求：API 格式工作流 + 一个 _meta.title 为
# "Input Prompt" 的入口节点（提示词沿连线注入），seed 由 Presenton 自动随机化。
_PPT_IMAGE_WORKFLOW = {
    "3": {
        "class_type": "SamplerCustomAdvanced",
        "inputs": {
            "noise": ["15", 0], "guider": ["16", 0], "sampler": ["17", 0],
            "sigmas": ["6", 0], "latent_image": ["13", 0],
        },
    },
    "6": {
        "class_type": "BasicScheduler",
        "inputs": {"model": ["11", 0], "scheduler": "simple", "steps": 8, "denoise": 1},
    },
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["29", 0]}},
    "9": {
        "class_type": "SaveImage",
        "inputs": {"images": ["8", 0], "filename_prefix": "presenton-slide"},
    },
    "11": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["28", 0], "shift": 3}},
    "13": {
        "class_type": "EmptySD3LatentImage",
        "inputs": {"width": 1344, "height": 768, "batch_size": 1},  # 16:9 适配幻灯片
    },
    "15": {"class_type": "RandomNoise", "inputs": {"noise_seed": 0}},
    "16": {"class_type": "BasicGuider", "inputs": {"model": ["11", 0], "conditioning": ["27", 0]}},
    "17": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
    "27": {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["30", 0], "text": "placeholder"},
        "_meta": {"title": "Input Prompt"},  # Presenton 提示词注入入口
    },
    "28": {
        "class_type": "UNETLoader",
        "inputs": {"unet_name": "z_image_turbo_bf16.safetensors", "weight_dtype": "default"},
    },
    "29": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
    "30": {
        "class_type": "CLIPLoader",
        "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "lumina2", "device": "default"},
    },
}


def _ensure_comfyui_for_images() -> bool:
    """确保 ComfyUI 在运行（PPT 配图依赖），失败时回退纯文字模式"""
    try:
        from agent.tools.custom.image_generation import _ensure_comfyui_running
        err = _ensure_comfyui_running()
        if err:
            print(f"[Presenton] ComfyUI 不可用，回退纯文字模式: {err}", flush=True)
            return False
        return True
    except Exception as e:
        print(f"[Presenton] ComfyUI 启动异常，回退纯文字模式: {e}", flush=True)
        return False


def _kill_port(port: int):
    """杀掉占用指定端口的进程（Windows）"""
    if not _IS_WINDOWS:
        return
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=5
        ).stdout
        for line in out.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
                subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=5)
                time.sleep(1)
                break
    except Exception:
        pass


def _find_chrome() -> str:
    """查找系统 Chrome/Edge —— 供 Presenton 导出 PPTX 时的无头渲染使用。
    找不到返回空串（导出脚本会尝试自行下载 Chrome）。"""
    if os.environ.get("PUPPETEER_EXECUTABLE_PATH", "").strip():
        return os.environ["PUPPETEER_EXECUTABLE_PATH"]
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return ""

logging.getLogger("httpx").setLevel(logging.WARNING)


def _get_llm_config():
    """读取 LLM 配置 —— 优先 .env，其次 config.yaml"""
    # 1. 从 .env 读取（最可靠）
    api_key = os.environ.get("SILICONFLOW_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("API_BASE_URL", "").rstrip("/")
    model = os.environ.get("MODEL_NAME", "")

    # 2. .env 没有则从 config.yaml 读取
    if not base_url or not model:
        try:
            from agent.config import llm_base_url, llm_model
            base_url = base_url or llm_base_url().rstrip("/")
            model = model or llm_model()
        except Exception:
            pass

    # 3. 最终兜底
    if not base_url:
        base_url = "https://api.siliconflow.cn/v1"
    if not model:
        model = "Pro/deepseek-ai/DeepSeek-V3"
    if not api_key:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")

    # 4. DeepSeek API: OpenAI SDK 会直接在 base_url 后拼路径，
    #    官方示例 base_url="https://api.deepseek.com" 不带 /v1
    # 5. deepseek-v4-flash 不支持 JSON Schema 结构化输出：保持该模型（低价），
    #    通过 PRESENTON_JSON_MODE_DOWNGRADE 让 Presenton 后端降级为
    #    json_object + 后处理（见 Presenton utils/llm_utils.py 补丁）
    _json_mode_downgrade = False
    if "deepseek-v4-flash" in model:
        _json_mode_downgrade = True
        print("[Presenton] deepseek-v4-flash 不支持 JSON Schema，启用 json_object 降级模式", flush=True)
    if "api.deepseek.com" in base_url:
        base_url = re.sub(r"/v\d+$", "", base_url)

    print(f"[Presenton] LLM 配置: {model} @ {base_url}", flush=True)
    return {
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "json_mode_downgrade": _json_mode_downgrade,
    }


def _prepare_env_and_deps() -> bool:
    """准备 Presenton 运行环境和依赖"""
    # 检查 uv 是否可用
    if shutil.which("uv") is None:
        print("[Presenton] uv 未安装，正在安装...", flush=True)
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "uv"],
                check=True,
                stdout=subprocess.DEVNULL,
            )
        except Exception as e:
            print(f"[Presenton] uv 安装失败: {e}", flush=True)
            return False

    # 同步依赖
    print("[Presenton] 同步 Python 依赖 (uv sync)...", flush=True)
    try:
        subprocess.run(
            ["uv", "sync"],
            cwd=str(PRESENTON_SERVER_DIR),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,
        )
        return True
    except Exception as e:
        print(f"[Presenton] uv sync 失败: {e}", flush=True)
        return False


def _start_nextjs_frontend() -> bool:
    """确保 Next.js 前端（pdf-maker 渲染页）在 3000 端口运行。
    导出 PPTX 时 Chrome 会访问 {NEXT_PUBLIC_URL}/pdf-maker 渲染幻灯片。
    使用 next dev --webpack 模式，始终运行最新源码（中文翻译不会回退英文）。"""

    already_running = False
    try:
        resp = requests.get(f"{NEXTJS_URL}/pdf-maker?id=ping", timeout=5)
        if resp.status_code < 500:
            already_running = True
    except Exception:
        pass

    if already_running:
        # dev 模式下路径无 BUILD_ID 前缀，ping 通了说明已就绪
        try:
            resp = requests.get(f"{NEXTJS_URL}/upload", timeout=10)
            if resp.status_code == 200:
                print("[Presenton] Next.js 前端已在运行", flush=True)
                return True
            print("[Presenton] 前端响应异常，重启 Next.js...", flush=True)
            _kill_port(NEXTJS_PORT)
        except Exception:
            print("[Presenton] Next.js 前端已在运行", flush=True)
            return True

    # 未运行 → 用 next dev --webpack 启动（绕过 Turbopack 的 lightningcss 崩溃，
    # 同时直达最新源码——避免 standalone 旧构建产物回退英文）
    if not (PRESENTON_NEXTJS_DIR / "node_modules" / "next").exists():
        print(f"[Presenton] Next.js 依赖未安装: {PRESENTON_NEXTJS_DIR}", flush=True)
        return False

    env = os.environ.copy()
    # 清除 CodeBuddy 注入的 safe-delete / language shim，否则 next dev 清理
    # 临时目录时触发 SAFE_DELETE_BULK_CONFIRM_REQUIRED 导致进程崩溃
    env.pop("CODEBUDDY_SAFE_DELETE_ENABLED", None)
    env.pop("CODEBUDDY_TOOL_CALL_ID", None)
    env.pop("CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR", None)
    env.pop("CODEBUDDY_SAFE_DELETE_STATE_DIR", None)
    env.pop("CODEBUDDY_SAFE_DELETE_TERMINAL_KEY", None)
    env.pop("NODE_OPTIONS", None)
    env.update({
        "HOSTNAME": "127.0.0.1",
        "PORT": str(NEXTJS_PORT),
        "NEXT_PUBLIC_URL": NEXTJS_URL,
        "NEXT_PUBLIC_FAST_API": PRESENTON_URL,
        "FAST_API_INTERNAL_URL": PRESENTON_URL,
        "DISABLE_AUTH": "true",
        "NEXT_PUBLIC_DISABLE_AUTH": "true",
        "APP_DATA_DIRECTORY": str(PRESENTON_APP_DATA),
        "NODE_ENV": "development",
    })
    node_bin = (PRESENTON_NEXTJS_DIR / "node_modules" / ".bin" / "next.cmd")
    next_dev_cmd = [
        "node", str(PRESENTON_NEXTJS_DIR / "node_modules" / "next" / "dist" / "bin" / "next"),
        "dev", "--webpack", "-p", str(NEXTJS_PORT), "-H", "127.0.0.1",
    ]
    popen_kwargs = {
        "env": env,
        "cwd": str(PRESENTON_NEXTJS_DIR),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if _IS_WINDOWS:
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    print(f"[Presenton] 启动 Next.js dev (webpack, 端口 {NEXTJS_PORT})...", flush=True)
    subprocess.Popen(next_dev_cmd, **popen_kwargs)

    # dev 模式下首次编译 120s，给足时间等待就绪
    max_wait = 60  # 60 × 2s = 120s
    for i in range(max_wait):
        time.sleep(2)
        try:
            resp = requests.get(f"{NEXTJS_URL}/pdf-maker?id=ping", timeout=5)
            if resp.status_code < 500:
                print(f"[Presenton] Next.js dev 就绪 (耗时 ~{(i+1)*2}s)", flush=True)
                return True
        except Exception:
            pass
    print("[Presenton] Next.js dev 启动超时", flush=True)
    return False


def _start_server(images: bool = True) -> bool:
    """启动 Presenton FastAPI 后端。images=True 时接入 ComfyUI 配图"""
    global _server_proc

    # 先杀死可能残留的旧进程（环境变量可能已过期）
    try:
        resp = requests.get(f"{PRESENTON_URL}/docs", timeout=3)
        if resp.status_code == 200:
            print("[Presenton] 服务已在运行", flush=True)
            return True
    except Exception:
        pass

    # 杀掉占用端口的旧进程
    try:
        subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5,
        )
        for line in subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True
        ).stdout.splitlines():
            if f":{PRESENTON_PORT}" in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
                subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=5)
                print(f"[Presenton] 已终止旧进程 PID={pid}", flush=True)
                time.sleep(1)
                break
    except Exception:
        pass

    # 确保 app data 目录存在
    PRESENTON_APP_DATA.mkdir(parents=True, exist_ok=True)

    # 设置环境变量
    llm_cfg = _get_llm_config()
    env = os.environ.copy()
    # 禁用 CodeBuddy safe-delete shim，否则 Presenton 启动时 shutil.rmtree
    # 清理模板静态资源会触发 SystemExit (line 35: _SAFE_DELETE_ENABLED)
    env.pop("CODEBUDDY_SAFE_DELETE_ENABLED", None)
    env["CODEBUDDY_SAFE_DELETE_ENABLED"] = "0"
    env.pop("CODEBUDDY_TOOL_CALL_ID", None)
    env.pop("CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR", None)
    env.pop("CODEBUDDY_SAFE_DELETE_STATE_DIR", None)
    env.pop("CODEBUDDY_SAFE_DELETE_TERMINAL_KEY", None)
    env.update({
        "APP_DATA_DIRECTORY": str(PRESENTON_APP_DATA),
        "DATABASE_URL": PRESENTON_DB_URL,
        "DISABLE_AUTH": "true",
        "DISABLE_ANONYMOUS_TRACKING": "true",
        "LLM": "deepseek",
        "DEEPSEEK_API_KEY": llm_cfg["api_key"],
        "DEEPSEEK_BASE_URL": llm_cfg["base_url"],
        "CUSTOM_LLM_URL": llm_cfg["base_url"],
        "CUSTOM_LLM_API_KEY": llm_cfg["api_key"],
        "CUSTOM_MODEL": llm_cfg["model"],
        "MIGRATE_DATABASE_ON_STARTUP": "true",
        "LOG_LEVEL": "info",
        # v4-flash 等不支持 JSON Schema 的模型：后端降级 json_object + 后处理
        "PRESENTON_JSON_MODE_DOWNGRADE": "1" if llm_cfg.get("json_mode_downgrade") else "0",
        # 导出时 Chrome 访问 {NEXT_PUBLIC_URL}/pdf-maker 渲染幻灯片
        "NEXT_PUBLIC_URL": NEXTJS_URL,
        "NEXT_PUBLIC_FAST_API": PRESENTON_URL,
        "FAST_API_INTERNAL_URL": PRESENTON_URL,
    })

    # 配图：ComfyUI（Z-Image-Turbo 写实风）；不可用时回退纯文字
    if images:
        try:
            from agent.config import comfyui_url as _comfyui_url_cfg
            comfyui_url = (_comfyui_url_cfg() or "").rstrip("/") or "http://127.0.0.1:8188"
        except Exception:
            comfyui_url = "http://127.0.0.1:8188"
        env.update({
            "IMAGE_PROVIDER": "comfyui",
            "COMFYUI_URL": comfyui_url,
            "COMFYUI_WORKFLOW": json.dumps(_PPT_IMAGE_WORKFLOW),
        })
        print(f"[Presenton] 配图模式: ComfyUI @ {comfyui_url}", flush=True)
    else:
        env.update({
            "IMAGE_PROVIDER": "pexels",
            "DISABLE_IMAGE_GENERATION": "true",  # 纯文字模式
        })

    # 导出 PPTX 需要无头 Chrome 渲染；优先用系统已装的 Chrome/Edge，
    # 否则导出脚本会尝试下载 Chrome（国内网络容易失败）
    chrome_path = _find_chrome()
    if chrome_path:
        env["PUPPETEER_EXECUTABLE_PATH"] = chrome_path
        print(f"[Presenton] 使用系统浏览器导出: {chrome_path}", flush=True)

    # 将 Presenton 日志写入文件，以便调试 API 错误
    _presenton_log = ROOT / "data" / "presenton_server.log"

    print(f"[Presenton] 启动服务 (端口 {PRESENTON_PORT})...", flush=True)
    print(f"[Presenton] 日志文件: {_presenton_log}", flush=True)
    _log_fh = open(str(_presenton_log), "w", encoding="utf-8")
    popen_kwargs = {
        "stdout": _log_fh,
        "stderr": _log_fh,
        "env": env,
        "cwd": str(PRESENTON_SERVER_DIR),
    }
    if _IS_WINDOWS:
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        _server_proc = subprocess.Popen(
            [PRESENTON_PYTHON, "server.py", "--port", str(PRESENTON_PORT)],
            **popen_kwargs,
        )
    except Exception as e:
        print(f"[Presenton] 服务启动失败: {e}", flush=True)
        return False

    # 等待服务就绪（最多等 60 秒，数据库迁移需要时间）
    print("[Presenton] 等待服务就绪 (含数据库迁移)...", flush=True)
    for i in range(60):
        time.sleep(2)
        try:
            resp = requests.get(f"{PRESENTON_URL}/docs", timeout=3)
            if resp.status_code == 200:
                print("[Presenton] 服务就绪", flush=True)
                return True
        except Exception:
            pass
        if i % 5 == 0 and i > 0:
            print(f"[Presenton] 等待中... ({i*2}s)", flush=True)

    print("[Presenton] 服务启动超时", flush=True)
    return False


def _stop_server():
    """停止 Presenton 后端"""
    global _server_proc
    if _server_proc and _server_proc.poll() is None:
        try:
            _server_proc.terminate()
            _server_proc.wait(timeout=10)
        except Exception:
            try:
                _server_proc.kill()
            except Exception:
                pass
        _server_proc = None
        print("[Presenton] 服务已停止", flush=True)


# ==================== 视觉质检（Ollama qwen3-vl） ====================

_SLIDE_QC_PROMPT = (
    '你是 PPT 排版质检员，必须严格审查每张幻灯片截图。请逐项检查以下缺陷：'
    '1) 文字重叠（文字与文字、文字与图片/图标互相压盖，标题字母粘连）'
    '2) 标题与正文混叠（标题和正文视觉上混在一起、无清晰纵向间距）'
    '3) 标题太密（每行串字超过 3 个字符、字母间距离异常小）'
    '4) 文字溢出或被截断（超出容器边界）'
    '5) 空白区/未填充（版面预留了多个文本框但实际只填了少数，大片空白）'
    '6) 元素碰撞或错位。'
    '忽略图片内容质量与配色。只要发现一项缺陷即标记为 fail，'
    '不要因为[大致还行]就给 pass。'
    '无问题则回答: {"pass": true}；'
    '有问题则回答: {"pass": false, "issues": ["第N页: 具体问题"]}，'
    '页码必须使用我标注的编号。只回答 JSON，不要任何其他文字。'
)


def _find_node() -> str:
    """查找 node 可执行文件"""
    found = shutil.which("node")
    if found:
        return found
    candidates = []
    try:
        from agent.config import get
        candidates = list(get("external.node_paths", []) or [])
    except Exception:
        pass
    candidates += [
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return ""


def _render_slide_images(presentation_id: str) -> list:
    """用无头 Chrome 打开 pdf-maker 渲染页，逐页截图供视觉质检"""
    node_exe = _find_node()
    chrome_path = _find_chrome()
    render_script = Path(__file__).with_name("presenton_slide_render.cjs")
    if not node_exe or not chrome_path or not render_script.exists():
        return []
    from urllib.parse import quote
    url = f"{NEXTJS_URL}/pdf-maker?id={presentation_id}&fastapiUrl={quote(PRESENTON_URL, safe='')}"
    out_dir = PRESENTON_APP_DATA / "qc_images" / presentation_id
    export_dir = PRESENTON_DIR / "presentation-export"
    env = os.environ.copy()
    env["PUPPETEER_EXECUTABLE_PATH"] = chrome_path
    env["NODE_PATH"] = str(export_dir / "node_modules")
    try:
        proc = subprocess.run(
            [node_exe, str(render_script), url, str(out_dir)],
            cwd=str(export_dir), env=env, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=180,
        )
        lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
        data = json.loads(lines[-1]) if lines else {}
        return data.get("files", [])
    except Exception as e:
        print(f"[Presenton] 幻灯片截图失败，跳过质检: {e}", flush=True)
        return []


def _parse_json_lenient(text: str):
    """宽容解析 LLM 返回的 JSON（剥代码围栏、截取首尾大括号）"""
    if not text:
        return None
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", t, re.DOTALL)
    if m:
        t = m.group(1).strip()
    s, e = t.find("{"), t.rfind("}")
    if s >= 0 and e > s:
        t = t[s:e + 1]
    try:
        return json.loads(t)
    except Exception:
        return None


def _structural_lint(presentation_id: str) -> list:
    """结构层静态检查：不依赖视觉模型，纯统计填充率/标题密度/空框。
    在视觉 QC 之前跑，避免廉价模型放水。
    Returns:
        问题列表，如 ["第2页: 5个框中仅填1个（大片空白）"]
    """
    issues = []
    try:
        resp = requests.get(
            f"{PRESENTON_URL}/api/v1/ppt/presentation/{presentation_id}", timeout=30
        )
        data = resp.json()
    except Exception:
        return issues

    for i, slide in enumerate(data.get("slides", []), start=1):
        content = slide.get("content", {})
        if not isinstance(content, dict):
            continue

        # 统计页面实际有内容的元素
        acc = []
        _collect_strings(content, acc)

        # 统计预定义的容器/框（递归统计 type 为 content-block / text-block 的节点）
        defined_boxes = _count_defined_boxes(content)

        # 规则 1：标题过长（>15 个中文字符几乎必然导致字体过大重叠）
        title = acc[0] if acc else ""
        cn_chars = sum(1 for ch in title if '\u4e00' <= ch <= '\u9fff' or '\u3040' <= ch <= '\u309f')
        total_chars = len(title)
        if total_chars > 30 or cn_chars > 15:
            issues.append(f"第{i}页: 标题过长({total_chars}字符)，字体必然过密/重叠")

        # 规则 2：页面定义了大量容器但极低填充率
        # 定义为有≥3 个内容框定义但实际只填了≤1 条正文（不含标题）
        body_items = len(acc) - 1  # 去掉标题
        if defined_boxes >= 3 and body_items <= 1:
            issues.append(f"第{i}页: {defined_boxes}个框中仅填{body_items}条正文（填充率极低，大片空白）")
        elif defined_boxes >= 2 and body_items == 0:
            issues.append(f"第{i}页: {defined_boxes}个框中无正文，仅标题有内容")

        # 规则 3：内容富但无框定义 = 排版未展开
        if defined_boxes == 0 and body_items >= 3:
            issues.append(f"第{i}页: 正文内容丰富但无布局框，排版坍缩")

    return issues


def _count_defined_boxes(node, depth=0) -> int:
    """递归统计幻灯片内容中定义的布局容器数量（type 为 box/block/column 的节点）"""
    if depth > 6:
        return 0
    count = 0
    if isinstance(node, dict):
        typ = str(node.get("type", ""))
        if typ in ("content-block", "text-block", "content_block", "text_block",
                   "content-block-container", "text-block-container"):
            count += 1
        # 也统计 list-item（常见 5 框结构）和 column
        if typ in ("list-item", "list_item", "column", "col", "card", "panel"):
            count += 1
        # 通用 pattern：含 __layout_id 或 layout_id 的节点 = 布局框
        if any(k.startswith("layout") or k == "frame_id" for k in node):
            count += 1
        for v in node.values():
            count += _count_defined_boxes(v, depth + 1)
    elif isinstance(node, list):
        for item in node:
            count += _count_defined_boxes(item, depth + 1)
    return count


def _vision_review_slides(image_paths: list):
    """调用视觉模型分批审查幻灯片排版。

    Returns:
        (passed, report)：passed 为 None 表示视觉模型不可用（静默跳过）
    """
    try:
        from config import VISION_API_KEY, VISION_BASE_URL, VISION_MODEL
    except Exception:
        return None, ""
    if not VISION_BASE_URL:
        return None, ""

    issues = []
    batch = 1  # 每批 1 页：Ollama 默认上下文 4096，一页高清图约占 2000+ tokens
    for start in range(0, len(image_paths), batch):
        chunk = image_paths[start:start + batch]
        parts = [{"type": "text",
                  "text": f"以下是 PPT 的第 {start + 1} 页：" if len(chunk) == 1
                  else f"以下是 PPT 的第 {start + 1} 到第 {start + len(chunk)} 页："}]
        for p in chunk:
            try:
                with open(p, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
            except Exception:
                continue
            parts.append({"type": "image_url",
                          "image_url": {"url": f"data:image/png;base64,{b64}"}})
        parts.append({"type": "text", "text": _SLIDE_QC_PROMPT})
        req_json = {"model": VISION_MODEL,
                    "messages": [{"role": "user", "content": parts}],
                    "max_tokens": 600, "temperature": 0.1,
                    # Ollama 默认上下文仅 4096，一页高清图即占 2000+ tokens
                    "num_ctx": 8192}
        try:
            resp = requests.post(
                f"{VISION_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {VISION_API_KEY}"},
                json=req_json, timeout=120,
            )
            body = resp.json()
            if "choices" not in body and "num_ctx" in req_json:
                # 云端 API 可能不认 num_ctx，去掉后重试一次
                req_json.pop("num_ctx")
                resp = requests.post(
                    f"{VISION_BASE_URL.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {VISION_API_KEY}"},
                    json=req_json, timeout=120,
                )
                body = resp.json()
            text = body["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[Presenton] 视觉模型调用失败（批次 {start // batch + 1}）: {e}", flush=True)
            return None, ""
        verdict = _parse_json_lenient(text)
        if isinstance(verdict, dict) and verdict.get("pass") is False:
            issues.extend(str(i) for i in verdict.get("issues", []))

    if issues:
        return False, "；".join(issues[:8])
    return True, "排版检查通过"


def _collect_strings(node, acc, depth=0):
    """从 slide content 结构中递归收集文本（跳过备注/图标/图片提示词/URL）"""
    if depth > 8:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            if k.startswith("__") or "icon" in k or "image_prompt" in k:
                continue
            if isinstance(v, str) and v.strip() and len(v) < 300:
                s = v.strip()
                # 跳过 URL（图片/资源地址不能当正文）
                if s.startswith(("http://", "https://", "/app_data/", "/static/", "data:")):
                    continue
                acc.append(s)
            else:
                _collect_strings(v, acc, depth + 1)
    elif isinstance(node, list):
        for item in node:
            _collect_strings(item, acc, depth + 1)


def _slides_markdown_from_api(presentation_id: str) -> list:
    """从后端取回演示文稿，把每页内容展平为 Markdown（供返修重写）"""
    try:
        resp = requests.get(
            f"{PRESENTON_URL}/api/v1/ppt/presentation/{presentation_id}", timeout=30
        )
        data = resp.json()
    except Exception:
        return []
    mds = []
    for slide in data.get("slides", []):
        acc = []
        _collect_strings(slide.get("content", {}), acc)
        if not acc:
            continue
        lines = [f"# {acc[0]}"] + [f"- {s}" for s in acc[1:10]]
        mds.append("\n".join(lines))
    return mds


def _rewrite_failed_slides(slides_md: list, issues_report: str, llm_cfg: dict) -> list:
    """用 LLM 精简问题页内容，返回修正后的全量 Markdown 列表；失败返回 None"""
    failed_idx = sorted({int(n) for n in re.findall(r"第\s*(\d+)\s*页", issues_report)
                         if 1 <= int(n) <= len(slides_md)})
    if not failed_idx:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(base_url=llm_cfg["base_url"], api_key=llm_cfg["api_key"])
    except Exception as e:
        print(f"[Presenton] 返修 LLM 初始化失败: {e}", flush=True)
        return None

    detail = "\n\n".join(
        f"第 {i} 页当前内容：\n{slides_md[i - 1]}" for i in failed_idx
    )
    prompt = (
        "你是 PPT 内容编辑。以下幻灯片存在排版问题，请重写这些页的内容：\n"
        "硬要求：\n"
        "- 标题不超过8个汉字（或16个英文字符），太长必导致字体过大粘连\n"
        "- 正文要点不超过4条，每条不超过10个汉字（或20英文字符）\n"
        "- 如果页面定义了多个布局框，必须为每个框提供内容（不能空框）\n"
        "- 保持原意与语言，用 Markdown（# 标题 + - 要点）。\n"
        '输出 JSON：{"slides": [{"index": 页码, "markdown": "重写后的markdown"}]}\n\n'
        f"问题描述：{issues_report}\n\n{detail}"
    )
    try:
        try:
            resp = client.chat.completions.create(
                model=llm_cfg["model"],
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=2000, temperature=0.3,
            )
        except Exception:
            resp = client.chat.completions.create(
                model=llm_cfg["model"],
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000, temperature=0.3,
            )
        verdict = _parse_json_lenient(resp.choices[0].message.content)
    except Exception as e:
        print(f"[Presenton] 返修 LLM 调用失败: {e}", flush=True)
        return None

    if not isinstance(verdict, dict) or not isinstance(verdict.get("slides"), list):
        return None
    fixed = list(slides_md)
    applied = 0
    for item in verdict["slides"]:
        idx = item.get("index")
        md = (item.get("markdown") or "").strip()
        if isinstance(idx, int) and 1 <= idx <= len(fixed) and md:
            fixed[idx - 1] = md
            applied += 1
    return fixed if applied else None


def _regenerate_with_markdown(payload: dict, slides_md: list):
    """用修正后的 Markdown 重新生成（跳过内容生成阶段，直接排版导出）"""
    p = dict(payload)
    p["slides_markdown"] = slides_md
    p["n_slides"] = len(slides_md)
    p["include_title_slide"] = False  # Markdown 已含标题页
    try:
        resp = requests.post(
            f"{PRESENTON_URL}/api/v1/ppt/presentation/generate",
            json=p, timeout=600,
        )
        if resp.status_code == 200:
            return resp.json()
        print(f"[Presenton] 返修重生成失败 ({resp.status_code}): {resp.text[:200]}", flush=True)
    except Exception as e:
        print(f"[Presenton] 返修重生成异常: {e}", flush=True)
    return None


def _visual_qc_and_fix(payload: dict, presentation_id: str,
                       output_path: Path, llm_cfg: dict):
    """视觉质检 + 自动返修（最多一轮）。

    Returns:
        (final_presentation_id, qc_note)；质检不可用时 qc_note 为空串
    """
    emit_progress("generate_presenton_ppt", 88, "视觉质检中 (qwen3-vl)...")
    # 前置结构检查：不依赖视觉模型，纯统计（填充率/标题密度）
    structural_issues = _structural_lint(presentation_id)
    if structural_issues:
        print(f"[Presenton] 结构层发现问题: {'; '.join(structural_issues)}", flush=True)
    images = _render_slide_images(presentation_id)
    if not images:
        return presentation_id, ""
    passed, report = _vision_review_slides(images)
    if passed is None:
        print("[Presenton] 视觉模型不可用，跳过质检", flush=True)
        # 结构检查出了问题但视觉模型不可用 → 按结构问题处理
        if structural_issues:
            report = "；".join(structural_issues)
            passed = False
        else:
            return presentation_id, ""
    # 合并结构问题：视觉 QC 即使说 pass，结构检查出的硬缺陷也视为未通过
    if structural_issues:
        struct_report = "；".join(structural_issues)
        report = f"{struct_report} | {report}" if report else struct_report
        passed = False
    if passed:
        print(f"[Presenton] 视觉质检通过: {report}", flush=True)
        return presentation_id, "视觉质检通过"

    print(f"[Presenton] 视觉质检发现问题，打回重写: {report}", flush=True)
    emit_progress("generate_presenton_ppt", 90, "发现排版问题，正在重写内容...")
    slides_md = _slides_markdown_from_api(presentation_id)
    fixed_md = _rewrite_failed_slides(slides_md, report, llm_cfg) if slides_md else None
    if not fixed_md:
        return presentation_id, f"视觉质检发现问题（返修失败）: {report}"

    emit_progress("generate_presenton_ppt", 92, "正在重新排版生成...")
    new_result = _regenerate_with_markdown(payload, fixed_md)
    if not new_result:
        return presentation_id, f"视觉质检发现问题（重生成失败）: {report}"
    new_path = new_result.get("path", "")
    full = PRESENTON_APP_DATA / new_path.lstrip("/").replace("app_data/", "", 1)
    if full.exists():
        shutil.copy2(full, output_path)
    new_id = new_result.get("presentation_id", presentation_id)

    # 复检一次
    emit_progress("generate_presenton_ppt", 96, "返修完成，复检中...")
    images2 = _render_slide_images(new_id)
    if images2:
        passed2, report2 = _vision_review_slides(images2)
        if passed2 is False:
            return new_id, f"返修后仍有排版问题: {report2}"
        if passed2:
            return new_id, "质检发现问题已自动返修，复检通过"
    return new_id, "质检发现问题已自动返修"


SCHEMA = {
    "type": "function",
    "tag": "PPT",
    "function": {
        "name": "generate_presenton_ppt",
        "description": (
            "【专用于 PPT / 演示文稿 / Slides / 幻灯片 / Keynote】"
            "使用 Presenton 生成专业 PPTX。传入主题描述，自动研究+排版，直接输出 PPTX 文件。"
            "支持指定模板（general/modern/executive/momentum/dynamic/standard/swift）、页数、语言（zh/en）、语调。"
            "可传入预写 Markdown 跳过内容生成直接排版。"
            "严禁用于论文、文档、报告、PDF 生成——那些场景不属于本工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "PPT 主题描述，包括内容要点、风格要求等"
                },
                "pages": {
                    "type": "string",
                    "description": "期望的幻灯片页数，如 '8'、'10'（可选，默认 8）"
                },
                "template": {
                    "type": "string",
                    "enum": ["general", "modern", "executive", "momentum", "dynamic", "standard", "swift"],
                    "description": "模板名称（可选，默认 general）"
                },
                "tone": {
                    "type": "string",
                    "enum": ["default", "professional", "casual", "educational", "sales_pitch", "funny"],
                    "description": "语调风格（可选，默认 professional）"
                },
                "lang": {
                    "type": "string",
                    "enum": ["zh", "en"],
                    "description": "输出语言（可选，默认 zh）"
                },
                "markdown_content": {
                    "type": "string",
                    "description": "预写的幻灯片 Markdown 内容。提供此参数将跳过内容生成，直接排版导出。每页用 '---' 分隔。（可选）"
                },
            },
            "required": ["prompt"],
        },
    },
}


def execute(arguments: dict) -> str:
    """工具统一入口"""
    prompt = arguments.get("prompt", "").strip()
    pages = int(arguments.get("pages", "8"))
    template = arguments.get("template", "general")
    tone = arguments.get("tone", "professional")
    lang = arguments.get("lang", "zh")
    markdown_content = arguments.get("markdown_content", "").strip()

    if not prompt:
        return "[Presenton] 请提供 PPT 主题描述"

    # 生成稳定 project_id（含配图模式，避免文字版/配图版缓存互串）
    seed = f"{prompt}|{pages}|{template}|{lang}|img"
    project_id = hashlib.md5(seed.encode()).hexdigest()[:8]
    output_filename = f"presenton_{project_id}.pptx"
    output_path = OUTPUT_DIR / output_filename

    # 如果已生成过，直接返回
    if output_path.exists():
        url = f"/static/papers/{output_filename}"
        return f"PPT 已生成 ({output_path.stat().st_size / 1024:.0f} KB)\n下载：[PAPER:{url}]"

    emit_progress("generate_presenton_ppt", 5, "正在准备 Presenton 服务...")

    # 准备依赖并启动服务（前端 + 后端 + ComfyUI 配图）
    if not _prepare_env_and_deps():
        return "[Presenton] 环境准备失败，请检查 uv 和 Python 依赖"

    images = _ensure_comfyui_for_images()
    if not images:
        emit_progress("generate_presenton_ppt", 8, "ComfyUI 不可用，将生成纯文字 PPT")

    if not _start_nextjs_frontend():
        return "[Presenton] Next.js 前端启动失败，无法导出 PPT"

    if not _start_server(images=images):
        return "[Presenton] Presenton 服务启动失败"

    emit_progress("generate_presenton_ppt", 15, "正在生成 PPT 内容...")

    # 构建 API 请求
    language_map = {"zh": "Chinese", "en": "English"}
    payload = {
        "content": prompt,
        "n_slides": pages,
        "template": template,
        "tone": tone,
        "language": language_map.get(lang, "Chinese"),
        "export_as": "pptx",
        "include_title_slide": True,
    }

    # 如果有预写 Markdown，按 --- 拆分为 slides_markdown
    if markdown_content:
        slides = [s.strip() for s in markdown_content.split("---") if s.strip()]
        if slides:
            payload["slides_markdown"] = slides
            payload["n_slides"] = len(slides)
            print(f"[Presenton] 使用预写 Markdown ({len(slides)} 页)", flush=True)
            emit_progress("generate_presenton_ppt", 20, f"使用预写内容，共 {len(slides)} 页")

    print(f"[Presenton] 调用 API 生成 PPT...", flush=True)
    print(f"[Presenton] 主题: {prompt[:80]}", flush=True)
    print(f"[Presenton] 页数: {pages}, 模板: {template}, 语言: {language_map.get(lang)}", flush=True)

    start_time = time.time()
    emit_progress("generate_presenton_ppt", 25, "Presenton 正在生成幻灯片...")

    # 瞬时错误自动重试（最多 3 次）：
    #  - "slides not found"：导出时后端重启竞态，渲染页拉不到幻灯片
    #  - "outlines"：LLM 偶发返回坏格式 JSON
    #  - "did not match schema"：json_object 降级模式下模型未遵循 schema（快速失败）
    #  - "Presentation generation failed"：生成链路偶发失败
    # 说明：使用 deepseek-v4-flash 等不支持 JSON Schema 的模型时，后端只能降级为
    # json_object 模式，模型偶发产出不合规 JSON 会 400。多试几次通常能过；若要从
    # 根本上消除，请改用支持 response_format=json_schema 的模型（如 gpt-4o-mini），
    # 此时 PRESENTON_JSON_MODE_DOWNGRADE 自动关闭，由 API 服务端强制 schema。
    _RETRYABLE_MARKERS = (
        "slides not found",
        "Failed to generate presentation outlines",
        "did not match schema",
        "Presentation generation failed",
    )
    result = None
    max_attempts = 3
    try:
        for attempt in range(1, max_attempts + 1):
            resp = requests.post(
                f"{PRESENTON_URL}/api/v1/ppt/presentation/generate",
                json=payload,
                timeout=600,  # 10 分钟超时
            )

            if resp.status_code != 200:
                error_detail = resp.text[:500]
                print(f"[Presenton] API 错误 ({resp.status_code}): {error_detail}", flush=True)
                if attempt < max_attempts and any(m in error_detail for m in _RETRYABLE_MARKERS):
                    wait = 5 * attempt
                    print(f"[Presenton] 瞬时错误，{wait} 秒后自动重试 ({attempt}/{max_attempts - 1})...", flush=True)
                    emit_progress("generate_presenton_ppt", 25, f"遇到瞬时错误，正在重试 ({attempt}/{max_attempts - 1})...")
                    time.sleep(wait)
                    continue
                # 尝试读取 Presenton 服务端日志（含 DeepSeek 真实错误）
                _pr_log = ROOT / "data" / "presenton_server.log"
                if _pr_log.exists():
                    try:
                        tail = _pr_log.read_text(encoding="utf-8")[-3000:]
                        print(f"[Presenton] 服务端日志 (尾部):\n{tail}", flush=True)
                    except Exception:
                        pass
                return f"[Presenton] 生成失败: HTTP {resp.status_code}\n{error_detail}"

            result = resp.json()
            break
    except requests.Timeout:
        return "[Presenton] 生成超时（10 分钟），请减少页数或简化主题重试"
    except Exception as e:
        return f"[Presenton] API 请求失败: {e}"

    elapsed = time.time() - start_time
    emit_progress("generate_presenton_ppt", 85, "正在下载 PPTX 文件...")

    # 获取 PPTX 文件路径
    pptx_server_path = result.get("path", "")
    if not pptx_server_path:
        return f"[Presenton] API 返回异常，缺少文件路径: {json.dumps(result, ensure_ascii=False)}"

    # 从 Presenton 的 app_data 目录复制到输出目录
    # path 格式: /app_data/exports/xxx.pptx 或 /app_data/{uuid}/xxx.pptx
    pptx_full_path = PRESENTON_APP_DATA / pptx_server_path.lstrip("/").replace("app_data/", "", 1)
    if not pptx_full_path.exists():
        return f"[Presenton] 生成的 PPTX 文件不存在: {pptx_full_path}"

    shutil.copy2(pptx_full_path, output_path)

    # ── 视觉质检 + 自动返修（Ollama qwen3-vl，不可用时静默跳过） ──
    qc_note = ""
    try:
        presentation_id = result.get("presentation_id", "")
        if presentation_id:
            _, qc_note = _visual_qc_and_fix(payload, presentation_id, output_path, _get_llm_config())
    except Exception as e:
        print(f"[Presenton] 视觉质检异常，跳过: {e}", flush=True)

    url = f"/static/papers/{output_filename}"
    size_kb = output_path.stat().st_size / 1024
    elapsed = time.time() - start_time

    emit_progress("generate_presenton_ppt", 100, f"完成 ({size_kb:.0f} KB, {elapsed:.0f}s)")

    print(f"[Presenton] 完成! {output_filename} ({size_kb:.0f} KB, {elapsed:.0f}s)" +
          (f"，质检: {qc_note}" if qc_note else ""), flush=True)

    return (
        f"Presenton 已生成专业 PPT （{size_kb:.0f} KB，耗时 {elapsed:.0f}s）"
        + (f"，视觉质检：{qc_note}" if qc_note else "")
        + f"，下载链接：[PAPER:{url}]"
    )


execute._timeout = 1800.0  # 30 分钟超时（配图 + 视觉质检返修链路更长）
