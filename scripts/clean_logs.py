"""日志清理脚本"""

import os
import glob
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "data", "logs")


def clean_logs(days: int = 7):
    """清理 N 天前的日志"""
    if not os.path.exists(LOG_DIR):
        print(f"日志目录不存在: {LOG_DIR}")
        return

    cutoff = datetime.now() - timedelta(days=days)
    count = 0

    for log_file in glob.glob(os.path.join(LOG_DIR, "*.log")):
        mtime = datetime.fromtimestamp(os.path.getmtime(log_file))
        if mtime < cutoff:
            os.remove(log_file)
            count += 1
            print(f"已删除: {os.path.basename(log_file)}")

    print(f"共清理 {count} 个日志文件（{days} 天前）")


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    clean_logs(days)