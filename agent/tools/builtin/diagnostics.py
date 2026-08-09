"""系统诊断工具 —— 检测所有功能的实际可用性"""

import os
import shutil

# 移动端连接状态回调，由 server/app.py 注入
_mobile_status_cb = None


def set_mobile_status_callback(cb):
    """设置移动端状态回调，返回 dict: {"connected": bool, "agent_location": str}"""
    global _mobile_status_cb
    _mobile_status_cb = cb


SCHEMA = {
    "type": "function",
    "tag": "系统",
    "function": {
        "name": "run_diagnostics",
        "description": (
            "运行系统诊断，实际检测所有功能的可用性。包括：LLM API 连通性、"
            "硬件设备（麦克风/扬声器/摄像头）、ComfyUI 绘画服务、"
            "音乐播放器（ncm-cli/mpv）、RAG 长期记忆、移动端连接状态等。"
            "在用户询问「你能做什么」或「有哪些功能可用」时，应先调用此工具获取真实状态，"
            "而不是凭记忆回答。"
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}


def _check(name: str, ok: bool, detail: str = "") -> dict:
    """构建单条检测结果"""
    return {"name": name, "status": "ok" if ok else "error", "detail": detail}


def _run_all_checks() -> list:
    """运行所有检测项，返回结果列表"""
    results = []

    # ── 1. LLM API ──
    try:
        from config import API_KEY, API_BASE_URL
        if not API_KEY:
            results.append(_check("LLM API", False, "API_KEY 未配置"))
        else:
            try:
                import requests
                resp = requests.get(f"{API_BASE_URL}/models", timeout=5,
                                    headers={"Authorization": f"Bearer {API_KEY}"})
                if resp.status_code == 200:
                    results.append(_check("LLM API", True, f"已连接 ({API_BASE_URL})"))
                else:
                    results.append(_check("LLM API", False, f"HTTP {resp.status_code}"))
            except Exception as e:
                results.append(_check("LLM API", False, str(e)))
    except ImportError:
        results.append(_check("LLM API", False, "config 模块导入失败"))

    # ── 2. 数据库 ──
    try:
        from agent import database
        sessions = database.get_active_sessions()
        results.append(_check("数据库", True, f"{len(sessions)} 个活跃会话"))
    except Exception as e:
        results.append(_check("数据库", False, str(e)))

    # ── 3. PC 硬件 ──
    # 麦克风
    mic_ok = False
    mic_detail = "未检测到"
    try:
        import sounddevice
        devices = sounddevice.query_devices()
        inputs = [d for d in devices if d["max_input_channels"] > 0]
        if inputs:
            mic_ok = True
            mic_detail = inputs[0]["name"]
    except ImportError:
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info["maxInputChannels"] > 0:
                    mic_ok = True
                    mic_detail = info["name"]
                    break
            p.terminate()
        except ImportError:
            mic_detail = "sounddevice/pyaudio 未安装"
        except Exception as e:
            mic_detail = str(e)
    except Exception as e:
        mic_detail = str(e)
    results.append(_check("麦克风", mic_ok, mic_detail))

    # 扬声器
    spk_ok = False
    spk_detail = "未检测到"
    try:
        import sounddevice
        devices = sounddevice.query_devices()
        outputs = [d for d in devices if d["max_output_channels"] > 0]
        if outputs:
            spk_ok = True
            spk_detail = outputs[0]["name"]
    except ImportError:
        spk_detail = "sounddevice 未安装"
    except Exception as e:
        spk_detail = str(e)
    results.append(_check("扬声器", spk_ok, spk_detail))

    # 摄像头
    cam_ok = False
    cam_detail = "未检测到"
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            cam_ok = True
            cam_detail = f"摄像头 0 ({int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))})"
            cap.release()
        else:
            cam_detail = "摄像头 0 无法打开"
    except ImportError:
        cam_detail = "opencv-python 未安装"
    except Exception as e:
        cam_detail = str(e)
    results.append(_check("摄像头", cam_ok, cam_detail))

    # ── 4. ComfyUI 绘画 ──
    try:
        import requests
        from agent.config import comfyui_url as _cfg_cu
        resp = requests.get(f"{_cfg_cu()}/system_stats", timeout=5)
        if resp.status_code == 200:
            stats = resp.json()
            gpu = stats.get("system", {}).get("gpu", "未知")
            results.append(_check("ComfyUI 绘画", True, f"GPU: {gpu}"))
        else:
            results.append(_check("ComfyUI 绘画", False, f"HTTP {resp.status_code}"))
    except Exception as e:
        results.append(_check("ComfyUI 绘画", False, "未启动 (端口 8188)"))

    # ── 5. 音乐播放 ──
    from agent.config import find_ncm_cli as _cfg_ncm, find_mpv as _cfg_mpv
    ncm_path = shutil.which("ncm-cli")
    if not ncm_path:
        _cfg = _cfg_ncm()
        if _cfg:
            ncm_path = _cfg
    mpv_path = shutil.which("mpv")
    if not mpv_path:
        _cfg = _cfg_mpv()
        if _cfg:
            mpv_path = _cfg

    if ncm_path and mpv_path:
        results.append(_check("音乐播放", True, f"ncm-cli + mpv 已就绪"))
    elif ncm_path:
        results.append(_check("音乐播放", False, "缺少 mpv 播放器，安装：winget install mpv"))
    elif mpv_path:
        results.append(_check("音乐播放", False, "缺少 ncm-cli，安装：npm install -g ncm-cli"))
    else:
        results.append(_check("音乐播放", False, "ncm-cli 和 mpv 均未安装"))

    # ── 6. RAG 长期记忆 ──
    try:
        from agent.memory.long_term import get_memory_count
        count = get_memory_count()
        results.append(_check("RAG 长期记忆", True, f"{count} 条记忆"))
    except Exception as e:
        results.append(_check("RAG 长期记忆", False, str(e)))

    # ── 7. 移动端连接 ──
    if _mobile_status_cb:
        try:
            mobile_info = _mobile_status_cb()
            if mobile_info.get("connected"):
                loc = mobile_info.get("agent_location", "未知")
                results.append(_check("移动端连接", True, f"已连接，Agent 在{loc}端"))
            else:
                results.append(_check("移动端连接", False, "未连接"))
        except Exception as e:
            results.append(_check("移动端连接", False, str(e)))
    else:
        results.append(_check("移动端连接", False, "回调未注册（仅在 server 模式下可用）"))

    return results


def execute(arguments: dict, current_device: str = None) -> str:
    """运行诊断并返回格式化报告"""
    results = _run_all_checks()

    ok_count = sum(1 for r in results if r["status"] == "ok")
    total = len(results)

    lines = [f"系统诊断报告（{ok_count}/{total} 项就绪）", "=" * 30]
    for r in results:
        icon = "✓" if r["status"] == "ok" else "✗"
        detail = f" — {r['detail']}" if r["detail"] else ""
        lines.append(f"  {icon} {r['name']}{detail}")

    # 汇总建议
    errors = [r for r in results if r["status"] == "error"]
    if errors:
        lines.append("")
        lines.append(f"⚠ {len(errors)} 项不可用，请注意：")
        for r in errors:
            if "未安装" in r.get("detail", ""):
                lines.append(f"  · {r['name']}：{r['detail']}")

    return "\n".join(lines)