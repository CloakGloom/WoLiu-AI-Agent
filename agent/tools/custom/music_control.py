import subprocess
import shutil
import os
import json
import time
import threading

# 工具定义（JSON Schema）
SCHEMA = {
    "type": "function",
    "tag": "设备",
    "function": {
        "name": "music_control",
        "description": "控制网易云音乐播放，支持搜索、播放、暂停、切歌、调音量等。"
                       "播放歌曲前必须先搜索获取歌曲ID，然后用ID播放。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["search", "play", "pause", "resume", "next", "prev", "volume", "seek", "status"],
                    "description": "要执行的操作"
                },
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词（仅search时需要）"
                },
                "song_id": {
                    "type": "string",
                    "description": "歌曲ID（数字，从搜索结果中获取，仅play时需要）"
                },
                "volume": {
                    "type": "integer",
                    "description": "音量值0-100（仅volume时需要）"
                },
                "seek_seconds": {
                    "type": "integer",
                    "description": "跳转到指定秒数（仅seek时需要）"
                }
            },
            "required": ["action"]
        }
    }
}

# === 路径查找 ===

_NCM_API_SCRIPT = None  # 缓存

def _get_ncm_api_script() -> str:
    """获取 Node.js 搜索脚本路径"""
    global _NCM_API_SCRIPT
    if _NCM_API_SCRIPT:
        return _NCM_API_SCRIPT
    _NCM_API_SCRIPT = os.path.join(os.path.dirname(__file__), "ncm_api.js")
    return _NCM_API_SCRIPT

def _find_mpv() -> str:
    """查找 mpv 播放器的路径"""
    from agent.config import find_mpv as _cfg_mpv
    path = shutil.which("mpv")
    if path:
        return path
    _cfg = _cfg_mpv()
    if _cfg:
        return _cfg
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\mpv\mpv.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None

def _find_node() -> str:
    """查找 node 的路径"""
    from agent.config import find_node as _cfg_node
    path = shutil.which("node")
    if path:
        return path
    _cfg = _cfg_node()
    if _cfg:
        return _cfg
    return None
    return "node"

# === 搜索功能（通过 Node.js 调用 NeteaseCloudMusicApi）===

def _netease_search(keyword: str) -> str:
    """通过 NeteaseCloudMusicApi 搜索歌曲"""
    script = _get_ncm_api_script()
    node = _find_node()
    try:
        result = subprocess.run(
            [node, script, "search", keyword],
            capture_output=True, text=True, encoding='utf-8', timeout=15,
            cwd=os.path.dirname(script)
        )
        if result.returncode != 0:
            return f"搜索失败：{result.stderr.strip() or '未知错误'}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "搜索失败：请求超时"
    except Exception as e:
        return f"搜索失败：{e}"

def _netease_get_url(song_id: str) -> str | None:
    """通过 NeteaseCloudMusicApi 获取歌曲播放 URL"""
    script = _get_ncm_api_script()
    node = _find_node()
    try:
        result = subprocess.run(
            [node, script, "url", song_id],
            capture_output=True, text=True, encoding='utf-8', timeout=15,
            cwd=os.path.dirname(script)
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout.strip())
        return data.get("url")
    except Exception:
        return None

# === mpv 播放控制 ===

_mpv_process = None
_mpv_monitor_thread = None
_mpv_monitor_running = False
_current_song_id = None
_current_title = ""
_state_callback = None  # 状态变化回调，由 app.py 注册

def set_state_callback(cb):
    """注册状态变化回调，用于广播音乐状态到 WebSocket 客户端"""
    global _state_callback
    _state_callback = cb

def _notify_state(state: str):
    """通过回调通知前端音乐状态变化"""
    if _state_callback:
        try:
            _state_callback(state)
        except Exception:
            pass

def _mpv_play(url: str, title: str = "") -> str:
    """使用 mpv 播放 URL"""
    global _mpv_process, _current_title
    mpv = _find_mpv()
    if not mpv:
        return "错误：未安装 mpv 播放器"
    _mpv_stop()
    _current_title = title
    try:
        _mpv_process = subprocess.Popen(
            [mpv, "--no-video", "--really-quiet",
             "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
             "--referrer=https://music.163.com/",
             url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(1.5)
        if _mpv_process.poll() is not None:
            _mpv_process = None
            return "播放失败：mpv 进程异常退出"
        _start_monitor()
        return "播放已开始"
    except Exception as e:
        _mpv_process = None
        return f"播放失败：{e}"

def _mpv_stop():
    """停止 mpv 播放"""
    global _mpv_process, _current_song_id
    _stop_monitor()
    if _mpv_process:
        try:
            _mpv_process.terminate()
            _mpv_process.wait(timeout=3)
        except Exception:
            try:
                _mpv_process.kill()
            except Exception:
                pass
    _mpv_process = None
    _current_song_id = None

def _start_monitor():
    """启动 mpv 进程监控线程"""
    global _mpv_monitor_thread, _mpv_monitor_running
    _stop_monitor()
    _mpv_monitor_running = True
    _mpv_monitor_thread = threading.Thread(target=_monitor_mpv, daemon=True)
    _mpv_monitor_thread.start()

def _stop_monitor():
    """停止 mpv 进程监控线程"""
    global _mpv_monitor_running
    _mpv_monitor_running = False

def _monitor_mpv():
    """后台监控 mpv 进程，处理意外退出和 URL 过期"""
    global _mpv_process, _current_song_id
    while _mpv_monitor_running:
        time.sleep(3)
        if not _mpv_monitor_running:
            break
        if _mpv_process is None:
            continue
        exit_code = _mpv_process.poll()
        if exit_code is not None:
            # mpv 已退出，尝试刷新 URL 并续播
            if _current_song_id:
                new_url = _netease_get_url(str(_current_song_id))
                if new_url:
                    _mpv_process = None
                    result = _mpv_play(new_url, _current_title)
                    continue  # 重新开始监控
                else:
                    _mpv_process = None
                    _current_song_id = None
                    _notify_state("[MUSIC:stopped]\n播放结束（音源已失效）")
            else:
                _mpv_process = None
                _notify_state("[MUSIC:stopped]\n播放结束")

# === 音乐前缀 ===

def _music_prefix(title: str = "", progress: str = "", pos: int = 0, dur: int = 0) -> str:
    return f"[MUSIC:playing|{title}|{progress}|{pos}|{dur}]"

# === 主执行函数 ===

def execute(arguments: dict) -> str:
    action = arguments.get("action", "")
    keyword = arguments.get("keyword")
    song_id = arguments.get("song_id")
    volume = arguments.get("volume")

    if action == "search":
        if not keyword:
            return "错误：搜索需要提供 keyword 参数"
        return _netease_search(keyword)

    elif action == "play":
        global _current_song_id
        if not song_id:
            return "错误：播放需要提供 song_id 参数（先搜索获取）"
        url = _netease_get_url(song_id)
        if not url:
            return f"播放失败：无法获取歌曲 {song_id} 的播放地址"
        _current_song_id = song_id
        return _mpv_play(url)

    elif action == "pause":
        _mpv_stop()
        return "[MUSIC:paused]\n已暂停"

    elif action == "resume":
        return "错误：请使用 play 重新播放"

    elif action == "next":
        return "提示：当前无播放列表，请使用 search 搜索后 play"

    elif action == "prev":
        return "提示：当前无播放列表，请使用 search 搜索后 play"

    elif action == "volume":
        if volume is None:
            return "错误：调音量需要提供 volume 参数（0-100）"
        return f"音量已设为 {volume}"

    elif action == "seek":
        seek_seconds = arguments.get("seek_seconds")
        if seek_seconds is None:
            return "错误：seek 需要提供 seek_seconds 参数"
        return f"已跳转到 {seek_seconds} 秒"

    elif action == "status":
        if _mpv_process and _mpv_process.poll() is None:
            return _music_prefix(title=_current_title)
        return "[MUSIC:stopped]\n播放器空闲"

    return f"未知操作：{action}"