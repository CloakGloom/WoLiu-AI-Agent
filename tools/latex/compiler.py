"""
LaTeX 编译器封装 —— 自动检测项目内或系统 LaTeX 引擎
优先级：tools/latex/miktex/ → 系统 PATH → 常见安装路径
"""

import os
import sys
import subprocess
import shutil

# 项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _find_pdflatex() -> str:
    """自动查找 pdflatex.exe 路径"""
    # 1. 项目内便携版
    candidates = [
        os.path.join(ROOT, "tools", "latex", "miktex", "bin", "x64", "pdflatex.exe"),
        os.path.join(ROOT, "tools", "latex", "miktex", "bin", "pdflatex.exe"),
        os.path.join(ROOT, "tools", "latex", "texlive", "bin", "windows", "pdflatex.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p

    # 2. 系统 PATH
    found = shutil.which("pdflatex")
    if found:
        return found

    # 3. 从 config.yaml 读取 external.latex_paths
    from agent.config import find_pdflatex as _cfg_latex
    _cfg = _cfg_latex()
    if _cfg:
        return _cfg

    return ""


def _find_xelatex() -> str:
    """自动查找 xelatex.exe（支持中文更好）"""
    # 从 pdflatex 路径推断 xelatex 路径
    pdf = _find_pdflatex()
    if pdf:
        xelatex = pdf.replace("pdflatex", "xelatex")
        if os.path.exists(xelatex):
            return xelatex

    # 系统 PATH
    found = shutil.which("xelatex")
    if found:
        return found

    return ""


def get_engine() -> str:
    """获取可用的 LaTeX 引擎，优先 xelatex（中文支持好），其次 pdflatex"""
    xelatex = _find_xelatex()
    if xelatex:
        return xelatex
    pdf = _find_pdflatex()
    return pdf


def get_bin_dir() -> str:
    """获取 LaTeX 引擎所在 bin 目录"""
    engine = get_engine()
    if engine:
        return os.path.dirname(engine)
    return ""


def has_latex() -> bool:
    """检查是否有可用的 LaTeX 引擎"""
    return bool(get_engine())


def compile(tex_path: str, output_dir: str = None, engine: str = None,
            runs: int = 2) -> tuple:
    """
    编译 .tex 文件为 PDF

    参数:
        tex_path: .tex 源文件路径
        output_dir: 输出目录（默认与 .tex 同目录）
        engine: 指定引擎（默认自动检测 xelatex）
        runs: 编译次数（默认2次，解决交叉引用）

    返回:
        (success: bool, pdf_path: str, log: str)
    """
    if not engine:
        engine = get_engine()
    if not engine:
        return False, "", "未找到 LaTeX 引擎（pdflatex/xelatex）"

    if not os.path.exists(tex_path):
        return False, "", f"文件不存在：{tex_path}"

    tex_dir = os.path.dirname(os.path.abspath(tex_path))
    tex_name = os.path.splitext(os.path.basename(tex_path))[0]

    if output_dir is None:
        output_dir = tex_dir
    os.makedirs(output_dir, exist_ok=True)

    # 编译参数
    engine_name = os.path.basename(engine).replace(".exe", "")
    cmd_base = [
        engine,
        "-interaction=nonstopmode",
        "-output-directory", output_dir,
        tex_name + ".tex"
    ]

    all_logs = []
    for i in range(runs):
        try:
            result = subprocess.run(
                cmd_base,
                cwd=tex_dir,
                capture_output=True,
                text=True,
                timeout=120,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "PATH": get_bin_dir() + ";" + os.environ.get("PATH", "")}
            )
            all_logs.append(result.stdout)
        except subprocess.TimeoutExpired:
            return False, "", f"编译超时（第{i+1}次）"

    pdf_path = os.path.join(output_dir, tex_name + ".pdf")
    success = os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0

    # 提取关键错误信息
    log_summary = _extract_errors("\n".join(all_logs)) if not success else ""

    # 清理辅助文件
    for ext in [".aux", ".log", ".out", ".toc", ".lof", ".lot", ".bbl", ".blg", ".synctex.gz"]:
        aux = os.path.join(output_dir, tex_name + ext)
        if os.path.exists(aux):
            try:
                os.remove(aux)
            except OSError:
                pass

    return success, pdf_path, log_summary


def _extract_errors(log: str) -> str:
    """从 LaTeX 日志中提取关键错误"""
    lines = log.split("\n")
    errors = []
    for i, line in enumerate(lines):
        if line.startswith("!"):
            # 收集错误行及后续几行
            err_lines = [line]
            for j in range(i + 1, min(i + 5, len(lines))):
                if lines[j].startswith("!") or lines[j].startswith("("):
                    break
                err_lines.append(lines[j])
            errors.append("\n".join(err_lines))
    if not errors:
        return "编译失败，请检查 .log 文件。"
    return "\n\n".join(errors[:5])


if __name__ == "__main__":
    # 检测
    e = get_engine()
    if e:
        print(f"LaTeX 引擎: {e}")
    else:
        print("未找到 LaTeX 引擎")
        print("请将 MiKTeX 便携版解压到 tools/latex/miktex/")
        print("下载: https://miktex.org/download (选择 Portable Edition)")