"""邮件发送工具（预留）"""

import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def send_email(to: str, subject: str, body: str) -> str:
    """
    发送邮件（当前为预留实现）
    后续可接入 SMTP 服务：smtplib + email.mime
    """
    return f"[预留] 邮件发送功能待实现: to={to}, subject={subject}"


if __name__ == "__main__":
    print(send_email("test@example.com", "Test", "Hello World"))