"""
环境检测脚本 —— 检查 WoLiu AI Agent 所需的所有依赖

用法: python scripts/check_env.py
      双击 setup.bat 会自动调用
"""
import importlib, os, shutil, subprocess, sys, ctypes, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK, WARN, FAIL, INFO = "✓", "⚠", "✗", "→"


def _color(text: str, code: int) -> str:
    if sys.stdout.isatty() and os.name == "nt":
        try:
            ctypes.windll.kernel32.SetConsoleMode(
                ctypes.windll.kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass
    colors = {32: "\033[32m", 33: "\033[33m", 31: "\033[31m", 36: "\033[36m", 0: "\033[0m"}
    return f"{colors.get(code, '')}{text}{colors[0]}"


def _step(label: str) -> None:
    print(f"\n{_color(label, 36)}")


def _ok(msg: str) -> None:    print(f"  {_color(OK, 32)} {msg}")
def _warn(msg: str) -> None:  print(f"  {_color(WARN, 33)} {msg}")
def _fail(msg: str) -> None:  print(f"  {_color(FAIL, 31)} {msg}")
def _info(msg: str) -> None:  print(f"  {_color(INFO, 36)} {msg}")


def _check_py_module(name: str, label: str) -> bool:
    try:
        importlib.import_module(name)
        _ok(label)
        return True
    except ImportError:
        _fail(f"{label} — 缺失")
        return False


def _check_exe(name: str, label: str) -> bool:
    if shutil.which(name):
        try:
            ver = subprocess.check_output([name, "--version"], stderr=subprocess.STDOUT,
                                          timeout=5, text=True).strip().splitlines()[0]
            _ok(f"{label} — {ver}")
        except Exception:
            _ok(label)
        return True
    else:
        _fail(f"{label} — 未找到")
        return False


def _can_connect(host: str, port: int, label: str) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect((host, port))
        s.close()
        _ok(f"{label} — {host}:{port}")
        return True
    except Exception:
        _info(f"{label} — 未运行")
        return False


def _check_file(path: str, label: str) -> bool:
    full = ROOT / path
    if full.exists():
        _ok(label)
        return True
    _info(f"{label} — 未配置")
    return False


def run():
    print(f"\n{_color('=== WoLiu AI Agent 环境检测 ===', 36)}\n")

    # ── Python ──
    _step("Python 环境")
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 10):
        _ok(f"Python {py_ver}")
    else:
        _fail(f"Python {py_ver} — 需要 3.10+")
    _check_py_module("fastapi", "fastapi")
    _check_py_module("uvicorn", "uvicorn")
    _check_py_module("openai", "openai")
    _check_py_module("chromadb", "chromadb")
    _check_py_module("sqlalchemy", "sqlalchemy")
    _check_py_module("yaml", "pyyaml")
    _check_py_module("aiohttp", "aiohttp")
    _check_py_module("sentence_transformers", "sentence-transformers")
    _check_py_module("edge_tts", "edge-tts (语音合成)")
    _check_py_module("modelscope", "modelscope (魔搭下载)")
    _check_py_module("PIL", "pillow (图像)")
    _check_py_module("requests", "requests")

    # ── 虚拟环境 ──
    _step("虚拟环境")
    if hasattr(sys, "real_prefix") or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix):
        _ok(f"已激活 — {sys.prefix}")
    else:
        _warn("未使用虚拟环境 — 建议: python -m venv .venv")

    # ── Node.js ──
    _step("Node.js & 浏览器自动化")
    has_node = _check_exe("node", "Node.js")
    if has_node:
        _check_exe("npm", "npm")
        agent_bin = ROOT / "node_modules" / ".bin" / "agent-browser.cmd"
        if agent_bin.exists():
            _ok("agent-browser (浏览器自动化)")
        else:
            _warn("agent-browser 未安装 — npm install agent-browser")
    else:
        _info("跳过 Node.js 相关")

    # ── Git ──
    _step("版本控制")
    _check_exe("git", "Git")

    # ── 配置文件 ──
    _step("配置文件")
    _check_file(".env", ".env (密钥)")
    if (ROOT / ".env").exists():
        env_content = (ROOT / ".env").read_text(encoding="utf-8")
        keys_found = sum(1 for line in env_content.splitlines()
                        if "=" in line and not line.strip().startswith("#")
                        and not line.strip().endswith("="))
        _info(f"已配置 {keys_found} 个环境变量")

    # ── 服务端口 ──
    _step("网络端口")
    _can_connect("127.0.0.1", 8000, "HTTP 服务")
    _can_connect("127.0.0.1", 8188, "ComfyUI (AI绘画)")

    # ── 数据 ──
    _step("数据存储")
    data_dir = ROOT / "data"
    if data_dir.exists():
        dbs = list(data_dir.glob("*.db"))
        _ok(f"data/ 目录 — {len(dbs)} 个数据库")
    else:
        _info("data/ 目录 — 首次运行后创建")
    audio_dir = ROOT / "server" / "static" / "generated"
    if audio_dir.exists():
        mp3s = list(audio_dir.rglob("*.mp3"))
        _ok(f"generated/ — {len(mp3s)} 个音频文件")
    else:
        _info("generated/ — 首次合成后创建")

    # ── 模型文件 ──
    _step("AI 绘画模型")
    comfyui = ROOT / "side-projects" / "ComfyUI_windows_portable" / "ComfyUI" / "models"
    if comfyui.exists():
        safetensors = list(comfyui.rglob("*.safetensors"))
        _ok(f"ComfyUI 模型目录 — {len(safetensors)} 个模型文件")
    else:
        _info("ComfyUI 模型目录 — 未安装")

    # ── 汇总 ──
    _step("人格系统")
    try:
        from agent.personality import get_state
        dims = get_state()
        _ok(f"15维人格已加载 — {len(dims)} 维")
    except Exception as e:
        _fail(f"人格系统异常: {e}")

    print(f"\n{_color('=== 检测完成 ===', 36)}\n")


if __name__ == "__main__":
    run()
