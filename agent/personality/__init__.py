"""
AI Companion 人格模块 —— 仅对外暴露六个函数

封闭模块。内部加密存储、演化引擎、过滤逻辑均不暴露。
外部只能通过这些接口使用人格系统。
"""

from agent.personality.state import get_personality_state
from agent.personality.evolution import get_evolution_engine
from agent.personality.filter import get_filter
from agent.personality.generator import generate_personality_prompt
from agent.personality.migration import export_personality, import_personality


def get_state() -> dict:
    """获取当前 14 维人格状态

    Returns:
        dict: {warmth: 55, extroversion: 45, ...}
    """
    return get_personality_state().get_state()


def record_event(event_type: str = "", user_msg: str = "",
                 assistant_msg: str = "", turn_count: int = 0,
                 session_id: str = "") -> dict:
    """记录一次对话交互，触发人格演化

    可以传入 event_type 直接指定交互类型，或传入 user_msg 自动分析。

    Args:
        event_type: 手动指定交互类型（可选，优先级高于自动分析）
        user_msg: 用户消息文本（用于自动分析）
        assistant_msg: AI 回复文本
        turn_count: 当前对话轮数
        session_id: 会话 ID

    Returns:
        dict: 本次应用的维度变化，如 {"humor": 0.15, "sarcasm": 0.05}
    """
    engine = get_evolution_engine()
    if event_type:
        return engine.record_interaction([event_type], session_id)
    return engine.process_turn(user_msg, assistant_msg, turn_count, session_id)


def apply_filter(text: str) -> str:
    """应用人格过滤器，调整 LLM 输出语气

    在 LLM 生成文本后、发送给用户前调用。

    Args:
        text: LLM 原始输出文本

    Returns:
        str: 经过人格过滤后的文本
    """
    return get_filter().apply(text)


def generate_prompt() -> str:
    """生成人格 Prompt 片段，注入到 System Prompt 中

    Returns:
        str: 人格描述文本，可直接追加到 System Prompt 末尾
    """
    return generate_personality_prompt()


def export_data(password: str) -> dict | str:
    """导出人格数据（用于换电脑迁移）

    用人设密码加密导出当前人格状态。
    导出的数据离开你的密码就是无用字节。

    Args:
        password: 迁移密码（≥8 位，含字母+数字）

    Returns:
        dict: 成功 → {"data": base64加密串, "manifest": {...}}
        str: 失败 → 错误信息
    """
    return export_personality(password)


def import_data(data_blob: str, password: str) -> str | None:
    """导入人格数据（用于换电脑迁移）

    用导出时设置的密码解密并恢复人格状态。

    Args:
        data_blob: export_data 返回的 data 字段
        password: 导出时设置的迁移密码

    Returns:
        None: 导入成功
        str: 失败原因
    """
    return import_personality(data_blob, password)
