"""
Presenton 桥接工具 —— 调用 Presenton API 生成专业 PPT
"""
import os
import sys
import json
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
PRESENTON_APP_DATA = ROOT / "data" / "presenton_data"
PRESENTON_DB_URL = f"sqlite+aiosqlite:///{PRESENTON_APP_DATA.as_posix()}/presenton.db"
PRESENTON_PORT = 18001
PRESENTON_URL = f"http://127.0.0.1:{PRESENTON_PORT}"
PRESENTON_PYTHON = str(PRESENTON_SERVER_DIR / ".venv" / "Scripts" / "python.exe")

_IS_WINDOWS = platform.system() == "Windows"
_server_proc: Optional[subprocess.Popen] = None

logging.getLogger("httpx").setLevel(logging.WARNING)


def _get_llm_config():
    """读取主程序 LLM 配置"""
    try:
        from agent.config import API_BASE_URL, MODEL_NAME, API_KEY
        return {
            "base_url": API_BASE_URL.rstrip("/"),
            "model": MODEL_NAME,
            "api_key": API_KEY,
        }
    except Exception:
        return {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "api_key": ""}


def _get_api_key() -> str:
    for env_key in ("SILICONFLOW_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        val = os.environ.get(env_key, "")
        if val:
            return val
    return _get_llm_config()["api_key"]


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


def _start_server() -> bool:
    """启动 Presenton FastAPI 后端"""
    global _server_proc

    # 检查是否已在运行
    try:
        resp = requests.get(f"{PRESENTON_URL}/docs", timeout=3)
        if resp.status_code == 200:
            print("[Presenton] 服务已在运行", flush=True)
            return True
    except Exception:
        pass

    # 确保 app data 目录存在
    PRESENTON_APP_DATA.mkdir(parents=True, exist_ok=True)

    # 设置环境变量
    env = os.environ.copy()
    env.update({
        "APP_DATA_DIRECTORY": str(PRESENTON_APP_DATA),
        "DATABASE_URL": PRESENTON_DB_URL,
        "DISABLE_AUTH": "true",
        "DISABLE_ANONYMOUS_TRACKING": "true",
        "LLM": "custom",
        "CUSTOM_LLM_URL": _get_llm_config()["base_url"],
        "CUSTOM_LLM_API_KEY": _get_api_key(),
        "CUSTOM_MODEL": _get_llm_config()["model"],
        "IMAGE_PROVIDER": "pexels",
        "PEXELS_API_KEY": os.environ.get("PEXELS_API_KEY", ""),
        "DISABLE_IMAGE_GENERATION": "true",  # 先禁用图片，用纯文字
        "MIGRATE_DATABASE_ON_STARTUP": "true",
        "LOG_LEVEL": "warning",
    })

    print(f"[Presenton] 启动服务 (端口 {PRESENTON_PORT})...", flush=True)
    popen_kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
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


SCHEMA = {
    "type": "function",
    "tag": "PPT",
    "function": {
        "name": "generate_presenton_ppt",
        "description": (
            "使用 Presenton 生成专业 PPT。传入主题描述，自动研究和排版，直接输出 PPTX 文件。"
            "支持指定模板、页数、语言、语调。"
            "可传入预写的 Markdown 内容跳过内容生成阶段。"
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

    # 生成稳定 project_id
    seed = f"{prompt}|{pages}|{template}|{lang}"
    project_id = hashlib.md5(seed.encode()).hexdigest()[:8]
    output_filename = f"presenton_{project_id}.pptx"
    output_path = OUTPUT_DIR / output_filename

    # 如果已生成过，直接返回
    if output_path.exists():
        url = f"/static/papers/{output_filename}"
        return f"PPT 已生成 ({output_path.stat().st_size / 1024:.0f} KB)\n下载：[PAPER:{url}]"

    emit_progress("generate_presenton_ppt", 5, "正在准备 Presenton 服务...")

    # 准备依赖并启动服务
    if not _prepare_env_and_deps():
        return "[Presenton] 环境准备失败，请检查 uv 和 Python 依赖"

    if not _start_server():
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

    try:
        resp = requests.post(
            f"{PRESENTON_URL}/api/v1/ppt/presentation/generate",
            json=payload,
            timeout=600,  # 10 分钟超时
        )

        if resp.status_code != 200:
            error_detail = resp.text[:500]
            print(f"[Presenton] API 错误 ({resp.status_code}): {error_detail}", flush=True)
            return f"[Presenton] 生成失败: HTTP {resp.status_code}\n{error_detail}"

        result = resp.json()
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

    url = f"/static/papers/{output_filename}"
    size_kb = output_path.stat().st_size / 1024

    emit_progress("generate_presenton_ppt", 100, f"完成 ({size_kb:.0f} KB, {elapsed:.0f}s)")

    print(f"[Presenton] 完成! {output_filename} ({size_kb:.0f} KB, {elapsed:.0f}s)", flush=True)

    return (
        f"Presenton 已生成专业 PPT （{size_kb:.0f} KB，耗时 {elapsed:.0f}s），"
        f"下载链接：[PAPER:{url}]"
    )


execute._timeout = 900.0  # 15 分钟超时（含服务启动）
