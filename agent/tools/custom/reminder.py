"""
提醒工具 —— AI 设置定时提醒，到期 WS 推送 + edge-tts 语音播报
"""
import sqlite3, os, time, threading, re, subprocess, sys
from datetime import datetime, timedelta
from agent.tools import emit_progress

_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "data", "reminders.db")
_AUDIO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "server", "static", "generated", "reminders")
_WS_PUSH = None
_lock = threading.Lock()

SCHEMA = {
    "type": "function", "tag": "提醒",
    "function": {
        "name": "set_reminder",
        "description": "为用户设置定时提醒，到时间系统会语音播报并弹窗。时间支持'30分钟后'、'明天10点'。",
        "parameters": {
            "type": "object",
            "properties": {
                "when": {"type": "string", "description": "提醒时间。N分钟后/今天HH:MM/明天HH:MM/日期 HH:MM"},
                "message": {"type": "string", "description": "提醒内容"}
            }, "required": ["when", "message"]
        }
    }
}

def _db():
    os.makedirs(os.path.dirname(_DB), exist_ok=True)
    c = sqlite3.connect(_DB); c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY AUTOINCREMENT, remind_at REAL NOT NULL, message TEXT NOT NULL, audio_path TEXT DEFAULT '', created_at REAL DEFAULT(unixepoch()), fired INTEGER DEFAULT 0, cancelled INTEGER DEFAULT 0)")
    # 兼容旧数据库：为已有表补加 audio_path 列
    try:
        c.execute("ALTER TABLE reminders ADD COLUMN audio_path TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    return c

def set_push(cb): global _WS_PUSH; _WS_PUSH = cb

def _parse(when: str):
    now = datetime.now(); s = when.strip()
    m = re.match(r'(\d+)\s*分钟?后', s)
    if m: return now + timedelta(minutes=int(m.group(1)))
    m = re.match(r'(\d+)\s*小时?后', s)
    if m: return now + timedelta(hours=int(m.group(1)))
    m = re.match(r'(\d+)\s*秒后', s)
    if m: return now + timedelta(seconds=int(m.group(1)))
    m = re.match(r'今天\s*(\d{1,2}):(\d{2})', s)
    if m: return now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    m = re.match(r'明天\s*(\d{1,2}):(\d{2})', s)
    if m: return (now + timedelta(days=1)).replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    m = re.match(r'^(\d{1,2}):(\d{2})$', s)
    if m:
        dt = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        if dt <= now: dt += timedelta(days=1)
        return dt
    for t, offset in [('凌晨',0),('上午',0),('中午',12),('下午',12),('傍晚',17),('晚上',20)]:
        m = re.match(rf'{t}\s*(\d{{1,2}}):(\d{{2}})', s)
        if m: return now.replace(hour=offset+int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})', s)
    if m: return datetime(int(m.group(1)),int(m.group(2)),int(m.group(3)),int(m.group(4)),int(m.group(5)))
    return None

def _synthesize(text: str, name: str) -> str:
    os.makedirs(_AUDIO_DIR, exist_ok=True)
    out = os.path.join(_AUDIO_DIR, name)
    if os.path.exists(out):
        return out
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "edge-tts", "-q"], capture_output=True, timeout=60)
        import edge_tts, asyncio
        voice = "zh-CN-XiaoxiaoNeural"
        async def _do():
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(out)
        asyncio.run(_do())
        return out if os.path.exists(out) else ""
    except Exception as e:
        print(f"[提醒] TTS 合成失败: {e}", flush=True)
        return ""

def execute(args: dict) -> str:
    when, msg = args.get("when", ""), args.get("message", "")
    if not when or not msg:
        return "请提供提醒时间（when）和提醒内容（message）。"
    dt = _parse(when)
    if dt is None:
        return f"无法解析时间 '{when}'。请用 '30分钟后'、'明天10点'、'15:30' 等格式。"
    if dt <= datetime.now():
        return "提醒时间不能早于当前时间，请换个时间。"

    audio_name = f"reminder_{int(time.time())}.mp3"
    audio_file = _synthesize(msg, audio_name)
    audio_url = f"/static/generated/reminders/{audio_name}" if audio_file else ""

    with _lock:
        db = _db()
        ts = dt.timestamp()
        db.execute("INSERT INTO reminders(remind_at,message,audio_path) VALUES(?,?,?)", (ts, msg, audio_url))
        db.commit(); rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.close()

    emit_progress("set_reminder", 100, "提醒已设置")
    tts_status = "语音已就绪" if audio_file else "语音合成失败（将纯文字提醒）"
    return f"已设置提醒（ID: {rid}）：{dt.strftime('%H:%M')} —— {msg}（{tts_status}）"

_timer = None

def start_scheduler():
    global _timer
    def _loop():
        while True:
            time.sleep(30)
            try: _check_and_fire()
            except Exception: pass
    _timer = threading.Thread(target=_loop, daemon=True)
    _timer.start()
    print("[提醒] 调度器已启动（含语音合成）", flush=True)

def _check_and_fire():
    now = time.time()
    with _lock:
        db = _db()
        rows = db.execute("SELECT id, remind_at, message, audio_path FROM reminders WHERE fired=0 AND cancelled=0 AND remind_at<=?", (now+5,)).fetchall()
        if rows:
            print(f"[提醒] 发现{len(rows)}条到期提醒", flush=True)
        for rid, ts, message, audio_path in rows:
            db.execute("UPDATE reminders SET fired=1 WHERE id=?", (rid,))
            if _WS_PUSH:
                try:
                    _WS_PUSH({"type": "reminder_fired", "id": rid, "message": message,
                               "at": datetime.fromtimestamp(ts).strftime("%H:%M"),
                               "audio": audio_path or ""})
                    print(f"[提醒] 已推送: {message}", flush=True)
                except Exception as e:
                    print(f"[提醒] 推送失败: {e}", flush=True)
        db.commit(); db.close()

def get_pending():
    db = _db()
    rows = db.execute("SELECT id, remind_at, message, audio_path FROM reminders WHERE fired=0 AND cancelled=0 ORDER BY remind_at").fetchall()
    db.close()
    return [{"id": r[0], "at": datetime.fromtimestamp(r[1]).strftime("%m-%d %H:%M"), "message": r[2], "audio": r[3] or ""} for r in rows]

def cancel(rid: int):
    db = _db()
    db.execute("UPDATE reminders SET cancelled=1 WHERE id=?", (rid,))
    db.commit(); db.close()
