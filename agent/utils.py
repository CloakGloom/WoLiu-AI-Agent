"""
共享工具函数 —— 全项目通用，避免重复定义
"""
import os
import socket
from pathlib import Path

from agent.config import load as load_config


def is_port_open(host: str = "127.0.0.1", port: int = 8188) -> bool:
    """检测指定端口是否已开放（可建立 TCP 连接）"""
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def get_project_root() -> Path:
    """获取项目根目录（I:/Agent）的绝对路径"""
    return Path(__file__).resolve().parent.parent


def get_comfyui_path() -> str:
    """获取 ComfyUI 安装路径：环境变量 > config.yaml > 默认搜索"""
    # 1. 环境变量优先
    env = os.environ.get("COMFYUI_PATH")
    if env:
        return env
    # 2. config.yaml
    cfg = load_config()
    install_dir = cfg.get("services", {}).get("comfyui", {}).get("install_dir", "")
    if install_dir:
        p = Path(get_project_root()) / install_dir if not Path(install_dir).is_absolute() else Path(install_dir)
        if p.exists():
            return str(p)
    # 3. 自动搜索
    side = get_project_root() / "side-projects"
    if side.exists():
        for d in side.iterdir():
            if d.is_dir() and "ComfyUI" in d.name:
                return str(d)
    # 4. 回退
    return str(get_project_root() / "side-projects" / "ComfyUI_windows_portable")


def get_python_exe() -> str:
    """返回当前环境下的 Python 可执行文件路径。"""
    from agent.config import get_python_exe as cfg_py
    exe = cfg_py()
    if exe and Path(exe).exists():
        return exe
    import sys
    return sys.executable


def get_torch_lib_path() -> str:
    """返回 PyTorch CUDA DLL 目录路径。"""
    cfg = load_config()
    return cfg.get("python", {}).get("torch_lib", "")


def get_comfyui_url() -> str:
    """从配置获取 ComfyUI 服务地址。"""
    from agent.config import comfyui_url
    return comfyui_url()


def get_data_dir() -> Path:
    """获取统一的用户数据目录。"""
    from agent.config import data_dir
    return data_dir()


def get_output_dir() -> Path:
    """获取统一的文件输出目录。"""
    from agent.config import output_dir
    return output_dir()


def get_static_dir() -> Path:
    """获取 Web 静态文件目录。"""
    return get_project_root() / "server" / "static"


def format_file_size(size_bytes: int) -> str:
    """将字节数格式化为可读的大小字符串（B/KB/MB/GB）"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
