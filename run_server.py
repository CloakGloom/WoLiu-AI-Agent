"""
电脑端启动脚本
用法: 在项目根目录执行: python run_server.py
      首次运行自动引导到项目专用 venv
（FastAPI 版本，使用 uvicorn 启动）
"""
import sys
import os
from datetime import datetime

# ── 自动引导到项目专用虚拟环境 ──
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_VENV_PYTHON = os.path.join(_PROJECT_ROOT, "Anaconda", "Scripts", "python.exe")
if os.path.abspath(sys.executable) != os.path.abspath(_VENV_PYTHON):
    if os.path.exists(_VENV_PYTHON):
        import subprocess as _sp
        _sp.run([_VENV_PYTHON] + sys.argv)
    else:
        # 尝试从 config.yaml 读取 venv 路径
        try:
            from agent.config import get_python_exe, get_base_python
            _venv = get_python_exe()
            if _venv != "python" and os.path.exists(_venv):
                _sp = __import__("subprocess")
                _sp.run([_venv] + sys.argv)
                sys.exit(0)
        except Exception:
            pass
        print(f"[auto-venv] 虚拟环境未找到: {_VENV_PYTHON}")
        print(f"[auto-venv] 请先创建虚拟环境后重试")
    sys.exit(0)

import logging
import time
import subprocess
import threading

import uvicorn
import asyncio

# ── Windows asyncio 修复 ──
# ProactorEventLoop 在 WebSocket 客户端非优雅断开时，
# transport 回调会抛 ConnectionResetError（WinError 10054）。
# 切换到 SelectorEventLoop 彻底规避此问题（Unix 默认行为）。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 确保项目根目录在 Python 路径中
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# 同时加入当前工作目录（兼容从其他目录运行的情况）
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.insert(0, cwd)

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

# 初始化数据库
from agent import database
database.init_database()
database.update_online_status(True)

from server.app import app
from server.resume_editor_routes import register as register_resume_editor
register_resume_editor(app)
from config import WS_HOST, WS_PORT

logger = logging.getLogger("run_server")
_weixin_bridge_started = False
_ai_services_started = False

# ComfyUI 配置
from agent.utils import is_port_open, get_comfyui_path
COMFYUI_PATH = get_comfyui_path()
COMFYUI_PYTHON = os.path.join(COMFYUI_PATH, "python_embeded", "python.exe")
COMFYUI_PORT = 8188

# JadeAI 配置
JADEAI_DIR = os.path.join(PROJECT_ROOT, "side-projects", "JadeAI-0.4.1")
JADEAI_PORT = 3002
_jadeai_proc = None
_jadeai_started = False

# 统一管理所有子进程，退出时一起关闭
_all_subprocesses = []
_shutting_down = False  # 全局关闭标志，供后台线程检查

# GPU 服务空闲自动回收（释放显存）
_gpu_services = {}  # {name: {"last_used": timestamp, "kill": callable}}
GPU_IDLE_TIMEOUT = 180  # 3 分钟无请求即释放显存


def _track_subprocess(proc):
    _all_subprocesses.append(proc)
    return proc


def _mark_gpu_used(name: str):
    """记录 GPU 服务被使用"""
    if name in _gpu_services:
        _gpu_services[name]["last_used"] = time.time()


def _register_gpu_service(name: str, kill_fn):
    """注册一个 GPU 服务，name 用于标记，kill_fn 用于杀进程"""
    _gpu_services[name] = {"last_used": 0.0, "kill": kill_fn}


def _gpu_cleanup_loop():
    """后台线程：定期检查并杀死空闲 GPU 服务"""
    while not _shutting_down:
        time.sleep(30)
        now = time.time()
        for name, info in list(_gpu_services.items()):
            last_used = info.get("last_used", 0.0) if isinstance(info, dict) else info
            if last_used == 0.0:
                continue  # 从未使用，不杀
            if now - last_used > GPU_IDLE_TIMEOUT:
                import agent.tools.custom.image_generation as ig
                import agent.tools.custom.video_generation_i2v as vi
                if name == "comfyui":
                    if ig._comfyui_proc:
                        print(f"[GPU] ComfyUI 空闲 {GPU_IDLE_TIMEOUT}s，释放显存...", flush=True)
                        try:
                            ig._comfyui_proc.terminate()
                            ig._comfyui_proc.wait(timeout=5)
                        except Exception:
                            try:
                                ig._comfyui_proc.kill()
                            except Exception:
                                pass
                        ig._comfyui_proc = None
                        if isinstance(info, dict):
                            info["last_used"] = 0.0
                        else:
                            _gpu_services[name] = 0.0
                elif name == "chattts":
                    import subprocess
                    try:
                        r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=5)
                        for line in r.stdout.splitlines():
                            if ":8001" in line and "LISTENING" in line:
                                pid = int(line.strip().split()[-1])
                                print(f"[GPU] ChatTTS 空闲 {GPU_IDLE_TIMEOUT}s，释放显存 (PID={pid})...", flush=True)
                                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                                break
                    except Exception:
                        pass
                    if isinstance(info, dict):
                        info["last_used"] = 0.0
                    else:
                        _gpu_services[name] = 0.0


def _cleanup_subprocesses():
    for proc in _all_subprocesses:
        try:
            proc.terminate()
        except Exception:
            pass
    for proc in _all_subprocesses:
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
                proc.wait()
            except Exception:
                pass
    _all_subprocesses.clear()


# Confucius4-TTS 配置
TTS_DIR = os.path.join(PROJECT_ROOT, "side-projects", "Confucius4-TTS")
TTS_PYTHON = os.path.join(TTS_DIR, "python", "python.exe")
TTS_PORT = 8000
_tts_proc = None
_tts_started = False

# 从 config.yaml 读取所有服务路径和端口（不再硬编码）
from agent.config import (
    ollama_exe as _cfg_ollama_exe, ollama_models_dir as _cfg_ollama_models_dir,
    ollama_port as _cfg_ollama_port, ollama_vision_model as _cfg_ollama_vision,
    hf_endpoint as _cfg_hf_endpoint,
)
OLLAMA_EXE = _cfg_ollama_exe()
OLLAMA_MODELS_DIR = _cfg_ollama_models_dir()
OLLAMA_PORT = _cfg_ollama_port()
OLLAMA_VISION_MODEL = _cfg_ollama_vision()
_ollama_proc = None
_ollama_started = False

def _start_ollama():
    """后台启动 Ollama 服务（本地视觉模型，端口 11434）"""
    global _ollama_proc, _ollama_started
    if _ollama_started:
        return
    _ollama_started = True

    if is_port_open(port=OLLAMA_PORT):
        print("[Ollama] 已在运行 (端口 11434)")
        return

    if not os.path.isfile(OLLAMA_EXE):
        print(f"[Ollama] 未找到: {OLLAMA_EXE}，跳过（视觉质检将自动降级跳过）")
        return

    print("[Ollama] 正在启动本地视觉模型服务（qwen3-vl:4b 按需加载）...")
    try:
        env = os.environ.copy()
        env["OLLAMA_MODELS"] = OLLAMA_MODELS_DIR
        env["OLLAMA_HOST"] = f"127.0.0.1:{OLLAMA_PORT}"
        env["OLLAMA_KEEP_ALIVE"] = "2m"  # 空闲2分钟后自动释放 GPU 显存
        env["OLLAMA_NUM_PARALLEL"] = "1"  # 限制并发，避免多模型争抢显存
        _ollama_proc = _track_subprocess(subprocess.Popen(
            [OLLAMA_EXE, "serve"],
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ))
        for _ in range(15):
            time.sleep(1)
            if is_port_open(port=OLLAMA_PORT):
                print("[Ollama] 已就绪 (端口 11434)")
                return
        print("[Ollama] 启动超时（15秒），进程仍在后台，就绪后自动可用")
    except Exception as e:
        print(f"[Ollama] 启动失败: {e}")


def _start_weixin_bridge():
    """后台启动微信桥接服务（仅在已登录时，且只启动一次）"""
    global _weixin_bridge_started
    if _weixin_bridge_started:
        return
    _weixin_bridge_started = True

    try:
        from agent.tools.custom.weixin_bridge.ilink_client import WeChatBot
        from agent.tools.custom.weixin_bridge.bridge import WeChatBridge, create_handler

        bot = WeChatBot.from_config()
        if not bot or not bot.token:
            print("[微信桥接] 未检测到登录信息，跳过。首次使用请运行: python agent/tools/custom/weixin_bridge/run.py")
            return

        bridge = WeChatBridge(bot)
        handler = create_handler(bridge)
        print("[微信桥接] 已启动，正在监听微信消息...")
        bot.listen(handler)
    except Exception as e:
        print(f"[微信桥接] 启动失败: {e}")


def _start_ai_painting_services():
    """后台启动 AI 绘画服务（ComfyUI + 桥接），只启动一次"""
    global _ai_services_started
    if _ai_services_started:
        return
    _ai_services_started = True

    # ── 1. 启动 ComfyUI（如果未运行） ──
    if not is_port_open(port=COMFYUI_PORT):
        if not os.path.exists(COMFYUI_PYTHON):
            print(f"[AI绘画] ComfyUI Python 未找到: {COMFYUI_PYTHON}")
            return

        print("[AI绘画] 正在启动 ComfyUI，首次需加载模型（约 30-60 秒）...")
        try:
            env = os.environ.copy()
            env["PYTHONNOUSERSITE"] = "1"
            git_path = os.path.join(COMFYUI_PATH, "git", "cmd", "git.exe")
            if os.path.exists(git_path):
                env["GIT_PYTHON_GIT_EXECUTABLE"] = git_path

            proc = subprocess.Popen(
                [COMFYUI_PYTHON, "-s", "ComfyUI/main.py", "--port", str(COMFYUI_PORT)],
                cwd=COMFYUI_PATH,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # 保存进程引用，供重启逻辑使用
            try:
                from agent.tools.custom import image_generation as ig
                ig._comfyui_proc = proc
                print("[AI绘画] 进程引用已保存")
            except Exception:
                pass

            # 等待 ComfyUI 就绪（最多 300 秒，大模型加载较慢）
            for i in range(150):
                time.sleep(2)
                if is_port_open(port=COMFYUI_PORT):
                    print("[AI绘画] ComfyUI 已就绪 (端口 8188)")
                    break
            else:
                print("[AI绘画] ComfyUI 启动超时（300秒），进程仍在后台运行，就绪后自动可用")
                return
        except Exception as e:
            print(f"[AI绘画] ComfyUI 启动失败: {e}")
            return
    else:
        print("[AI绘画] ComfyUI 已在运行 (端口 8188)")


def _start_jadeai():
    """后台启动 JadeAI Next.js 开发服务器（端口 3002）"""
    global _jadeai_proc, _jadeai_started
    if _jadeai_started:
        return
    _jadeai_started = True

    if is_port_open(port=JADEAI_PORT):
        print("[JadeAI] 已在运行 (端口 3002)")
        return

    if not os.path.isdir(JADEAI_DIR):
        print("[JadeAI] 目录未找到，跳过")
        return

    # 查找 pnpm
    import shutil
    pnpm = shutil.which("pnpm")
    if not pnpm:
        print("[JadeAI] pnpm 未安装，跳过（需 Node.js 18+ + pnpm）")
        return

    # 检查依赖是否已安装
    if not os.path.isdir(os.path.join(JADEAI_DIR, "node_modules")):
        print("[JadeAI] 依赖未安装，正在运行 pnpm install...")
        try:
            subprocess.run([pnpm, "install", "--frozen-lockfile"], cwd=JADEAI_DIR,
                           check=True, timeout=120)
        except Exception:
            print("[JadeAI] 依赖安装失败，跳过")
            return

    # 检查数据库是否已初始化
    if not os.path.exists(os.path.join(JADEAI_DIR, "data", "jade.db")):
        print("[JadeAI] 数据库未初始化，正在迁移...")
        try:
            subprocess.run([pnpm, "db:generate"], cwd=JADEAI_DIR,
                           check=True, timeout=30)
            subprocess.run([pnpm, "db:migrate"], cwd=JADEAI_DIR,
                           check=True, timeout=30)
        except Exception:
            print("[JadeAI] 数据库迁移失败，请手动执行: cd side-projects/JadeAI-0.4.1 && pnpm db:generate && pnpm db:migrate")
            return

    print("[JadeAI] 正在启动 Next.js 开发服务器...")
    try:
        env = os.environ.copy()
        env["PORT"] = str(JADEAI_PORT)
        _jadeai_proc = _track_subprocess(subprocess.Popen(
            [pnpm, "dev"],
            cwd=JADEAI_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ))
        # 等待 JadeAI 就绪（最多 60 秒）
        for _ in range(60):
            time.sleep(1)
            if is_port_open(port=JADEAI_PORT):
                print("[JadeAI] 已就绪 → http://localhost:8765/jade/")
                return
        print("[JadeAI] 启动超时（60秒），进程仍在后台，就绪后自动可用")
    except Exception as e:
        print(f"[JadeAI] 启动失败: {e}")


def _start_presenton():
    """后台启动 Presenton（Next.js 前端 3000 + FastAPI 后端 18001）"""
    try:
        from agent.tools.custom import presenton_bridge as pb
        if not pb._prepare_env_and_deps():
            print("[Presenton] 依赖准备失败，跳过自启动")
            return
        if not pb._start_nextjs_frontend():
            print("[Presenton] 前端启动失败")
            return
        # 配图模式环境变量先行；ComfyUI 不在此拉起，生成时由工具按需启动
        if pb._start_server(images=True):
            print("[Presenton] 已就绪 → 前端 http://localhost:3000 / 后端 http://localhost:18001")
    except Exception as e:
        print(f"[Presenton] 自启动失败: {e}")


def _load_autostart_config():
    """根据 config/autostart.json 决定启动哪些服务"""
    import json as _json
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "autostart.json")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = _json.load(f)
    except Exception:
        return

    mapping = {
        "comfyui": _start_ai_painting_services,
        "tts": _start_tts,
        "jadeai": _start_jadeai,
        "ollama": _start_ollama,
        "presenton": _start_presenton,
    }
    for name, starter in mapping.items():
        if cfg.get(name, False):
            print(f"[自启动] {name} ...")
            threading.Thread(target=starter, daemon=True, name=f"auto-{name}").start()


def _start_tts():
    """后台启动 Confucius4-TTS FastAPI 服务（端口 8000）"""
    global _tts_proc, _tts_started
    if _tts_started:
        return
    _tts_started = True

    if is_port_open(port=TTS_PORT):
        print("[TTS] Confucius4-TTS 已在运行 (端口 8000)")
        return

    if not os.path.isfile(TTS_PYTHON):
        print(f"[TTS] Python 3.10 未找到: {TTS_PYTHON}")
        return

    req_file = os.path.join(TTS_DIR, "requirements.txt")
    if not os.path.isfile(req_file):
        print("[TTS] requirements.txt 未找到，请先克隆仓库")
        return

    print("[TTS] 正在启动 Confucius4-TTS 服务...")
    try:
        env = os.environ.copy()
        # 使用 HuggingFace 镜像加速模型下载（首次启动需要）
        env["HF_ENDPOINT"] = _cfg_hf_endpoint()
        _tts_proc = _track_subprocess(subprocess.Popen(
            [TTS_PYTHON, "server.py", "--port", str(TTS_PORT)],
            cwd=TTS_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ))
        # 等待 TTS 就绪（模型首次下载可能很慢，给 300 秒）
        for i in range(150):
            time.sleep(2)
            if is_port_open(port=TTS_PORT):
                print(f"[TTS] Confucius4-TTS 已就绪 → http://localhost:8765/tts/")
                return
        print("[TTS] 启动超时（300秒），进程仍在后台，就绪后自动可用")
    except Exception as e:
        print(f"[TTS] 启动失败: {e}")


if __name__ == "__main__":
    # FastAPI 单进程启动：直接打印 banner 并启动后台线程
    print(f"""
╔══════════════════════════════════════════════╗
║      AI Agent 跨设备漫游系统（MVP）            ║
║                                              ║
║  Web 界面:  http://localhost:{WS_PORT}           ║
║  WebSocket: ws://{WS_HOST}:{WS_PORT}/ws         ║
║  HTTP API:  http://{WS_HOST}:{WS_PORT}/api/     ║
║  JadeAI:    http://localhost:{WS_PORT}/jade/       ║
║  TTS:       http://localhost:{WS_PORT}/tts/        ║
║                                              ║
║  默认驻地: 电脑端                             ║
╚══════════════════════════════════════════════╝
    """)

    # 微信桥接始终自动启动
    # 微信桥接（始终启动）
    threading.Thread(target=_start_weixin_bridge, daemon=True, name="weixin-bridge").start()

    # GPU 显存自动回收线程
    threading.Thread(target=_gpu_cleanup_loop, daemon=True, name="gpu-cleanup").start()

    # 根据自启动配置按需启动服务
    _load_autostart_config()

    # Ctrl+C 安全退出
    import signal as _signal
    _shutting_down = False

    def _handle_sigint(sig, frame):
        global _shutting_down
        if _shutting_down:
            print("\n[退出] 强制终止...")
            _cleanup_subprocesses()
            os._exit(1)
        _shutting_down = True
        print("\n[退出] Ctrl+C 收到，正在安全关闭（再次 Ctrl+C 强制终止）...")
        # 停止 uvicorn：向自身发送 KeyboardInterrupt 让 uvicorn.run 正常返回
        _signal.signal(_signal.SIGINT, _signal.SIG_DFL)
        os.kill(os.getpid(), _signal.SIGINT)

    _signal.signal(_signal.SIGINT, _handle_sigint)

    # uvicorn 启动 FastAPI（uvicorn[standard] 自带 WebSocket 支持）
    try:
        uvicorn.run(
            app,
            host=WS_HOST,
            port=WS_PORT,
            log_level="info",
        )
    except KeyboardInterrupt:
        pass
    except Exception as e:
        import traceback
        crash_log = os.path.join(PROJECT_ROOT, "data", "logs", f"crash_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        os.makedirs(os.path.dirname(crash_log), exist_ok=True)
        with open(crash_log, "w", encoding="utf-8") as f:
            f.write(f"FATAL: {e}\n\n")
            traceback.print_exc(file=f)
        print(f"\n[崩溃] 主程序异常退出！详情已写入: {crash_log}", flush=True)
        print(traceback.format_exc(), flush=True)
    finally:
        print("[退出] 正在关闭所有后台服务...")
        _cleanup_subprocesses()
        # 兜底：杀掉 ComfyUI 端口的残留进程
        import agent.tools.custom.image_generation as ig
        if ig._comfyui_proc is not None:
            try:
                ig._comfyui_proc.terminate()
                ig._comfyui_proc.wait(timeout=5)
            except Exception:
                try:
                    ig._comfyui_proc.kill()
                except Exception:
                    pass
        print("[退出] 所有服务已关闭，再见 👋")