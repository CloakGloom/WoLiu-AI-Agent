"""
微信 ↔ Agent 桥接服务
将微信消息转发给 Agent 处理，并将回复发回微信
支持图片、文件等媒体消息的自动转发
"""
import logging
import re
import sys
import os
import tempfile
import uuid
from typing import Callable

import httpx

# 确保项目根目录在 Python 路径中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agent import database
from agent.core import run_agent

logger = logging.getLogger("weixin_bridge")

# 图片/文件标记正则
IMAGE_RE = re.compile(r'\[IMAGE:([^\]]+)\]')
PAPER_RE = re.compile(r'\[PAPER:([^\]]+)\]')


class WeChatBridge:
    """微信 ↔ Agent 桥接器"""

    def __init__(self, bot):
        self.bot = bot
        self._sessions: dict[str, str] = {}  # wx_user_id → agent_session_id
        self._last_context: dict[str, str] = {}  # wx_user_id → context_token（用于图片/文件发送）

    def handle_message(self, text: str, from_user: str) -> str | None:
        """
        处理微信消息，转发给 Agent 并返回回复
        自动处理回复中的图片和文件标记
        """
        if not text or not text.strip():
            return None

        text = text.strip()
        logger.info(f"[{from_user}] 收到: {text}")

        # 获取或创建 Agent 会话
        session_id = self._get_or_create_session(from_user)

        # 构建 messages
        messages = [{"role": "user", "content": text}]

        # 保存用户消息到数据库
        try:
            database.save_message(session_id, "user", text, "微信")
        except Exception as e:
            logger.warning(f"保存用户消息失败: {e}")

        # 调用 Agent
        try:
            reply = run_agent(
                messages=messages,
                session_id=session_id,
            )
        except Exception as e:
            logger.error(f"Agent 调用失败: {e}")
            return "抱歉，我暂时无法处理你的消息，请稍后再试。"

        if not reply:
            return None

        reply = reply.strip()
        print(f"[微信桥接] AI回复: {reply[:200]}")

        # 处理回复中的图片/文件标记，通过微信发送媒体
        reply = self._send_media_from_reply(reply, from_user)

        return reply

    def _send_media_from_reply(self, reply: str, from_user: str) -> str:
        """从回复中提取图片/文件标记，发送媒体消息，返回清理后的文本"""
        ct = self._last_context.get(from_user, self.bot.context_token)
        print(f"[微信桥接] 开始检查媒体标记, reply前100字: {reply[:100]}")

        # 处理图片标记
        for match in IMAGE_RE.finditer(reply):
            url = match.group(1)
            print(f"[微信桥接] 发现图片标记: {url}")
            image_path = self._resolve_url_to_path(url)
            if image_path:
                print(f"[微信桥接] 图片路径: {image_path}, 文件存在: {os.path.exists(image_path)}")
                ok = self.bot.send_image(image_path, to=from_user, context_token=ct)
                print(f"[微信桥接] send_image 结果: {ok}")
                if not ok:
                    logger.error(f"图片发送失败: {image_path}")
            else:
                print(f"[微信桥接] 无法解析图片路径: {url}")

        # 处理论文/文件标记
        for match in PAPER_RE.finditer(reply):
            url = match.group(1)
            print(f"[微信桥接] 发现文件标记: {url}")
            file_path = self._resolve_url_to_path(url)
            if file_path:
                print(f"[微信桥接] 文件路径: {file_path}, 文件存在: {os.path.exists(file_path)}")
                ok = self.bot.send_file(file_path, to=from_user, context_token=ct)
                print(f"[微信桥接] send_file 结果: {ok}")
                if not ok:
                    logger.error(f"文件发送失败: {file_path}")
            else:
                print(f"[微信桥接] 无法解析文件路径: {url}")

        # 清理标记，保留描述文字
        reply = IMAGE_RE.sub('', reply)
        reply = PAPER_RE.sub('', reply)
        reply = reply.strip()

        return reply if reply else None

    def _resolve_url_to_path(self, url: str) -> str | None:
        """将服务器相对路径 URL 解析为本地文件路径"""
        if url.startswith("/static/"):
            local_path = os.path.join(PROJECT_ROOT, "server", url.lstrip("/"))
            if os.path.exists(local_path):
                return local_path
        elif url.startswith("http://") or url.startswith("https://"):
            # 远程 URL：下载到临时文件
            try:
                resp = httpx.get(url, timeout=30, follow_redirects=True)
                if resp.status_code == 200:
                    suffix = ".png"
                    if "content-type" in resp.headers:
                        ct = resp.headers["content-type"]
                        if "jpeg" in ct or "jpg" in ct:
                            suffix = ".jpg"
                        elif "pdf" in ct:
                            suffix = ".pdf"
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                    tmp.write(resp.content)
                    tmp.close()
                    return tmp.name
            except Exception as e:
                logger.warning(f"下载远程文件失败 [{url}]: {e}")
        return None

    def _get_or_create_session(self, wx_user_id: str) -> str:
        """获取或创建微信用户对应的 Agent 会话"""
        if wx_user_id in self._sessions:
            sid = self._sessions[wx_user_id]
            # 验证会话是否仍存在
            try:
                session = database.get_session(sid)
                if session:
                    return sid
            except Exception:
                pass

        # 创建新会话
        try:
            sid = database.create_session(device="微信")
            self._sessions[wx_user_id] = sid
            logger.info(f"为微信用户 [{wx_user_id}] 创建会话: {sid}")
            return sid
        except Exception as e:
            logger.error(f"创建会话失败: {e}")
            # 降级：使用 UUID
            sid = f"wx-{uuid.uuid4().hex[:12]}"
            self._sessions[wx_user_id] = sid
            return sid


def create_handler(bridge: WeChatBridge) -> Callable:
    """创建微信消息处理器"""
    def handler(text: str, from_user: str, context_token: str = "") -> str | None:
        if context_token:
            bridge._last_context[from_user] = context_token
        return bridge.handle_message(text, from_user)
    return handler