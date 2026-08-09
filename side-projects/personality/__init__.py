"""
AI Companion 人格系统 —— 15维动态演化 + 健康提醒

通过 config/settings.json → personality_enabled 控制开关。
"""
from agent.personality.state import get_personality_state
from agent.personality.evolution import get_evolution_engine
from agent.personality.filter import get_filter
from agent.personality.generator import generate_personality_prompt
from agent.personality.migration import export_personality, import_personality


def get_state() -> dict:
    return get_personality_state().get_state()


def record_event(event_type: str = "", user_msg: str = "",
                 assistant_msg: str = "", turn_count: int = 0,
                 session_id: str = "") -> dict:
    engine = get_evolution_engine()
    if event_type:
        return engine.record_interaction([event_type], session_id)
    return engine.process_turn(user_msg, assistant_msg, turn_count, session_id)


def apply_filter(text: str) -> str:
    return get_filter().apply(text)


def generate_prompt() -> str:
    return generate_personality_prompt()


def export_data(password: str) -> dict | str:
    return export_personality(password)


def import_data(data_blob: str, password: str) -> str | None:
    return import_personality(data_blob, password)


def init_personality_system():
    """启动时加载状态"""
    get_personality_state().load()


def start_wellness(push_callback):
    """启动健康提醒调度器"""
    from agent.personality.wellness import start_scheduler, set_push
    set_push(push_callback)
    start_scheduler()
