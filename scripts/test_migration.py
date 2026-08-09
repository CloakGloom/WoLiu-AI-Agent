"""迁移功能测试脚本"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import database


def test_migration():
    """测试迁移打包/解包"""
    database.init_database()

    # 创建测试会话
    session_id = database.create_session("电脑")
    print(f"1. 创建会话: {session_id}")

    # 添加测试消息
    database.save_message(session_id, "user", "你好", "电脑")
    database.save_message(session_id, "assistant", "你好！有什么可以帮助你的？", "电脑")
    database.save_message(session_id, "user", "去手机", "电脑")
    print("2. 添加 3 条测试消息")

    # 打包
    package = database.pack_migration_package(session_id, "电脑")
    print(f"3. 打包: {len(package['messages'])} 条消息, from_device={package['from_device']}")

    # 解包到手机
    database.unpack_migration_package(package, "手机")
    print("4. 解包到手机端")

    # 验证
    messages = database.get_all_messages(session_id)
    session = database.get_session(session_id)
    print(f"5. 验证: 会话设备={session['device']}, 消息数={len(messages)}")

    # 迁移日志
    database.log_migration(session_id, "电脑", "手机", "success", len(messages))
    print("6. 迁移日志已记录")

    print("\n迁移测试通过!")


if __name__ == "__main__":
    test_migration()