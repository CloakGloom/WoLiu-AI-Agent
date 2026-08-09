"""AI Agent launcher - double-click to start, Ctrl+C to exit"""
import os
import sys
import subprocess

# PyInstaller root detection
if getattr(sys, 'frozen', False):
    PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PYTHON_EXE = os.path.join(PROJECT_ROOT, "Anaconda", "Scripts", "python.exe")
SERVER_SCRIPT = os.path.join(PROJECT_ROOT, "run_server.py")


def main():
    if not os.path.isfile(PYTHON_EXE):
        print(f"[ERROR] Python not found: {PYTHON_EXE}")
        input("Press Enter to exit...")
        return

    if not os.path.isfile(SERVER_SCRIPT):
        print(f"[ERROR] Server script not found: {SERVER_SCRIPT}")
        input("Press Enter to exit...")
        return

    print("AI Agent starting...")
    print(f"   Python: {PYTHON_EXE}")
    print(f"   Script: {SERVER_SCRIPT}")
    print()

    proc = subprocess.Popen(
        [PYTHON_EXE, SERVER_SCRIPT],
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
