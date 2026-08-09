"""
短期记忆模块 —— 滑动窗口上下文管理
"""

from agent import database


class ShortTermMemory:
    """短期记忆管理器，使用滑动窗口限制上下文长度"""

    def __init__(self, session_id: str, max_turns: int = None):
        self.session_id = session_id
        self.max_turns = max_turns or int(
            database.get_preference("max_history_turns") or "3"
        )

    def get_context(self) -> list:
        """获取当前会话上下文（OpenAI API 格式）"""
        return database.get_messages_as_openai_format(self.session_id, self.max_turns)

    def add_user_message(self, content: str, device: str):
        """添加用户消息"""
        database.save_message(self.session_id, "user", content, device)

    def add_assistant_message(self, content: str, device: str, tool_calls=None):
        """添加助手消息"""
        database.save_message(
            self.session_id, "assistant", content, device,
            tool_calls=tool_calls
        )

    def add_tool_result(self, content: str, device: str, tool_call_id: str):
        """添加工具返回结果"""
        database.save_message(
            self.session_id, "tool", content, device,
            tool_call_id=tool_call_id
        )

    def get_recent_messages(self, limit: int = None) -> list:
        """获取最近 N 条消息"""
        limit = limit or self.max_turns * 2
        return database.get_recent_messages(self.session_id, limit)

    def get_all_messages(self) -> list:
        """获取全部消息（用于迁移）"""
        return database.get_all_messages(self.session_id)

    def clear(self):
        """清空上下文（归档旧会话，创建新会话）"""
        database.archive_session(self.session_id)