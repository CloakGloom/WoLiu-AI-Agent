"""
SQLite 数据库模块 —— 所有数据持久化操作
数据库文件: data/agent.db
"""

import sqlite3
import json
import os
import time
from datetime import datetime
from contextlib import contextmanager

# 数据库文件路径
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_BASE_DIR, "data", "agent.db")


def _retry_on_lock(func):
    """装饰器：数据库锁冲突时自动重试（最多 3 次，每次间隔 0.5s）"""
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        for attempt in range(3):
            try:
                return func(*args, **kwargs)
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < 2:
                    time.sleep(0.5)
                    continue
                raise
    return wrapper


@contextmanager
def get_db():
    """获取数据库连接（上下文管理器，自动提交/关闭）
    使用 WAL 模式 + 10s 超时，支持多线程并发读取和有限并发写入。
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    except sqlite3.OperationalError as e:
        conn.rollback()
        if "database is locked" in str(e):
            # 并发写入冲突，记录并重新抛出
            import logging
            logging.getLogger("agent.database").warning(f"SQLite 写入冲突: {e}")
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ==================== 初始化 ====================

def init_database():
    """创建所有表并插入初始数据"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    with get_db() as conn:
        conn.executescript("""
            -- 表1：会话管理
            CREATE TABLE IF NOT EXISTS sessions (
                session_id     TEXT PRIMARY KEY,
                device         TEXT NOT NULL,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status         TEXT DEFAULT 'active',
                message_count  INTEGER DEFAULT 0,
                summary        TEXT,
                pinned         INTEGER DEFAULT 0,
                title          TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_device ON sessions(device);
            CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);

            -- 表2：消息历史
            CREATE TABLE IF NOT EXISTS messages (
                message_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id     TEXT NOT NULL,
                role           TEXT NOT NULL,
                content        TEXT NOT NULL,
                device         TEXT,
                tool_calls     TEXT,
                tool_call_id   TEXT,
                process_steps  TEXT,
                token_count    INTEGER,
                branches       TEXT,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);

            -- 表3：用户偏好
            CREATE TABLE IF NOT EXISTS user_preferences (
                pref_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                pref_key     TEXT UNIQUE NOT NULL,
                pref_value   TEXT NOT NULL,
                description  TEXT,
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- 表4：工具注册表
            CREATE TABLE IF NOT EXISTS tools (
                tool_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name      TEXT UNIQUE NOT NULL,
                tool_type      TEXT NOT NULL,
                description    TEXT NOT NULL,
                json_schema    TEXT NOT NULL,
                enabled        INTEGER DEFAULT 1,
                timeout_seconds INTEGER DEFAULT 10,
                module_path    TEXT,
                function_name  TEXT,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_tools_enabled ON tools(enabled);

            -- 表5：行为规则配置
            CREATE TABLE IF NOT EXISTS rules (
                rule_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_name    TEXT UNIQUE NOT NULL,
                rule_category TEXT NOT NULL,
                rule_value   TEXT NOT NULL,
                description  TEXT,
                enabled      INTEGER DEFAULT 1,
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- 表6：当前设备状态（单例表）
            CREATE TABLE IF NOT EXISTS agent_status (
                id               INTEGER PRIMARY KEY CHECK (id = 1),
                current_device   TEXT NOT NULL,
                is_online        INTEGER DEFAULT 1,
                last_online_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_migration_at TIMESTAMP
            );

            -- 表7：迁移历史记录
            CREATE TABLE IF NOT EXISTS migrations (
                migration_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id     TEXT NOT NULL,
                from_device    TEXT NOT NULL,
                to_device      TEXT NOT NULL,
                status         TEXT DEFAULT 'pending',
                message_count  INTEGER,
                started_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at   TIMESTAMP,
                error_message  TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );

            -- 表8：工具调用日志
            CREATE TABLE IF NOT EXISTS tool_call_logs (
                log_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id     TEXT NOT NULL,
                tool_name      TEXT NOT NULL,
                arguments      TEXT,
                result         TEXT,
                status         TEXT,
                duration_ms    INTEGER,
                error_message  TEXT,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );

            -- 表9：人格状态（加密存储）
            CREATE TABLE IF NOT EXISTS personality_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                encrypted_data BLOB NOT NULL,
                version INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- 表10：人格演化事件日志
            CREATE TABLE IF NOT EXISTS personality_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                dimensions_delta TEXT NOT NULL,
                reason TEXT,
                session_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- 表11：人格快照
            CREATE TABLE IF NOT EXISTS personality_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                encrypted_snapshot BLOB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 兼容旧数据库：添加 process_steps 列（忽略已存在的情况）
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN process_steps TEXT")
        except sqlite3.OperationalError:
            pass

        # 兼容旧数据库：添加 pinned / title 列
        for col in [("pinned", "INTEGER DEFAULT 0"), ("title", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {col[0]} {col[1]}")
            except sqlite3.OperationalError:
                pass

        # 兼容旧数据库：添加 branches 列
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN branches TEXT")
        except sqlite3.OperationalError:
            pass

        # 插入初始数据（使用 INSERT OR IGNORE 避免重复）
        conn.executescript("""
            INSERT OR IGNORE INTO user_preferences (pref_key, pref_value, description) VALUES
            ('response_style', 'concise', '回复风格：concise/detailed/friendly'),
            ('default_device', '电脑', '默认启动设备'),
            ('max_history_turns', '20', '上下文保留最大轮数'),
            ('enable_long_term_memory', 'true', '是否启用长期记忆');

            INSERT OR IGNORE INTO agent_status (id, current_device, is_online) VALUES
            (1, '电脑', 1);

            INSERT OR IGNORE INTO rules (rule_name, rule_category, rule_value, description) VALUES
            ('max_iterations', 'behavior', '10', 'Agent 最大循环次数'),
            ('migrate_timeout', 'behavior', '5', '迁移超时时间（秒）'),
            ('default_device', 'behavior', '电脑', '默认启动设备'),
            ('max_history_turns', 'memory', '20', '上下文保留最大轮数'),
            ('enable_rag', 'memory', 'false', '是否启用 RAG 长期记忆'),
            ('log_level', 'security', 'INFO', '日志级别');

            INSERT OR IGNORE INTO tools (tool_name, tool_type, description, json_schema, module_path, function_name) VALUES
            ('get_current_time', 'builtin', '获取当前日期和时间', '{}', 'agent.tools', 'execute_tool'),
            ('get_weather', 'builtin', '查询指定城市的天气信息', '{"city": {"type": "string", "description": "城市名称"}}', 'agent.tools', 'execute_tool'),
            ('calculate', 'builtin', '执行数学计算（支持加减乘除、幂运算等）', '{"expression": {"type": "string", "description": "数学表达式"}}', 'agent.tools', 'execute_tool'),
            ('migrate_agent', 'builtin', '将 Agent 从当前设备迁移到目标设备', '{"target_device": {"type": "string", "enum": ["电脑", "手机"]}}', 'agent.tools', 'execute_tool'),
            ('get_agent_status', 'builtin', '查询 Agent 当前所在的设备及可用硬件能力列表', '{}', 'agent.tools', 'execute_tool'),
            ('switch_hardware', 'hardware', '根据当前所在设备切换硬件调用目标', '{"device": {"type": "string", "enum": ["电脑", "手机"]}}', 'agent.tools', 'execute_tool'),
            ('use_microphone', 'hardware', '调用当前设备的麦克风进行录音', '{"duration": {"type": "integer", "description": "录音时长（秒）"}}', 'agent.tools', 'execute_tool'),
            ('use_speaker', 'hardware', '调用当前设备的扬声器播放文本', '{"text": {"type": "string", "description": "播放文本"}}', 'agent.tools', 'execute_tool');
        """)


# ==================== 会话管理 ====================

def create_session(device: str) -> str:
    """创建新会话，返回 session_id（含 UUID 后缀避免并发冲突）"""
    import uuid
    session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, device) VALUES (?, ?)",
            (session_id, device)
        )
    return session_id


def get_session(session_id: str) -> dict | None:
    """获取会话信息"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def get_active_sessions() -> list:
    """获取所有活跃会话（置顶优先，最近活跃优先）"""
    with get_db() as conn:
        # 显式列出所有列，避免 s.* 与子查询 AS message_count 的列名冲突
        rows = conn.execute(
            """SELECT s.session_id, s.device, s.created_at, s.updated_at,
                      s.last_active_at, s.status, s.summary, s.pinned, s.title,
                      (SELECT COUNT(*) FROM messages m
                       WHERE m.session_id = s.session_id
                       AND m.role IN ('user', 'assistant')
                       AND (m.tool_calls IS NULL OR m.tool_calls = '')
                      ) AS message_count
               FROM sessions s
               WHERE s.status = 'active'
               ORDER BY s.pinned DESC, s.updated_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def delete_session(session_id: str):
    """删除会话及其所有消息"""
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


def pin_session(session_id: str, pinned: bool = True):
    """置顶/取消置顶会话"""
    with get_db() as conn:
        conn.execute(
            "UPDATE sessions SET pinned = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (1 if pinned else 0, session_id)
        )


def rename_session(session_id: str, title: str):
    """重命名会话"""
    with get_db() as conn:
        conn.execute(
            "UPDATE sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (title, session_id)
        )


def duplicate_session(session_id: str, device: str = "电脑") -> str:
    """复制会话（含所有消息），返回新会话 ID"""
    import uuid
    new_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    with get_db() as conn:
        # 获取原会话信息
        row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if not row:
            return None
        row = dict(row)
        # 创建新会话
        conn.execute(
            """INSERT INTO sessions (session_id, device, pinned, title, status)
               VALUES (?, ?, ?, ?, 'active')""",
            (new_id, device, row.get("pinned", 0), (row.get("title") or "") + " (副本)")
        )
        # 复制消息
        conn.execute(
            """INSERT INTO messages (session_id, role, content, device, tool_calls, tool_call_id, process_steps)
               SELECT ?, role, content, device, tool_calls, tool_call_id, process_steps
               FROM messages WHERE session_id = ?""",
            (new_id, session_id)
        )
        # 更新消息计数
        conn.execute(
            "UPDATE sessions SET message_count = (SELECT COUNT(*) FROM messages WHERE session_id = ? AND role IN ('user', 'assistant') AND (tool_calls IS NULL OR tool_calls = '')) WHERE session_id = ?",
            (new_id, new_id)
        )
    return new_id


def delete_message(message_id: int):
    """删除单条消息"""
    with get_db() as conn:
        row = conn.execute("SELECT session_id, role, tool_calls FROM messages WHERE message_id = ?", (message_id,)).fetchone()
        if row:
            conn.execute("DELETE FROM messages WHERE message_id = ?", (message_id,))
            # 只减用户消息和 AI 最终回复的计数
            if row["role"] in ("user", "assistant") and not row["tool_calls"]:
                conn.execute(
                    "UPDATE sessions SET message_count = MAX(0, message_count - 1), updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                    (row["session_id"],)
                )


def get_message_session(message_id: int) -> str:
    """获取消息所属会话 ID"""
    with get_db() as conn:
        row = conn.execute("SELECT session_id FROM messages WHERE message_id = ?", (message_id,)).fetchone()
    return row["session_id"] if row else None


def update_message(message_id: int, content: str):
    """编辑消息内容"""
    with get_db() as conn:
        conn.execute(
            "UPDATE messages SET content = ? WHERE message_id = ?",
            (content, message_id)
        )


def add_branch(user_message_id: int, assistant_content: str, process_steps: str = None, user_content: str = None):
    """给用户消息添加一个 AI 回复分支"""
    with get_db() as conn:
        row = conn.execute("SELECT branches FROM messages WHERE message_id = ?", (user_message_id,)).fetchone()
        branches = json.loads(row["branches"]) if row and row["branches"] else []
        branches.append({"content": assistant_content, "process_steps": process_steps, "user_content": user_content})
        conn.execute(
            "UPDATE messages SET branches = ? WHERE message_id = ?",
            (json.dumps(branches, ensure_ascii=False), user_message_id)
        )
    return len(branches) - 1  # 返回分支索引


def get_message_content(message_id: int) -> str:
    """获取消息内容"""
    with get_db() as conn:
        row = conn.execute("SELECT content FROM messages WHERE message_id = ?", (message_id,)).fetchone()
        return row["content"] if row else ""


def get_branches(user_message_id: int) -> list:
    """获取用户消息的所有分支"""
    with get_db() as conn:
        row = conn.execute("SELECT branches FROM messages WHERE message_id = ?", (user_message_id,)).fetchone()
        if row and row["branches"]:
            return json.loads(row["branches"])
    return []


def get_next_assistant_message(session_id: str, after_message_id: int) -> dict:
    """获取指定消息之后的第一条 assistant 消息"""
    with get_db() as conn:
        row = conn.execute(
            """SELECT message_id, content, process_steps FROM messages
               WHERE session_id = ? AND role = 'assistant' AND message_id > ?
               ORDER BY message_id ASC LIMIT 1""",
            (session_id, after_message_id)
        ).fetchone()
    return dict(row) if row else None


def delete_messages_after(session_id: str, after_message_id: int):
    """删除指定消息之后的所有消息"""
    with get_db() as conn:
        conn.execute(
            "DELETE FROM messages WHERE session_id = ? AND message_id > ?",
            (session_id, after_message_id)
        )
        # 重新统计：只算 user + assistant 正文
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role IN ('user', 'assistant') AND (tool_calls IS NULL OR tool_calls = '')",
            (session_id,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE sessions SET message_count = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (count, session_id)
        )


def archive_session(session_id: str):
    """归档会话"""
    with get_db() as conn:
        conn.execute(
            "UPDATE sessions SET status = 'archived', updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (session_id,)
        )


def update_session_activity(session_id: str):
    """更新会话最后活跃时间"""
    with get_db() as conn:
        conn.execute(
            "UPDATE sessions SET last_active_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (session_id,)
        )


# ==================== 消息管理 ====================

@_retry_on_lock
def save_message(session_id: str, role: str, content: str, device: str = None,
                 tool_calls: str = None, tool_call_id: str = None, token_count: int = None,
                 process_steps: str = None):
    """保存一条消息"""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO messages (session_id, role, content, device, tool_calls, tool_call_id, token_count, process_steps)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, role, content, device, tool_calls, tool_call_id, token_count, process_steps)
        )
        # 只统计用户消息和 AI 最终回复（不含工具调用中间消息）
        if role in ("user", "assistant") and not tool_calls:
            conn.execute(
                "UPDATE sessions SET message_count = message_count + 1, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (session_id,)
            )


def get_recent_messages(session_id: str, limit: int = 20) -> list:
    """获取最近 N 条消息（用于恢复上下文）"""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT message_id, role, content, device, tool_calls, tool_call_id, process_steps, branches, created_at
               FROM messages WHERE session_id = ?
               ORDER BY message_id DESC LIMIT ?""",
            (session_id, limit)
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_all_messages(session_id: str) -> list:
    """获取全部消息（用于迁移打包）"""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT message_id, role, content, device, tool_calls, tool_call_id, process_steps, branches, created_at
               FROM messages WHERE session_id = ?
               ORDER BY message_id ASC""",
            (session_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_messages_as_openai_format(session_id: str, max_turns: int = 3) -> list:
    """获取消息并转换为 OpenAI API 格式（用于 LLM 调用）
    
    一轮 = 1 条用户消息 + 最终 1 条 AI 文本回复。
    中间的工具调用（assistant tool_calls + tool results）不发送给 LLM，
    只保留用户发言和 AI 的最终文字回复。
    """
    raw = get_recent_messages(session_id, limit=max_turns * 10)
    
    if not raw:
        return []
    
    # 只保留 user 消息和 assistant 纯文本回复（无 tool_calls）
    filtered = []
    for m in raw:
        if m["role"] == "user":
            filtered.append(m)
        elif m["role"] == "assistant" and not m.get("tool_calls"):
            filtered.append(m)
    
    # 从末尾向前数 turn（每个 user 消息算一个 turn）
    turn_count = 0
    cut_index = 0
    for i in range(len(filtered) - 1, -1, -1):
        if filtered[i]["role"] == "user":
            turn_count += 1
            if turn_count >= max_turns:
                cut_index = i
                break
    
    kept = filtered[cut_index:]
    
    # 确保第一条是 user
    while kept and kept[0]["role"] != "user":
        kept.pop(0)
    
    # 转换为 OpenAI 格式
    result = []
    for m in kept:
        result.append({"role": m["role"], "content": m["content"]})
    
    return result


def delete_session_messages(session_id: str):
    """删除指定会话的所有消息"""
    with get_db() as conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute(
            "UPDATE sessions SET message_count = 0, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (session_id,)
        )


def import_messages(session_id: str, messages: list, device: str, conn=None):
    """批量导入消息（迁移解包时使用）
    如果传入 conn 参数，则复用已有连接；否则自行打开新连接
    """
    if conn is not None:
        _do_import(conn, session_id, messages, device)
    else:
        with get_db() as conn:
            _do_import(conn, session_id, messages, device)


def _do_import(conn, session_id: str, messages: list, device: str):
    """执行批量导入"""
    for m in messages:
        conn.execute(
            """INSERT INTO messages (session_id, role, content, device, tool_calls, tool_call_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, m.get("role"), m.get("content", ""),
             device, m.get("tool_calls"), m.get("tool_call_id"))
        )


# ==================== 设备状态管理 ====================

def get_current_device() -> str:
    """获取 Agent 当前所在设备"""
    with get_db() as conn:
        row = conn.execute("SELECT current_device FROM agent_status WHERE id = 1").fetchone()
    return row["current_device"] if row else "电脑"


def update_current_device(device: str):
    """更新 Agent 当前设备"""
    with get_db() as conn:
        conn.execute(
            "UPDATE agent_status SET current_device = ?, last_migration_at = CURRENT_TIMESTAMP WHERE id = 1",
            (device,)
        )


def get_agent_status() -> dict:
    """获取 Agent 完整状态"""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM agent_status WHERE id = 1").fetchone()
    return dict(row) if row else {}


def update_online_status(is_online: bool):
    """更新在线状态"""
    with get_db() as conn:
        conn.execute(
            "UPDATE agent_status SET is_online = ?, last_online_at = CURRENT_TIMESTAMP WHERE id = 1",
            (1 if is_online else 0,)
        )


def set_migrating_status():
    """设置迁移中状态（Agent 同时离线）"""
    with get_db() as conn:
        conn.execute(
            "UPDATE agent_status SET current_device = '迁移中', is_online = 0 WHERE id = 1"
        )


# ==================== 工具管理 ====================

def get_enabled_tools() -> list:
    """获取所有启用的工具"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM tools WHERE enabled = 1 ORDER BY tool_id"
        ).fetchall()
    return [dict(r) for r in rows]


def get_tool_config(tool_name: str) -> dict | None:
    """获取单个工具配置"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM tools WHERE tool_name = ?", (tool_name,)
        ).fetchone()
    return dict(row) if row else None


def toggle_tool(tool_name: str, enabled: bool):
    """启用/禁用工具"""
    with get_db() as conn:
        conn.execute(
            "UPDATE tools SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE tool_name = ?",
            (1 if enabled else 0, tool_name)
        )


# ==================== 规则管理 ====================

def get_rule(rule_name: str) -> str | None:
    """获取规则值"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT rule_value FROM rules WHERE rule_name = ? AND enabled = 1", (rule_name,)
        ).fetchone()
    return row["rule_value"] if row else None


def update_rule(rule_name: str, value: str):
    """更新规则值"""
    with get_db() as conn:
        conn.execute(
            "UPDATE rules SET rule_value = ?, updated_at = CURRENT_TIMESTAMP WHERE rule_name = ?",
            (value, rule_name)
        )


def get_all_rules() -> list:
    """获取所有启用的规则"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM rules WHERE enabled = 1 ORDER BY rule_id"
        ).fetchall()
    return [dict(r) for r in rows]


# ==================== 偏好管理 ====================

def get_preference(key: str) -> str | None:
    """获取偏好值"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT pref_value FROM user_preferences WHERE pref_key = ?", (key,)
        ).fetchone()
    return row["pref_value"] if row else None


def update_preference(key: str, value: str):
    """更新偏好值"""
    with get_db() as conn:
        conn.execute(
            "UPDATE user_preferences SET pref_value = ?, updated_at = CURRENT_TIMESTAMP WHERE pref_key = ?",
            (value, key)
        )


def get_all_preferences() -> dict:
    """获取所有偏好设置"""
    with get_db() as conn:
        rows = conn.execute("SELECT pref_key, pref_value FROM user_preferences").fetchall()
    return {r["pref_key"]: r["pref_value"] for r in rows}


# ==================== 迁移管理 ====================

def pack_migration_package(session_id: str, from_device: str) -> dict:
    """打包迁移数据"""
    messages = get_all_messages(session_id)
    return {
        "session_id": session_id,
        "messages": [
            {
                "role": m["role"],
                "content": m["content"],
                "device": m.get("device", from_device),
                "tool_calls": m.get("tool_calls"),
                "tool_call_id": m.get("tool_call_id"),
                "created_at": m.get("created_at"),
            }
            for m in messages
        ],
        "from_device": from_device,
        "timestamp": datetime.now().isoformat(),
    }


def unpack_migration_package(package: dict, target_device: str):
    """解包迁移数据并写入本地数据库"""
    session_id = package.get("session_id")
    messages = package.get("messages", [])

    with get_db() as conn:
        # 创建或更新会话记录
        existing = conn.execute(
            "SELECT session_id FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE sessions SET device = ?, updated_at = CURRENT_TIMESTAMP, status = 'active' WHERE session_id = ?",
                (target_device, session_id)
            )
        else:
            conn.execute(
                "INSERT INTO sessions (session_id, device) VALUES (?, ?)",
                (session_id, target_device)
            )

        # 导入消息（复用同一连接，避免锁冲突）
        import_messages(session_id, messages, target_device, conn=conn)


def log_migration(session_id: str, from_device: str, to_device: str,
                  status: str, message_count: int = None, error: str = None):
    """记录迁移日志"""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO migrations (session_id, from_device, to_device, status, message_count, completed_at, error_message)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)""",
            (session_id, from_device, to_device, status, message_count, error)
        )


def get_migration_history(session_id: str = None) -> list:
    """获取迁移历史"""
    with get_db() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM migrations WHERE session_id = ? ORDER BY started_at DESC",
                (session_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM migrations ORDER BY started_at DESC LIMIT 50"
            ).fetchall()
    return [dict(r) for r in rows]


# ==================== 工具调用日志 ====================

def log_tool_call(session_id: str, tool_name: str, arguments: str,
                  result: str, status: str, duration_ms: int = None,
                  error_message: str = None):
    """记录工具调用日志"""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO tool_call_logs (session_id, tool_name, arguments, result, status, duration_ms, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, tool_name, arguments, result, status, duration_ms, error_message)
        )