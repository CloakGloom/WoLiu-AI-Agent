"""
提醒工具 —— AI 可设置定时提醒，到时间 WebSocket 推送通知

工具:
  set_reminder(when, message)  → 设置提醒
  list_reminders()              → 列出待提醒
  cancel_reminder(id)           → 取消

调度器每 30 秒轮询，到期通过 WS push 到前端。
"""

import sqlite3, os, time, threading, re
from datetime import datetime, timedelta
from agent.tools import emit_progress

_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "data", "reminders.db")
_WS_PUSH = None
_lock = threading.Lock()

SCHEMA = {
    "type": "function", "tag": "提醒",
    "function": {
        "name": "set_reminder",
        "description": "为用户设置定时提醒，到时间系统会主动通知。时间支持'30分钟后'、'明天10点'、'15:30'、'2026-08-15 14:00'。",
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
    c.execute("CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY AUTOINCREMENT, remind_at REAL NOT NULL, message TEXT NOT NULL, created_at REAL DEFAULT(unixepoch()), fired INTEGER DEFAULT 0, cancelled INTEGER DEFAULT 0)")
    return c


def set_push(cb): global _WS_PUSH; _WS_PUSH = cb


# ── 时间解析 ──

def _parse(when: str):
    now = datetime.now(); s = when.strip()
    # N分钟后 / N小时后
    m = re.match(r'(\d+)\s*分钟?后', s)
    if m: return now + timedelta(minutes=int(m.group(1)))
    m = re.match(r'(\d+)\s*小时?后', s)
    if m: return now + timedelta(hours=int(m.group(1)))
    m = re.match(r'(\d+)\s*秒后', s)
    if m: return now + timedelta(seconds=int(m.group(1)))
    # 今天 HH:MM
    m = re.match(r'今天\s*(\d{1,2}):(\d{2})', s)
    if m: return now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    # 明天 HH:MM
    m = re.match(r'明天\s*(\d{1,2}):(\d{2})', s)
    if m: return (now + timedelta(days=1)).replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    # HH:MM
    m = re.match(r'^(\d{1,2}):(\d{2})$', s)
    if m:
        dt = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        if dt <= now: dt += timedelta(days=1)
        return dt
    # 下午/晚上 HH:MM 等
    for t, offset in [('凌晨',0),('上午',0),('中午',12),('下午',12),('傍晚',17),('晚上',20)]:
        m = re.match(rf'{t}\s*(\d{{1,2}}):(\d{{2}})', s)
        if m: return now.replace(hour=offset+int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    # YYYY-MM-DD HH:MM
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})', s)
    if m: return datetime(int(m.group(1)),int(m.group(2)),int(m.group(3)),int(m.group(4)),int(m.group(5)))
    return None


# ── 执行 ──

def execute(args: dict) -> str:
    when, msg = args.get("when", ""), args.get("message", "")
    if not when or not msg:
        return "请提供提醒时间（when）和提醒内容（message）。"
    dt = _parse(when)
    if dt is None:
        return f"无法解析时间 '{when}'。请用 '30分钟后'、'明天10点'、'15:30' 等格式。"
    if dt <= datetime.now():
        return "提醒时间不能早于当前时间，请换个时间。"

    with _lock:
        db = _db()
        ts = dt.timestamp()
        db.execute("INSERT INTO reminders(remind_at,message) VALUES(?,?)", (ts, msg))
        db.commit(); rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.close()

    when_str = dt.strftime("%Y-%m-%d %H:%M")
    emit_progress("set_reminder", 100, "提醒已设置")
    return f"已设置提醒（ID: {rid}）：{when_str} —— {msg}"


# ── 调度器 ──

_timer = None

def start_scheduler():
    """启动后台定时器（由 app.py startup 调用）"""
    global _timer
    def _loop():
        while True:
            time.sleep(30)
            try: _check_and_fire()
            except Exception: pass
    _timer = threading.Thread(target=_loop, daemon=True)
    _timer.start()
    print("[提醒] 调度器已启动", flush=True)

def _check_and_fire():
    now = time.time()
    with _lock:
        db = _db()
        rows = db.execute("SELECT id, remind_at, message FROM reminders WHERE fired=0 AND cancelled=0 AND remind_at<=?", (now+5,)).fetchall()
        for rid, ts, message in rows:
            db.execute("UPDATE reminders SET fired=1 WHERE id=?", (rid,))
            if _WS_PUSH:
                try:
                    from datetime import datetime as dt
                    _WS_PUSH({"type": "reminder_fired", "id": rid, "message": message,
                               "at": dt.fromtimestamp(ts).strftime("%H:%M")})
                except Exception: pass
        db.commit(); db.close()


# ── 查询/取消 ──

def get_pending():
    """获取待提醒列表"""
    db = _db()
    rows = db.execute("SELECT id, remind_at, message FROM reminders WHERE fired=0 AND cancelled=0 ORDER BY remind_at").fetchall()
    db.close()
    return [{"id": r[0], "at": datetime.fromtimestamp(r[1]).strftime("%m-%d %H:%M"), "message": r[2]} for r in rows]

def cancel(rid: int):
    db = _db()
    db.execute("UPDATE reminders SET cancelled=1 WHERE id=?", (rid,))
    db.commit(); db.close()
