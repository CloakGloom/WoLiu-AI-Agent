"""
人格状态管理 —— 加密存储 + HMAC 签名防篡改

使用 Python 标准库实现：
- PBKDF2-HMAC-SHA256 密钥派生
- XOR 加密
- HMAC-SHA256 完整性校验
"""

import json
import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta

from agent.personality.dimensions import (
    DIMENSION_KEYS,
    DEFAULT_PERSONALITY,
    INACTIVITY_REGRESSION_RATE,
)

# ==================== 路径配置 ====================

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_KEY_PATH = os.path.join(_BASE_DIR, "data", ".personality_key")
_DB_PATH = os.path.join(_BASE_DIR, "data", "agent.db")

# ==================== 密钥管理 ====================

def _derive_machine_fingerprint() -> bytes:
    """生成机器指纹（用于密钥派生）"""
    import platform
    import socket
    parts = [
        platform.node() or "unknown",
        socket.gethostname() or "unknown",
        platform.processor() or "unknown",
        os.path.expanduser("~") or "unknown",
    ]
    return hashlib.sha256("|".join(parts).encode()).digest()


def _get_or_create_key() -> bytes:
    """获取或创建加密密钥"""
    if os.path.exists(_KEY_PATH):
        with open(_KEY_PATH, "rb") as f:
            return f.read()
    os.makedirs(os.path.dirname(_KEY_PATH), exist_ok=True)
    key = secrets.token_bytes(32)
    with open(_KEY_PATH, "wb") as f:
        f.write(key)
    # 设置文件为隐藏（Windows）
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(_KEY_PATH, 2)
    except Exception:
        pass
    return key


def _derive_encryption_key(master_key: bytes) -> bytes:
    """从主密钥派生加密密钥"""
    fingerprint = _derive_machine_fingerprint()
    return hashlib.pbkdf2_hmac(
        "sha256", master_key, fingerprint, 200000, dklen=32
    )


def _get_salt() -> bytes:
    """获取或创建 salt"""
    return _derive_machine_fingerprint()[:16]


def _encrypt(plaintext: str, key: bytes) -> bytes:
    """加密文本，返回密文（含 nonce）"""
    enc_key = _derive_encryption_key(key)
    nonce = secrets.token_bytes(16)
    plaintext_bytes = plaintext.encode("utf-8")

    # 用 enc_key + nonce 生成 keystream
    keystream = hashlib.pbkdf2_hmac(
        "sha256", enc_key, nonce, 1, dklen=len(plaintext_bytes) + 32
    )
    ciphertext = bytes(a ^ b for a, b in zip(plaintext_bytes, keystream[:len(plaintext_bytes)]))

    # [nonce(16) | ciphertext | mac_key(32)]
    mac_key = keystream[len(plaintext_bytes):]
    packet = nonce + ciphertext

    # HMAC 签名
    sig = hmac.new(mac_key, packet, hashlib.sha256).digest()

    return nonce + ciphertext + sig


def _decrypt(packet: bytes, key: bytes) -> str | None:
    """解密并验签，失败返回 None"""
    if len(packet) < 16 + 32:
        return None

    nonce = packet[:16]
    sig = packet[-32:]
    ciphertext = packet[16:-32]

    enc_key = _derive_encryption_key(key)
    keystream = hashlib.pbkdf2_hmac(
        "sha256", enc_key, nonce, 1, dklen=len(ciphertext) + 32
    )
    mac_key = keystream[len(ciphertext):]

    # 验签
    expected_sig = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected_sig):
        return None

    # 解密
    plaintext_bytes = bytes(a ^ b for a, b in zip(ciphertext, keystream[:len(ciphertext)]))
    return plaintext_bytes.decode("utf-8")


# ==================== 数据库操作 ====================

def _ensure_tables():
    """确保人格相关表存在"""
    import sqlite3
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS personality_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                encrypted_data BLOB NOT NULL,
                version INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS personality_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                dimensions_delta TEXT NOT NULL,
                reason TEXT,
                session_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS personality_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                encrypted_snapshot BLOB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
    finally:
        conn.close()


# ==================== 人格状态类 ====================

class PersonalityState:
    """人格状态单例"""

    def __init__(self):
        _ensure_tables()
        self._key = _get_or_create_key()
        self._state: dict = {}
        self._loaded = False

    def load(self) -> dict:
        """从数据库加载人格状态"""
        import sqlite3
        conn = sqlite3.connect(_DB_PATH, timeout=10)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            row = conn.execute(
                "SELECT encrypted_data, updated_at FROM personality_state WHERE id = 1"
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            self._state = dict(DEFAULT_PERSONALITY)
            self._loaded = True
            self._save()
            return self.get_state()

        packet = row[0]
        decrypted = _decrypt(packet, self._key)

        if decrypted is None:
            # 签名校验失败 —— 被篡改
            self._state = dict(DEFAULT_PERSONALITY)
            self._loaded = True
            self._save()
            self._log_event(
                "tamper_detected",
                {},
                "人格数据签名校验失败，已重置为默认值"
            )
            return self.get_state()

        try:
            data = json.loads(decrypted)
            # 保证所有维度都存在
            for key in DIMENSION_KEYS:
                if key not in data:
                    data[key] = DEFAULT_PERSONALITY[key]
            self._state = data
        except (json.JSONDecodeError, TypeError):
            self._state = dict(DEFAULT_PERSONALITY)
            self._save()

        self._loaded = True
        self._last_updated = row[1]
        return self.get_state()

    def get_state(self) -> dict:
        """获取当前人格状态（14 维）"""
        if not self._loaded:
            return self.load()
        return dict(self._state)

    def apply_deltas(self, deltas: dict, reason: str = "", session_id: str = ""):
        """应用维度变化（带边界裁剪）"""
        if not self._loaded:
            self.load()

        validated = {}
        for key, delta in deltas.items():
            if key not in DIMENSION_KEYS:
                continue
            delta = max(-0.3, min(0.3, delta))
            new_val = self._state.get(key, DEFAULT_PERSONALITY[key]) + delta
            new_val = max(0, min(100, new_val))
            self._state[key] = round(new_val, 2)
            validated[key] = round(delta, 2)

        if validated:
            self._save()
            self._log_event("evolution", validated, reason, session_id)

    def _save(self):
        """加密保存到数据库"""
        import sqlite3
        plaintext = json.dumps(self._state, ensure_ascii=False)
        packet = _encrypt(plaintext, self._key)
        conn = sqlite3.connect(_DB_PATH, timeout=10)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute(
                """INSERT OR REPLACE INTO personality_state (id, encrypted_data, version, updated_at)
                   VALUES (1, ?, 1, CURRENT_TIMESTAMP)""",
                (packet,)
            )
            conn.commit()
        finally:
            conn.close()

    def _log_event(self, event_type: str, deltas: dict, reason: str = "",
                   session_id: str = ""):
        """记录演化事件"""
        import sqlite3
        conn = sqlite3.connect(_DB_PATH, timeout=10)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                """INSERT INTO personality_events
                   (event_type, dimensions_delta, reason, session_id)
                   VALUES (?, ?, ?, ?)""",
                (event_type, json.dumps(deltas, ensure_ascii=False),
                 reason, session_id)
            )
            conn.commit()
        finally:
            conn.close()

    def take_snapshot(self):
        """创建人格快照"""
        if not self._loaded:
            self.load()

        import sqlite3
        plaintext = json.dumps({
            "state": self._state,
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False)
        packet = _encrypt(plaintext, self._key)
        conn = sqlite3.connect(_DB_PATH, timeout=10)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                "INSERT INTO personality_snapshots (encrypted_snapshot) VALUES (?)",
                (packet,)
            )
            conn.commit()
        finally:
            conn.close()

    def apply_inactivity_regression(self):
        """应用不活跃回归（30 天无互动）"""
        if not self._loaded:
            self.load()

        deltas = {}
        for key in DIMENSION_KEYS:
            current = self._state.get(key, 50)
            default = DEFAULT_PERSONALITY[key]
            delta = (default - current) * INACTIVITY_REGRESSION_RATE
            if abs(delta) > 0.01:
                deltas[key] = round(delta, 2)

        if deltas:
            self.apply_deltas(deltas, reason="30 天无互动回归")


# ==================== 全局单例 ====================

_state_instance = None


def get_personality_state() -> PersonalityState:
    """获取人格状态单例"""
    global _state_instance
    if _state_instance is None:
        _state_instance = PersonalityState()
    return _state_instance
