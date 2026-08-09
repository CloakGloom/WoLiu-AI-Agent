"""
文件读取工具 —— 支持 txt、docx、pdf、md 等常见文档格式
支持本地绝对路径和上传文件路径
"""

import os

SCHEMA = {
    "type": "function",
    "tag": "文档",
    "function": {
        "name": "read_document",
        "description": "读取文档内容。支持 txt/md/docx/pdf/csv/json，大文件自动截断。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "文件路径。可以是本地绝对路径（如 D:\\docs\\report.pdf）或上传文件的相对路径（如 uploads/filename.pdf）。"
                },
                "max_chars": {
                    "type": "integer",
                    "description": "最大返回字符数，超出部分截断并提示。默认 8000。（可选）"
                }
            },
            "required": ["file_path"]
        }
    }
}

# 上传文件存储目录
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "data", "uploads"
)

# 纯文本扩展名
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".py", ".js", ".html", ".xml",
                   ".yaml", ".yml", ".ini", ".cfg", ".log", ".css", ".java",
                   ".c", ".cpp", ".h", ".rs", ".go", ".ts", ".sh", ".bat", ".ps1"}


def _read_text(file_path: str) -> str:
    """读取纯文本文件，尝试多种编码"""
    for encoding in ["utf-8", "gbk", "gb2312", "latin-1"]:
        try:
            with open(file_path, "r", encoding=encoding) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"无法解码文件，已尝试 utf-8/gbk/gb2312/latin-1")


def _read_docx(file_path: str) -> str:
    """读取 Word 文档"""
    from docx import Document
    doc = Document(file_path)
    paragraphs = []
    for para in doc.paragraphs:
        if para.text.strip():
            # 检测标题样式
            if para.style.name.startswith("Heading"):
                level = para.style.name.split()[-1]
                try:
                    level = int(level)
                    paragraphs.append("#" * level + " " + para.text)
                except ValueError:
                    paragraphs.append(para.text)
            else:
                paragraphs.append(para.text)
    return "\n\n".join(paragraphs)


def _read_pdf(file_path: str) -> str:
    """读取 PDF 文档"""
    from PyPDF2 import PdfReader
    reader = PdfReader(file_path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text and text.strip():
            pages.append(text.strip())
    return "\n\n".join(pages)


def _resolve_path(file_path: str) -> str:
    """解析文件路径：支持绝对路径和相对于 uploads 目录的路径"""
    if os.path.isabs(file_path):
        if os.path.exists(file_path):
            return file_path
        raise FileNotFoundError(f"文件不存在：{file_path}")

    # 尝试在 uploads 目录下查找
    upload_path = os.path.join(UPLOAD_DIR, file_path)
    if os.path.exists(upload_path):
        return upload_path

    # 尝试直接拼接
    if os.path.exists(file_path):
        return os.path.abspath(file_path)

    raise FileNotFoundError(f"文件不存在：{file_path}（也尝试过 uploads/{file_path}）")


def _get_file_info(file_path: str) -> str:
    """获取文件基本信息"""
    size = os.path.getsize(file_path)
    if size < 1024:
        size_str = f"{size} B"
    elif size < 1024 * 1024:
        size_str = f"{size / 1024:.1f} KB"
    else:
        size_str = f"{size / (1024 * 1024):.1f} MB"
    return f"{os.path.basename(file_path)} ({size_str})"


def execute(arguments: dict) -> str:
    file_path = arguments.get("file_path", "").strip()
    max_chars = arguments.get("max_chars", 8000) or 8000

    if not file_path:
        return "请提供文件路径（file_path 参数）。"

    try:
        real_path = _resolve_path(file_path)
        ext = os.path.splitext(real_path)[1].lower()
        info = _get_file_info(real_path)

        # 根据扩展名选择读取方式
        if ext in TEXT_EXTENSIONS:
            content = _read_text(real_path)
        elif ext == ".docx":
            content = _read_docx(real_path)
        elif ext == ".pdf":
            content = _read_pdf(real_path)
        else:
            # 未知类型，尝试当纯文本读取
            try:
                content = _read_text(real_path)
            except Exception:
                return f"不支持的文件格式：{ext}。支持的格式：txt、md、docx、pdf、csv、json、py 等。"

        if not content or not content.strip():
            return f"文件 {info} 内容为空或无法提取文本。"

        # 截断处理
        if len(content) > max_chars:
            truncated = content[:max_chars]
            return (
                f"📄 {info}（内容已截断，共 {len(content)} 字符，显示前 {max_chars} 字符）\n\n"
                f"{truncated}\n\n"
                f"...（剩余 {len(content) - max_chars} 字符未显示）"
            )

        return f"📄 {info}（共 {len(content)} 字符）\n\n{content}"

    except FileNotFoundError as e:
        return str(e)
    except Exception as e:
        return f"读取文件失败：{e}"