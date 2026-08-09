"""
手机端客户端 —— HTTP API 调用 + 终端交互
运行环境：Termux (Android) + Python 3.10+
通信方式：通过 HTTP API 与电脑端通信
"""

import requests


# ==================== 配置 ====================
# 默认服务器地址（启动时可由用户输入覆盖）
# 从 config.yaml 读取 server.ws_port，IP 由用户输入
import os as _client_os
try:
    _p = _client_os.path.dirname(_client_os.path.dirname(_client_os.path.dirname(_client_os.path.abspath(__file__))))
    _client_os.chdir(_p)
    from agent.config import ws_port as _cfg_ws_port
    _default_port = _cfg_ws_port()
except Exception:
    _default_port = 8765
SERVER_URL = f"http://192.168.1.100:{_default_port}"


# ==================== API 调用函数 ====================

def api_get_status() -> dict:
    """获取 Agent 当前状态"""
    try:
        r = requests.get(f"{SERVER_URL}/api/agent/status", timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def api_create_session(device: str = "手机") -> dict:
    """创建新会话"""
    try:
        r = requests.post(f"{SERVER_URL}/api/sessions", json={"device": device}, timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def api_get_messages(session_id: str) -> dict:
    """获取会话消息历史"""
    try:
        r = requests.get(f"{SERVER_URL}/api/sessions/{session_id}/messages", timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def api_send_message(session_id: str, content: str) -> dict:
    """发送消息并获取回复"""
    try:
        r = requests.post(
            f"{SERVER_URL}/api/sessions/{session_id}/messages",
            json={"content": content, "device": "手机"},
            timeout=60
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def api_trigger_migrate(direction: str) -> dict:
    """发起迁移指令"""
    try:
        r = requests.post(
            f"{SERVER_URL}/api/agent/migrate",
            json={"direction": direction},
            timeout=10
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def api_get_sessions() -> dict:
    """获取活跃会话列表"""
    try:
        r = requests.get(f"{SERVER_URL}/api/sessions", timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {"error": str(e)}


# ==================== 主程序 ====================

def main():
    global SERVER_URL

    print("=" * 50)
    print("  AI Agent 手机端客户端")
    print("=" * 50)
    print()

    # 输入服务器地址
    addr = input(f"请输入电脑端地址 [{SERVER_URL}]: ").strip()
    if addr:
        SERVER_URL = addr.rstrip("/")

    print(f"\n连接地址: {SERVER_URL}")
    print()

    # 检查连接
    print("正在连接服务器...")
    status = api_get_status()
    if "error" in status:
        print(f"❌ 无法连接服务器: {status['error']}")
        print("   请确保：")
        print("   1. 电脑端已启动 (python run_server.py)")
        print("   2. 手机和电脑在同一局域网")
        print("   3. IP 地址正确")
        return

    current_device = status.get("current_device", "未知")
    is_online = status.get("is_online", False)
    current_session_id = status.get("session_id")

    print(f"✅ 已连接服务器")
    print(f"   Agent 当前在: {current_device}端")
    print(f"   状态: {'在线' if is_online else '离线'}")
    print()

    # 获取或创建会话
    if current_session_id:
        session_id = current_session_id
        print(f"📋 当前会话: {session_id}")
    else:
        result = api_create_session("手机")
        if "error" in result:
            print(f"❌ 创建会话失败: {result['error']}")
            return
        session_id = result["session_id"]
        print(f"📋 已创建新会话: {session_id}")

    # 加载历史消息
    msgs = api_get_messages(session_id)
    if "error" not in msgs and msgs.get("messages"):
        print(f"📥 已加载 {len(msgs['messages'])} 条历史消息")
        for m in msgs["messages"][-5:]:  # 只显示最近5条
            role_label = "👤 你" if m["role"] == "user" else "🤖 Agent"
            content = m["content"][:80] + ("..." if len(m["content"]) > 80 else "")
            print(f"  {role_label}: {content}")
    print()

    # 主循环
    print("💡 提示：")
    print("  - 输入消息开始对话")
    print("  - 输入 '去手机' 将 Agent 迁移到手机端")
    print("  - 输入 '回电脑' 将 Agent 迁移回电脑端")
    print("  - 输入 'status' 查看 Agent 状态")
    print("  - 输入 'exit' 退出")
    print()

    while True:
        try:
            user_input = input("👤 你: ").strip()

            if not user_input:
                continue

            if user_input.lower() == "exit":
                print("👋 再见")
                break

            if user_input.lower() == "status":
                s = api_get_status()
                if "error" in s:
                    print(f"❌ {s['error']}")
                else:
                    print(f"   设备: {s.get('current_device')}")
                    print(f"   在线: {'是' if s.get('is_online') else '否'}")
                    print(f"   会话: {s.get('session_id')}")
                continue

            # 迁移命令
            if user_input == "去手机":
                print("正在迁移到手机端...")
                result = api_trigger_migrate("to_mobile")
                if "error" in result:
                    print(f"❌ {result['error']}")
                else:
                    print(f"📡 {result.get('result')}")
                continue

            if user_input == "回电脑":
                print("正在迁移回电脑端...")
                result = api_trigger_migrate("to_pc")
                if "error" in result:
                    print(f"❌ {result['error']}")
                else:
                    print(f"📡 {result.get('result')}")
                continue

            # 发送消息
            print("⏳ 思考中...")
            result = api_send_message(session_id, user_input)

            if "error" in result:
                print(f"❌ {result['error']}")
            else:
                print(f"\n🤖 Agent: {result.get('reply', '')}\n")

        except KeyboardInterrupt:
            print("\n👋 再见")
            break
        except EOFError:
            break


if __name__ == "__main__":
    main()