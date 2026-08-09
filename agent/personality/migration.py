"""
人格迁移 —— 加密导出/导入

换电脑时安全迁移人格数据，防止他人用你的 AI 记忆。

导出流程：
  用户输入密码 → 用机器密钥解密人格状态 → 用 PBKDF2(密码) 重新加密 → 导出 blob
导入流程：
  用户输入密码 → 用 PBKDF2(密码) 解密 → 用新机器密钥重新加密 → 保存

密码强度要求：≥8 位，含字母+数字。
"""

import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime

from agent.personality.dimensions import DIMENSION_KEYS, DEFAULT_PERSONALITY
from agent.personality.state import _encrypt, _decrypt, get_personality_state

# ==================== 密码加解密 ====================

_MIN_PASSWORD_LENGTH = 8


def validate_password(password: str) -> str | None:
    """验证密码强度，返回错误信息或 None"""
    if len(password) < _MIN_PASSWORD_LENGTH:
        return f"密码至少 {_MIN_PASSWORD_LENGTH} 位"
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not has_letter or not has_digit:
        return "密码必须包含字母和数字"
    return None


def _derive_key_from_password(password: str, salt: bytes) -> bytes:
    """从密码派生加密密钥"""
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 500000, dklen=32
    )


def _encrypt_with_password(plaintext: str, password: str) -> bytes:
    """用密码加密（生成随机 salt）"""
    salt = secrets.token_bytes(32)
    key = _derive_key_from_password(password, salt)
    packet = _encrypt(plaintext, key)
    return salt + packet


def _decrypt_with_password(data: bytes, password: str) -> str | None:
    """用密码解密，失败返回 None"""
    if len(data) < 32 + 16 + 32:
        return None
    salt = data[:32]
    packet = data[32:]
    key = _derive_key_from_password(password, salt)
    return _decrypt(packet, key)


# ==================== 导出/导入 ====================

def export_personality(password: str) -> dict | str:
    """导出人格数据为可迁移的加密包

    Args:
        password: 用户设定的迁移密码（≥8位，含字母+数字）

    Returns:
        dict: 成功返回 {"data": base64_blob, "manifest": {...}}
        str: 失败返回错误信息
    """
    error = validate_password(password)
    if error:
        return error

    state = get_personality_state()
    current_state = state.get_state()

    # 组装导出数据
    export_data = {
        "version": 1,
        "exported_at": datetime.now().isoformat(),
        "personality": current_state,
        "checksum": hashlib.sha256(
            json.dumps(current_state, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
    }

    plaintext = json.dumps(export_data, ensure_ascii=False)
    encrypted = _encrypt_with_password(plaintext, password)

    # Base64 编码以便传输
    import base64
    b64_data = base64.b64encode(encrypted).decode("ascii")

    # 清单（不包含敏感信息，方便用户识别）
    manifest = {
        "version": 1,
        "exported_at": export_data["exported_at"],
        "dimensions_count": len(DIMENSION_KEYS),
        "checksum": export_data["checksum"][:16],
    }

    return {
        "data": b64_data,
        "manifest": manifest,
    }


def import_personality(data_blob: str, password: str) -> str | None:
    """导入人格数据

    Args:
        data_blob: 导出时返回的 Base64 编码数据
        password: 导出时设置的迁移密码

    Returns:
        None: 导入成功
        str: 错误信息
    """
    error = validate_password(password)
    if error:
        return error

    # Base64 解码
    import base64
    try:
        encrypted = base64.b64decode(data_blob)
    except Exception:
        return "数据格式无效，无法解码"

    # 密码解密
    plaintext = _decrypt_with_password(encrypted, password)
    if plaintext is None:
        return "密码错误或数据已损坏"

    # 解析 JSON
    try:
        data = json.loads(plaintext)
    except (json.JSONDecodeError, TypeError):
        return "数据格式无效，无法解析"

    version = data.get("version", 0)
    if version != 1:
        return f"不支持的导出格式版本: {version}"

    imported_personality = data.get("personality", {})
    if not imported_personality:
        return "导出的数据中没有找到人格信息"

    # 校验 checksum
    expected = hashlib.sha256(
        json.dumps(imported_personality, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    if expected != data.get("checksum", ""):
        return "数据校验失败，文件可能已被篡改"

    # 验证维度完整性
    for key in DIMENSION_KEYS:
        if key not in imported_personality:
            imported_personality[key] = DEFAULT_PERSONALITY[key]

    # 加载到当前系统（用新机器密钥重新加密）
    state = get_personality_state()
    state._state = imported_personality
    state._loaded = True
    state._save()

    # 记录迁移事件
    manifest = data.get("exported_at", "未知时间")
    state._log_event(
        "personality_imported",
        {},
        f"从外部导入人格数据（导出时间: {manifest}）"
    )

    return None
