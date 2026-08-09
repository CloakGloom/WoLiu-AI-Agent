"""
手机端启动脚本
用法: 在项目根目录执行: python run_client.py
"""
import sys
import os

# 确保项目根目录在 Python 路径中
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# 同时加入当前工作目录（兼容从其他目录运行的情况）
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.insert(0, cwd)

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

from client.client import main

if __name__ == "__main__":
    main()