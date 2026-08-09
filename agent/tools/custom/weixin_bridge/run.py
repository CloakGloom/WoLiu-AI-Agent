"""
微信桥接入库脚本
用法: 在项目根目录执行: python agent/tools/custom/weixin_bridge/run.py

首次运行会弹出二维码，用微信扫码登录。
登录信息会保存在 wechat_config.json 中，后续启动无需重新扫码。
"""
import logging
import sys
import os

# 确保项目根目录在 Python 路径中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 加载 .env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
except ImportError:
    pass

from agent.tools.custom.weixin_bridge.ilink_client import WeChatBot, CONFIG_PATH
from agent.tools.custom.weixin_bridge.bridge import WeChatBridge, create_handler

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("weixin_bridge")


def main():
    print("""
╔══════════════════════════════════════════════╗
║      微信 ↔ Agent 桥接服务                    ║
║      基于 iLink Bot API                      ║
╚══════════════════════════════════════════════╝
    """)

    # ── 初始化数据库 ──
    from agent import database
    database.init_database()

    # ── 加载或创建 Bot ──
    bot = WeChatBot.from_config()

    if not bot or not bot.token:
        print("未检测到登录信息，正在进行首次登录...")
        login_info = WeChatBot.login()
        if not login_info:
            print("登录失败，请重试。")
            return

        bot = WeChatBot(
            token=login_info["token"],
            to_user_id=login_info["to_user_id"],
            context_token=login_info.get("context_token", ""),
        )
        bot.save_config()
        print("登录信息已保存。")

    # ── 创建桥接器 ──
    bridge = WeChatBridge(bot)
    handler = create_handler(bridge)

    print(f"开始监听微信消息...")
    print(f"按 Ctrl+C 停止服务\n")

    try:
        bot.listen(handler)
    except KeyboardInterrupt:
        print("\n服务已停止。")


if __name__ == "__main__":
    main()