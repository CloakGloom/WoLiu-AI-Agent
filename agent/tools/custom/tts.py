"""
Confucius4-TTS 语音合成工具（真实调用版）
Agent 对话中用户提供参考音频 → 自动调用 TTS API 合成 → 返回可播放音频。
"""

import os
import httpx
from pathlib import Path

SCHEMA = {
    "type": "function",
    "tag": "工具",
    "function": {
        "name": "tts_speak",
        "description": (
            "使用 Confucius4-TTS 进行多语种零样本语音合成。"
            "用户上传或指定参考音频后，直接调用 TTS API 生成克隆音色的语音。"
            "支持 14 种语言：zh/en/ja/ko/de/fr/es/id/it/th/pt/ru/ms/vi。"
            "action=speak 时，需要提供 reference（参考音频绝对路径）和 text（目标文本），"
            "lang 默认 zh。合成结果输出到 converted_files/ 目录。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "speak"],
                    "description": "status: 检查 TTS 服务状态; speak: 合成语音"
                },
                "text": {
                    "type": "string",
                    "description": "要合成的文本（speak 时必填）"
                },
                "lang": {
                    "type": "string",
                    "description": "目标语言代码，默认 zh"
                },
                "reference": {
                    "type": "string",
                    "description": "参考音频文件的绝对路径（speak 时必填）"
                },
            },
            "required": ["action"],
        },
    },
}

import os as _os

from agent.config import tts_url as _cfg_tts_url
TTS_API = _cfg_tts_url()
_OUTPUT_DIR = _os.environ.get(
    "TTS_OUTPUT_DIR",
    str(Path(__file__).resolve().parent.parent.parent.parent / "converted_files")
).replace("\\", "/")
OUTPUT_DIR = _OUTPUT_DIR
LANGUAGES = {
    "zh": "中文", "en": "英文", "ja": "日语", "ko": "韩语",
    "de": "德语", "fr": "法语", "es": "西班牙语", "id": "印尼语",
    "it": "意大利语", "th": "泰语", "pt": "葡萄牙语", "ru": "俄语",
    "ms": "马来语", "vi": "越南语",
}


def execute(args: dict) -> str:
    """执行 TTS 操作。"""
    action = args.get("action", "status")

    if action == "status":
        try:
            r = httpx.get(f"{TTS_API}/health", timeout=5)
            return (
                f"✅ TTS 服务在线 | 采样率 {r.json().get('sample_rate','?')}Hz\n"
                f"支持 {len(LANGUAGES)} 种语言零样本语音合成\n"
                f"API: {TTS_API}/api/tts"
            )
        except Exception:
            return "❌ TTS 服务未启动，请检查服务状态面板"

    if action == "speak":
        text = args.get("text", "").strip()
        lang = args.get("lang", "zh").strip()
        reference = args.get("reference", "").strip()

        if not text:
            return "❌ 请提供要合成的文本"
        if not lang or lang not in LANGUAGES:
            return f"❌ 不支持的语言: {lang}，支持: {', '.join(LANGUAGES)}"
        if not reference:
            return "❌ 请提供参考音频文件路径（你可以在对话中上传音频文件，系统会自动获取路径）"
        if not os.path.isfile(reference):
            return f"❌ 参考音频文件不存在: {reference}"

        # 实际调用 TTS API
        from datetime import datetime
        import time
        try:
            with open(reference, "rb") as f:
                files = {
                    "text": (None, text),
                    "lang": (None, lang),
                    "reference": (os.path.basename(reference), f.read(),
                                  "audio/wav" if reference.endswith(".wav") else "audio/mpeg"),
                }
            r = httpx.post(f"{TTS_API}/api/tts", files=files, timeout=120)
            if r.status_code != 200:
                detail = "未知错误"
                try:
                    detail = r.json().get("detail", r.text[:200])
                except Exception:
                    detail = r.text[:200]
                return f"❌ TTS 合成失败 ({r.status_code}): {detail}"

            # 保存结果
            today = datetime.now().strftime("%Y-%m-%d")
            out_dir = os.path.join(OUTPUT_DIR, today)
            os.makedirs(out_dir, exist_ok=True)
            out_name = f"tts_{datetime.now():%H%M%S}_{lang}.wav"
            out_path = os.path.join(out_dir, out_name)
            with open(out_path, "wb") as fw:
                fw.write(r.content)

            dur = r.headers.get("X-Duration-Sec", "?")
            elapsed = r.headers.get("X-Elapsed-Sec", "?")
            size_kb = len(r.content) / 1024

            return (
                f"✅ 语音合成成功！\n"
                f"文本: {text[:80]}{'...' if len(text) > 80 else ''}\n"
                f"语言: {LANGUAGES.get(lang, lang)} | 时长: {dur}s | 耗时: {elapsed}s | {size_kb:.0f}KB\n"
                f"输出: {out_path}"
            )
        except httpx.ConnectError:
            return "❌ 无法连接 TTS 服务 (localhost:8000)，请检查服务是否启动"
        except httpx.TimeoutException:
            return "❌ TTS 合成超时（>120秒），文本可能过长"
        except Exception as exc:
            return f"❌ TTS 合成异常: {type(exc).__name__}: {exc}"

    return f"❌ 未知操作: {action}"
