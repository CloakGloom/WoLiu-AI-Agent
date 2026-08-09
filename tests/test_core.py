"""Agent 核心逻辑单元测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_system_prompt():
    """测试 System Prompt 构建"""
    from agent.rules.loader import build_system_prompt
    prompt = build_system_prompt()
    assert "驻地规则" in prompt
    assert "历史规则" in prompt
    assert "迁移" in prompt
    print("  [PASS] test_system_prompt")


def test_max_iterations():
    """测试最大迭代次数"""
    from agent.rules.loader import get_max_iterations
    max_iter = get_max_iterations()
    assert max_iter > 0
    assert max_iter <= 100
    print(f"  [PASS] test_max_iterations: {max_iter}")


def test_database_init():
    """测试数据库初始化"""
    from agent import database
    database.init_database()
    status = database.get_agent_status()
    assert status, "agent_status 不应为空"
    print(f"  [PASS] test_database_init: current_device={status.get('current_device')}")


if __name__ == "__main__":
    test_system_prompt()
    test_max_iterations()
    test_database_init()
    print("\ncore 测试全部通过!")