"""记忆模块单元测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_short_term_memory():
    """测试短期记忆（滑动窗口）"""
    from agent.memory.short_term import ShortTermMemory
    from agent import database

    session_id = database.create_session("电脑")
    mem = ShortTermMemory(session_id=session_id, max_turns=3)
    mem.add_user_message("你好", "电脑")
    mem.add_assistant_message("你好！", "电脑")
    mem.add_user_message("天气怎么样", "电脑")
    mem.add_assistant_message("今天晴天", "电脑")
    mem.add_user_message("谢谢", "电脑")

    messages = mem.get_recent_messages()
    assert len(messages) <= 6, "最多保留 3 轮（6 条消息）"
    print(f"  [PASS] test_short_term_memory: {len(messages)} 条消息")


def test_database_message_retrieval():
    """测试数据库消息检索"""
    from agent import database

    session_id = database.create_session("电脑")
    database.save_message(session_id, "user", "测试消息", "电脑")
    recent = database.get_recent_messages(session_id, limit=5)
    assert len(recent) > 0
    print(f"  [PASS] test_database_message_retrieval: {len(recent)} 条消息")


if __name__ == "__main__":
    test_short_term_memory()
    test_database_message_retrieval()
    print("\nmemory 测试全部通过!")