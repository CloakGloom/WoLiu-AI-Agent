"""数据库备份脚本"""

import os
import shutil
from datetime import datetime

# 路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "agent.db")
BACKUP_DIR = os.path.join(BASE_DIR, "data", "backups")


def backup():
    """备份数据库"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d")
    backup_path = os.path.join(BACKUP_DIR, f"agent_backup_{timestamp}.db")

    if os.path.exists(DB_PATH):
        shutil.copy2(DB_PATH, backup_path)
        print(f"数据库已备份: {backup_path}")
    else:
        print(f"数据库文件不存在: {DB_PATH}")


if __name__ == "__main__":
    backup()