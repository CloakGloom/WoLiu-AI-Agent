"""AI Agent launcher - double-click to start, Ctrl+C to exit"""
import os
import sys
import shutil
import subprocess

# PyInstaller root detection
if getattr(sys, 'frozen', False):
    PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SERVER_SCRIPT = os.path.join(PROJECT_ROOT, "run_server.py")


def _find_python():
    """按优先级查找可用的 Python 解释器：
    1. .venv（setup.bat 创建的虚拟环境）
    2. Anaconda（开发者本机环境）
    3. 系统 PATH 中的 python
    """
    candidates = [
        os.path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe"),
        os.path.join(PROJECT_ROOT, "Anaconda", "Scripts", "python.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    # 系统 PATH 中的 python
    for name in ("python", "python3", "py"):
        found = shutil.which(name)
        if found:
            return found
    return None


def main():
    python_exe = _find_python()
    if not python_exe:
        print("[ERROR] 未找到 Python 环境")
        print("请先运行 setup.bat 安装依赖，或手动安装 Python 3.11+")
        print("下载: https://www.python.org/downloads/")
        input("Press Enter to exit...")
        return

    if not os.path.isfile(SERVER_SCRIPT):
        print(f"[ERROR] Server script not found: {SERVER_SCRIPT}")
        input("Press Enter to exit...")
        return

    print("AI Agent starting...")
    print(f"   Python: {python_exe}")
    print(f"   Script: {SERVER_SCRIPT}")
    print()

    proc = subprocess.Popen(
        [python_exe, SERVER_SCRIPT],
        cwd=PROJECT_ROOT,
        env=os.environ.copy(),
    )

    try:
        while proc.poll() is None:
            proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    except Exception as e:
        print(f"[launcher] Server error: {e}")
        proc.terminate()
        proc.wait(timeout=5)

    print("Goodbye.")


if __name__ == "__main__":
    main()
