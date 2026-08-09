"""文件写入工具"""

import os


def write_file(file_path: str, content: str, encoding: str = "utf-8") -> str:
    """写入文件内容"""
    try:
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with open(file_path, "w", encoding=encoding) as f:
            f.write(content)
        return f"写入成功: {file_path}"
    except Exception as e:
        return f"写入失败: {e}"


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2:
        print(write_file(sys.argv[1], sys.argv[2]))
    else:
        print("用法: python write.py <文件路径> <内容>")