"""文件读取工具"""

import os


def read_file(file_path: str, encoding: str = "utf-8") -> str:
    """读取文件内容"""
    if not os.path.exists(file_path):
        return f"文件不存在: {file_path}"
    try:
        with open(file_path, "r", encoding=encoding) as f:
            return f.read()
    except Exception as e:
        return f"读取失败: {e}"


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(read_file(sys.argv[1]))
    else:
        print("用法: python read.py <文件路径>")