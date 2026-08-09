"""
微信 iLink Bot API 客户端
基于腾讯官方 iLink 协议，支持扫码登录、消息收发、图片/文件发送
"""
import base64
import hashlib
import json
import logging
import os
import random
import secrets
import time
import uuid
from pathlib import Path

import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from agent.config import weixin_ilink_base as _cfg_ilink, weixin_cdn_base as _cfg_cdn
ILINK_BASE = _cfg_ilink()
CDN_BASE = _cfg_cdn()
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "wechat_config.json")

logger = logging.getLogger("weixin_bridge")


class WeChatBot:
    """微信 iLink Bot 客户端"""

    def __init__(self, token: str = "", to_user_id: str = "",
                 context_token: str = "", config_path: str = CONFIG_PATH):
        self.base = ILINK_BASE
        self.token = token
        self.to_user_id = to_user_id
        self.context_token = context_token
        self.config_path = config_path
        self._cursor = ""

    @classmethod
    def from_config(cls, path: str = CONFIG_PATH):
        """从配置文件加载 Bot"""
        p = Path(path)
        if not p.exists():
            return None
        cfg = json.loads(p.read_text())
        return cls(
            token=cfg.get("token", ""),
            to_user_id=cfg.get("to_user_id", ""),
            context_token=cfg.get("context_token", ""),
            config_path=path,
        )

    def save_config(self):
        """保存配置到文件"""
        cfg = {
            "token": self.token,
            "to_user_id": self.to_user_id,
            "context_token": self.context_token,
        }
        Path(self.config_path).write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False)
        )

    # ── HTTP 请求 ──────────────────────────────────

    def _headers(self) -> dict:
        uin = base64.b64encode(
            str(random.randint(0, 0xFFFFFFFF)).encode()
        ).decode()
        return {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {self.token}",
            "X-WECHAT-UIN": uin,
        }

    def _post(self, endpoint: str, body: dict, skip_base_info: bool = False) -> dict:
        """发送 POST 请求到 iLink API"""
        if not skip_base_info:
            body["base_info"] = {"channel_version": "1.0.3"}
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = self._headers()
        headers["Content-Length"] = str(len(raw))
        try:
            resp = httpx.post(
                f"{self.base}/ilink/bot/{endpoint}",
                content=raw, headers=headers, timeout=35,
            )
            text = resp.text.strip()
            return json.loads(text) if text and text != "{}" else {"ret": 0}
        except Exception as e:
            logger.error(f"iLink API 请求失败 [{endpoint}]: {e}")
            return {"ret": -1, "error": str(e)}

    def _get(self, path: str, params: dict = None, headers: dict = None) -> dict:
        """发送 GET 请求"""
        try:
            resp = httpx.get(
                f"{self.base}{path}",
                params=params, headers=headers, timeout=40,
            )
            return resp.json()
        except Exception as e:
            logger.error(f"iLink GET 请求失败 [{path}]: {e}")
            return {"error": str(e)}

    # ── 扫码登录 ──────────────────────────────────

    @staticmethod
    def login() -> dict | None:
        """
        扫码登录流程，返回登录信息或 None
        返回: {"token": str, "to_user_id": str, "account_id": str}
        """
        try:
            import qrcode as qrcode_lib
        except ImportError:
            print("请先安装 qrcode: pip install qrcode")
            return None

        # Step 1: 获取二维码
        print("正在获取登录二维码...")
        resp = httpx.get(f"{ILINK_BASE}/ilink/bot/get_bot_qrcode?bot_type=3")
        data = resp.json()
        qrcode_key = data["qrcode"]
        qrcode_url = data["qrcode_img_content"]

        # Step 2: 终端显示二维码
        qr = qrcode_lib.QRCode(border=1)
        qr.add_data(qrcode_url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
        print(f"\n扫码地址: {qrcode_url}")
        print("请用手机微信扫码，并在手机上确认登录...")

        # Step 3: 轮询扫码状态
        while True:
            status = httpx.get(
                f"{ILINK_BASE}/ilink/bot/get_qrcode_status?qrcode={qrcode_key}",
                headers={"iLink-App-ClientVersion": "1"},
                timeout=40,
            ).json()

            s = status.get("status", "")
            if s == "scaned":
                print("已扫码，请在手机上确认...")
            elif s == "confirmed":
                result = {
                    "token": status["bot_token"],
                    "to_user_id": status["ilink_user_id"],
                    "account_id": status["ilink_bot_id"],
                }
                print(f"登录成功！")
                print(f"  Bot ID: {result['account_id']}")
                print(f"  用户 ID: {result['to_user_id']}")
                return result
            elif s == "expired":
                print("二维码已过期，请重新运行")
                return None
            time.sleep(2)

    # ── 消息收发 ──────────────────────────────────

    def get_updates(self) -> list:
        """长轮询拉取新消息，自动更新 context_token"""
        result = self._post("getupdates", {"get_updates_buf": self._cursor})
        self._cursor = result.get("get_updates_buf", self._cursor)
        for msg in result.get("msgs", []):
            ct = msg.get("context_token", "")
            if ct:
                self.context_token = ct
                self._save_context_token(ct)
        return result.get("msgs", [])

    def send(self, text: str, to: str = None, context_token: str = None) -> bool:
        """发送文本消息"""
        result = self._post("sendmessage", {
            "msg": {
                "from_user_id": "",
                "to_user_id": to or self.to_user_id,
                "client_id": f"bot-{uuid.uuid4().hex[:12]}",
                "message_type": 2,      # BOT
                "message_state": 2,      # FINISH
                "context_token": context_token or self.context_token,
                "item_list": [{"type": 1, "text_item": {"text": text}}],
            }
        })
        # iLink API 成功时可能不返回 ret 字段，只要没有 error 就视为成功
        if "error" in result:
            logger.warning(f"发送消息失败: {result.get('error')}")
            return False
        return True

    def send_chunked(self, text: str, to: str = None,
                     context_token: str = None, delay: float = 0.8):
        """分块发送消息（模拟真人聊天节奏）"""
        import re
        chunks = []
        if "|||" in text:
            chunks = [c.strip() for c in text.split("|||") if c.strip()]
        else:
            paragraphs = re.split(r'\n\s*\n', text.strip())
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                if len(para) > 60:
                    sub = re.split(r'(?<=[。！？.!?\n])', para)
                    for s in sub:
                        s = s.strip()
                        if not s:
                            continue
                        if len(s) > 200:
                            sub2 = re.split(r'(?<=[，,；;：:])', s)
                            chunks.extend(x.strip() for x in sub2 if x.strip())
                        else:
                            chunks.append(s)
                else:
                    chunks.append(para)

        if not chunks:
            self.send(text, to, context_token)
            return

        for i, chunk in enumerate(chunks):
            ok = self.send(chunk, to, context_token)
            if not ok:
                logger.warning(f"发送第 {i+1}/{len(chunks)} 条消息失败")
            if i < len(chunks) - 1:
                d = delay + len(chunk) * 0.015 + random.uniform(-0.2, 0.3)
                time.sleep(max(0.3, d))

    # ── 图片/文件发送 ──────────────────────────────

    def send_image(self, image_path: str, to: str = None,
                   context_token: str = None) -> bool:
        """发送图片消息"""
        path = Path(image_path)
        if not path.exists():
            print(f"[微信桥接] send_image: 文件不存在 {image_path}")
            logger.error(f"图片文件不存在: {image_path}")
            return False

        data = path.read_bytes()
        print(f"[微信桥接] send_image: 开始上传 {path.name} ({len(data)} bytes)")
        media = self._upload_media(data, path.name, media_type=1,
                                   to_user_id=to or self.to_user_id)
        if not media:
            print(f"[微信桥接] send_image: 上传失败")
            return False

        print(f"[微信桥接] send_image: 上传成功, 发送消息...")
        result = self._post("sendmessage", {
            "msg": {
                "from_user_id": "",
                "to_user_id": to or self.to_user_id,
                "client_id": f"bot-{uuid.uuid4().hex[:12]}",
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token or self.context_token,
                "item_list": [{
                    "type": 2,
                    "image_item": {
                        "media": {
                            "encrypt_query_param": media["encrypt_query_param"],
                            "aes_key": media["aes_key"],
                            "encrypt_type": 1,
                        },
                        "mid_size": media["encrypted_size"],
                    },
                }],
            }
        })
        print(f"[微信桥接] send_image: sendmessage 响应: {json.dumps(result, ensure_ascii=False)[:200]}")
        if "error" in result:
            logger.warning(f"发送图片失败: {result.get('error')}")
            return False
        return True

    def send_file(self, file_path: str, to: str = None,
                  context_token: str = None) -> bool:
        """发送文件消息"""
        path = Path(file_path)
        if not path.exists():
            print(f"[微信桥接] send_file: 文件不存在 {file_path}")
            logger.error(f"文件不存在: {file_path}")
            return False

        data = path.read_bytes()
        print(f"[微信桥接] send_file: 开始上传 {path.name} ({len(data)} bytes)")
        media = self._upload_media(data, path.name, media_type=3,
                                   to_user_id=to or self.to_user_id)
        if not media:
            print(f"[微信桥接] send_file: 上传失败")
            return False

        print(f"[微信桥接] send_file: 上传成功, 发送消息...")
        result = self._post("sendmessage", {
            "msg": {
                "from_user_id": "",
                "to_user_id": to or self.to_user_id,
                "client_id": f"bot-{uuid.uuid4().hex[:12]}",
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token or self.context_token,
                "item_list": [{
                    "type": 4,
                    "file_item": {
                        "media": {
                            "encrypt_query_param": media["encrypt_query_param"],
                            "aes_key": media["aes_key"],
                            "encrypt_type": 1,
                        },
                        "file_name": path.name,
                        "len": str(media["raw_size"]),
                    },
                }],
            }
        })
        print(f"[微信桥接] send_file: sendmessage 响应: {json.dumps(result, ensure_ascii=False)[:200]}")
        if "error" in result:
            logger.warning(f"发送文件失败: {result.get('error')}")
            return False
        return True

    def _upload_media(self, data: bytes, file_name: str, media_type: int,
                      to_user_id: str) -> dict | None:
        """
        上传媒体文件到微信 CDN（AES-128-ECB 加密）
        media_type: 1=图片, 2=视频, 3=文件, 4=语音
        返回 CDNMedia dict，失败返回 None
        参考: @tencent-weixin/openclaw-weixin 官方实现
        """
        try:
            # 1. 生成 AES 密钥和加密
            aes_key = secrets.token_bytes(16)
            cipher = AES.new(aes_key, AES.MODE_ECB)
            encrypted = cipher.encrypt(pad(data, AES.block_size))

            raw_size = len(data)
            raw_md5 = hashlib.md5(data).hexdigest()
            enc_size = len(encrypted)
            filekey = secrets.token_hex(16)

            # 2. 获取上传凭证（完全对齐官方 TypeScript 实现）
            req_body = {
                "filekey": filekey,
                "media_type": media_type,
                "to_user_id": to_user_id,
                "rawsize": raw_size,
                "rawfilemd5": raw_md5,
                "filesize": enc_size,
                "no_need_thumb": True,
                "aeskey": aes_key.hex(),
            }
            logger.debug(f"[上传] 请求体: {json.dumps(req_body, ensure_ascii=False)}")
            resp = self._post("getuploadurl", req_body, skip_base_info=False)
            print(f"[微信桥接] getuploadurl 完整响应: {json.dumps(resp, ensure_ascii=False)}")
            logger.debug(f"[上传] 响应: {json.dumps(resp, ensure_ascii=False)}")
            # API 可能返回 upload_full_url 或 upload_param，兼容两种格式
            upload_full_url = resp.get("upload_full_url", "")
            upload_param = resp.get("upload_param", "")
            if not upload_full_url and not upload_param:
                logger.error(f"获取上传凭证失败: {resp}")
                return None

            # 3. POST 加密文件到 CDN（按官方格式构建 URL，不含 taskid）
            from urllib.parse import quote, urlparse, parse_qs, unquote
            if upload_param:
                # 官方格式：有 upload_param
                upload_url = (
                    f"{CDN_BASE}/upload?"
                    f"encrypted_query_param={quote(upload_param)}"
                    f"&filekey={quote(filekey)}"
                )
            elif upload_full_url:
                # API 返回了 upload_full_url，提取参数按官方格式重建
                parsed = urlparse(upload_full_url.strip("`"))
                qs = parse_qs(parsed.query)
                url_encrypt_param = qs.get("encrypted_query_param", [""])[0]
                if url_encrypt_param:
                    upload_url = (
                        f"{CDN_BASE}/upload?"
                        f"encrypted_query_param={quote(url_encrypt_param)}"
                        f"&filekey={quote(filekey)}"
                    )
                    print(f"[微信桥接] 按官方格式重建上传URL（去除taskid）")
                else:
                    upload_url = upload_full_url.strip("`")
            else:
                logger.error("获取上传凭证失败: 无 upload_param 或 upload_full_url")
                return None
            logger.debug(f"[上传] CDN URL: {upload_url[:100]}...")
            upload_resp = httpx.post(
                upload_url,
                content=encrypted,
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(enc_size),
                },
                timeout=60,
            )
            encrypted_param = upload_resp.headers.get("x-encrypted-param", "")
            print(f"[微信桥接] CDN上传响应: status={upload_resp.status_code}, "
                  f"x-encrypted-param={encrypted_param[:80] if encrypted_param else '无'}..., "
                  f"所有响应头: {dict(upload_resp.headers)}")
            if not encrypted_param:
                logger.error(f"CDN 上传失败: status={upload_resp.status_code}, body={upload_resp.text[:200]}")
                return None

            # 上传后等待 1 秒，确保 CDN 处理完毕
            import time as _time
            _time.sleep(1.0)

            # 4. 从 upload_full_url 中提取 encrypted_query_param（可能这才是消息里需要的引用）
            from urllib.parse import urlparse, parse_qs, unquote
            url_encrypt_param = ""
            if upload_full_url:
                parsed = urlparse(upload_full_url.strip("`"))
                qs = parse_qs(parsed.query)
                url_encrypt_param = qs.get("encrypted_query_param", [""])[0]
                if url_encrypt_param:
                    url_encrypt_param = unquote(url_encrypt_param)
                    print(f"[微信桥接] 从upload_full_url提取的encrypt_query_param: {url_encrypt_param[:80]}...")

            # 优先使用 API 返回的 encrypt_query_param 和 aes_key（如果有）
            api_encrypt_param = resp.get("encrypt_query_param", "")
            api_aes_key = resp.get("aes_key", "")
            
            # 尝试顺序：API返回的 > CDN返回的x-encrypted-param > upload_full_url里提取的
            final_encrypt_param = api_encrypt_param or encrypted_param or url_encrypt_param
            final_aes_key = api_aes_key if api_aes_key else base64.b64encode(aes_key).decode()
            
            print(f"[微信桥接] 最终参数: encrypt_query_param={final_encrypt_param[:80]}..., "
                  f"aes_key={'来自API' if api_aes_key else '来自本地计算'}")
            
            return {
                "encrypt_query_param": final_encrypt_param,
                "aes_key": final_aes_key,
                "encrypt_type": 1,
                "file_name": file_name,
                "raw_size": raw_size,
                "encrypted_size": enc_size,
                "md5": raw_md5,
            }
        except Exception as e:
            logger.error(f"上传媒体失败: {e}")
            return None

    def _save_context_token(self, ct: str):
        """持久化保存 context_token"""
        try:
            p = Path(self.config_path)
            if p.exists():
                cfg = json.loads(p.read_text())
                cfg["context_token"] = ct
                p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
        except Exception:
            pass

    def test_upload(self, file_path: str = None):
        """
        测试上传流程（独立调试用）
        用法: bot.test_upload("test.png")
        """
        # 临时启用 debug 日志
        logging.basicConfig(level=logging.DEBUG, format="[%(name)s] %(levelname)s: %(message)s")
        test_logger = logging.getLogger("weixin_bridge")

        if not file_path:
            # 生成一个 1x1 的 PNG 作为测试图片
            import struct, zlib
            def _make_png(w=1, h=1):
                raw = b""
                for y in range(h):
                    raw += b"\x00" + b"\xff\x00\x00" * w  # 红色像素
                def _chunk(ctype, data):
                    c = ctype + data
                    return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
                return (
                    b"\x89PNG\r\n\x1a\n"
                    + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                    + _chunk(b"IDAT", zlib.compress(raw))
                    + _chunk(b"IEND", b"")
                )
            data = _make_png()
            file_name = "test.png"
        else:
            p = Path(file_path)
            if not p.exists():
                test_logger.error(f"文件不存在: {file_path}")
                return
            data = p.read_bytes()
            file_name = p.name

        test_logger.info(f"=== 上传测试: {file_name} ({len(data)} bytes) ===")
        test_logger.info(f"  token: {self.token[:20]}...")
        test_logger.info(f"  to_user_id: {self.to_user_id}")

        # 尝试不同的参数组合
        test_logger.info("--- 方案1: encrypt_type=1, skip_base_info=True, 含 media_type ---")
        r1 = self._upload_media(data, file_name, media_type=1, to_user_id=self.to_user_id)
        test_logger.info(f"  结果: {'成功' if r1 else '失败'}")

        if not r1:
            test_logger.info("--- 方案2: encrypt_type=1, skip_base_info=False, 含 media_type ---")
            # 直接调用含 base_info 的版本
            try:
                aes_key_hex = secrets.token_hex(16)
                aes_key_bytes = bytes.fromhex(aes_key_hex)
                cipher = AES.new(aes_key_bytes, AES.MODE_ECB)
                encrypted = cipher.encrypt(pad(data, AES.block_size))
                req_body = {
                    "to_user_id": self.to_user_id,
                    "file_name": file_name,
                    "filekey": secrets.token_hex(16),
                    "raw_size": len(data),
                    "md5": hashlib.md5(data).hexdigest(),
                    "enc_size": len(encrypted),
                    "media_type": 1,
                    "encrypt_type": 1,
                    "aes_key": aes_key_hex,
                }
                test_logger.debug(f"  请求体: {json.dumps(req_body, ensure_ascii=False)}")
                r2 = self._post("getuploadurl", req_body, skip_base_info=False)
                test_logger.debug(f"  响应: {json.dumps(r2, ensure_ascii=False)}")
                test_logger.info(f"  结果: {'成功' if r2.get('upload_param') else '失败'} ret={r2.get('ret')}")
            except Exception as e:
                test_logger.error(f"  异常: {e}")

            test_logger.info("--- 方案3: encrypt_type=true (布尔), skip_base_info=True ---")
            try:
                aes_key_hex = secrets.token_hex(16)
                aes_key_bytes = bytes.fromhex(aes_key_hex)
                cipher = AES.new(aes_key_bytes, AES.MODE_ECB)
                encrypted = cipher.encrypt(pad(data, AES.block_size))
                req_body = {
                    "to_user_id": self.to_user_id,
                    "file_name": file_name,
                    "filekey": secrets.token_hex(16),
                    "raw_size": len(data),
                    "md5": hashlib.md5(data).hexdigest(),
                    "enc_size": len(encrypted),
                    "media_type": 1,
                    "encrypt_type": True,
                    "aes_key": aes_key_hex,
                }
                test_logger.debug(f"  请求体: {json.dumps(req_body, ensure_ascii=False)}")
                r3 = self._post("getuploadurl", req_body, skip_base_info=True)
                test_logger.debug(f"  响应: {json.dumps(r3, ensure_ascii=False)}")
                test_logger.info(f"  结果: {'成功' if r3.get('upload_param') else '失败'} ret={r3.get('ret')}")
            except Exception as e:
                test_logger.error(f"  异常: {e}")

    def listen(self, handler, interval: float = 3.0):
        """
        持续监听微信消息（阻塞）
        handler: callable(text, from_user_id, context_token) -> str | None
        """
        logger.info("开始监听微信消息...")
        while True:
            try:
                msgs = self.get_updates()
                for msg in msgs:
                    ct = msg.get("context_token", "")
                    from_user = msg.get("from_user_id", "")
                    text = ""
                    for item in msg.get("item_list", []):
                        if item.get("type") == 1:
                            text = item.get("text_item", {}).get("text", "")
                    if ct and text:
                        logger.info(f"收到微信消息 [{from_user}]: {text[:50]}...")
                        reply = handler(text, from_user, ct)
                        if reply:
                            self.send_chunked(reply, to=from_user, context_token=ct)
                            logger.info(f"已回复 [{from_user}]: {reply[:50]}...")
            except Exception as e:
                logger.error(f"监听循环异常: {e}")
                time.sleep(interval)