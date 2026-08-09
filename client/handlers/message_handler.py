"""手机端消息处理模块 —— 消息收发与显示逻辑"""

from datetime import datetime


class MessageHandler:
    """消息处理与显示"""

    def __init__(self):
        self.messages = []
        self.session_id = None

    def load_messages(self, messages: list):
        """加载历史消息"""
        self.messages = messages

    def add_message(self, role: str, content: str):
        """添加消息并显示"""
        self.messages.append({
            "role": role,
            "content": content,
            "time": datetime.now().strftime("%H:%M:%S"),
        })

    def display_recent(self, count: int = 5):
        """显示最近 N 条消息"""
        recent = self.messages[-count:]
        for m in recent:
            role_label = "👤 你" if m["role"] == "user" else "🤖 Agent"
            content = m["content"]
            if len(content) > 80:
                content = content[:80] + "..."
            print(f"  {role_label}: {content}")

    def get_openai_format(self) -> list:
        """获取 OpenAI API 格式的消息列表"""
        return [
            {"role": m["role"], "content": m["content"]}
            for m in self.messages
        ]

    def clear(self):
        self.messages = []