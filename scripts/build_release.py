"""
生成 GitHub Release 便携版 zip 打包脚本（独立版，可放任意盘运行）
打包内容：项目源码 + 启动器 exe（排除大目录）

用法: python build_release.py [项目根目录] [输出目录]
"""
import os
import sys
import zipfile
import fnmatch

PROJECT_ROOT = sys.argv[1] if len(sys.argv) > 1 else r"i:\Agent"
DIST = sys.argv[2] if len(sys.argv) > 2 else r"G:\releases"

INCLUDE_FILES = [
    "run_server.py", "run_client.py", "launcher.py", "requirements.txt",
    "config.yaml", "setup.bat", "README.md", "LICENSE.md", "alembic.ini",
    "docker-compose.yml", "AI_Agent.spec", ".env.example",
]
INCLUDE_DIRS = [
    "agent", "server", "client", "config", "scripts", "docs",
    "migrations", "tests", "tools",
]
EXCLUDE_PATTERNS = [
    "__pycache__", "*.pyc", "*.pyo", ".git", "node_modules", "*.log",
    "generated", "*.db", "*.sqlite3", "chroma",
]
EXCLUDE_DIRS = {
    "tools/PPTAgent", "tools/llama.cpp", "tools/kimi_ppt",
}
INCLUDE_EXE = True
EXE_NAME = "AI_Agent.exe"


def _should_exclude(name):
    return any(fnmatch.fnmatch(name, p) for p in EXCLUDE_PATTERNS)


def _add_dir(zf, src_dir, arc_dir):
    for root, dirs, files in os.walk(src_dir):
        rel_root = os.path.relpath(root, PROJECT_ROOT).replace("\\", "/")
        dirs[:] = [d for d in dirs
                   if not _should_exclude(d)
                   and os.path.join(rel_root, d).replace("\\", "/") not in EXCLUDE_DIRS]
        for f in files:
            if _should_exclude(f):
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, src_dir)
            arcname = os.path.join(arc_dir, rel).replace("\\", "/")
            try:
                zf.write(full, arcname)
            except OSError as e:
                print(f"  [warn] 跳过: {rel} ({e})")


def main():
    os.makedirs(DIST, exist_ok=True)
    zip_path = os.path.join(DIST, "WoLiu-AI-Agent-portable-v2.0.0.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)

    print(f"项目根: {PROJECT_ROOT}")
    print(f"输出:   {zip_path}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in INCLUDE_FILES:
            full = os.path.join(PROJECT_ROOT, f)
            if os.path.isfile(full):
                zf.write(full, f)
                print(f"  [file] {f}")
        for d in INCLUDE_DIRS:
            full = os.path.join(PROJECT_ROOT, d)
            if os.path.isdir(full):
                _add_dir(zf, full, d)
                print(f"  [dir ] {d}/")
        if INCLUDE_EXE:
            exe_full = os.path.join(PROJECT_ROOT, EXE_NAME)
            if os.path.isfile(exe_full):
                zf.write(exe_full, EXE_NAME)
                print(f"  [exe ] {EXE_NAME}")

    size_mb = os.path.getsize(zip_path) / 1048576
    print(f"\n完成: {zip_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
