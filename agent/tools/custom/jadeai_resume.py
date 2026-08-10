"""
JadeAI 简历生成工具 —— 直接产出 PDF 文件，无需用户手动操作页面。
两种模式：
  1) action=create  ：LLM 自行撰写结构化简历内容 → 创建 JadeAI 简历 → 服务端渲染 PDF → 返回内嵌 PDF 链接
  2) action=generate：解析用户上传的文件，交给 JadeAI AI 引擎生成简历 → 同样直接导出 PDF

PDF 导出后额外执行视觉排版质检：
用 PyMuPDF 将 PDF 渲染为图片，交给视觉模型（VISION_MODEL）检查排版问题，
质检结果随工具返回，由主 LLM 决定是否需要调整后重新生成。

输出 PDF 保存到 server/static/papers/，通过 [PAPER:url] 标记在对话中内嵌展示。
"""

import os
import re
import json
import uuid
import base64
import httpx

from config import VISION_API_KEY, VISION_BASE_URL, VISION_MODEL
from agent.tools import emit_progress

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUTPUT_DIR = os.path.join(ROOT, "server", "static", "papers")
os.makedirs(OUTPUT_DIR, exist_ok=True)

from agent.config import jadeai_url as _cfg_jadeai, server_host as _cfg_svr_host, server_port as _cfg_svr_port
_jade_base = _cfg_jadeai()
JADEAI_API = f"{_jade_base}/jade/api"
JADEAI_EDITOR = f"http://localhost:{_cfg_svr_port()}/resume-editor"
FINGERPRINT = "agent_bridge"
HEADERS = {
    "Content-Type": "application/json",
    "x-fingerprint": FINGERPRINT,
}

SECTION_TITLES_ZH = {
    "personal_info": "个人信息",
    "summary": "个人简介",
    "work_experience": "工作经历",
    "education": "教育背景",
    "skills": "技能特长",
    "projects": "项目经历",
}
SECTION_TITLES_EN = {
    "personal_info": "Personal Info",
    "summary": "Summary",
    "work_experience": "Work Experience",
    "education": "Education",
    "skills": "Skills",
    "projects": "Projects",
}

SCHEMA = {
    "type": "function",
    "tag": "工具",
    "function": {
        "name": "jadeai_resume",
        "description": (
            "制作简历并直接输出 PDF 文件（用户无需任何手动操作）。"
            "两种模式："
            "1) action=create：你根据用户需求自行撰写简历内容（用户没给信息就合理虚构测试内容），"
            "通过 name/position/summary/work_experience/education/skills 等参数传入结构化内容，"
            "工具渲染成专业模板 PDF 并返回文件链接；"
            "2) action=generate：用户提供 Word/PDF/图片文件时，传 file_path，"
            "由 JadeAI AI 引擎解析生成简历并导出 PDF。"
            "⚠️ 用户要求写简历/生成简历/做简历时，必须调用本工具直接给出 PDF，"
            "不要只返回网页链接让用户自己去操作。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "generate"],
                    "description": "create=由你撰写内容生成；generate=解析用户上传的文件生成",
                },
                "title": {
                    "type": "string",
                    "description": "简历标题（可选，默认按岗位生成）",
                },
                "template": {
                    "type": "string",
                    "description": "模板名（可选），如 classic/modern/minimal/professional/creative/developer 等，默认 classic",
                },
                "language": {
                    "type": "string",
                    "description": "简历语言 zh 或 en，默认 zh",
                },
                "name": {
                    "type": "string",
                    "description": "create 模式：姓名（用户未提供可合理虚构）",
                },
                "position": {
                    "type": "string",
                    "description": "create 模式：求职岗位/头衔",
                },
                "email": {
                    "type": "string",
                    "description": "create 模式：邮箱（可选）",
                },
                "phone": {
                    "type": "string",
                    "description": "create 模式：电话（可选）",
                },
                "location": {
                    "type": "string",
                    "description": "create 模式：所在城市（可选）",
                },
                "summary": {
                    "type": "string",
                    "description": "create 模式：个人简介/自我评价（2-4 句）",
                },
                "work_experience": {
                    "type": "array",
                    "description": "create 模式：工作经历列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "company": {"type": "string", "description": "公司名"},
                            "position": {"type": "string", "description": "职位"},
                            "start_date": {"type": "string", "description": "开始时间 YYYY-MM"},
                            "end_date": {"type": "string", "description": "结束时间 YYYY-MM，在职填'至今'"},
                            "description": {"type": "string", "description": "工作职责简述（可选）"},
                            "highlights": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "业绩亮点，每条一句话",
                            },
                        },
                        "required": ["company", "position", "start_date"],
                    },
                },
                "education": {
                    "type": "array",
                    "description": "create 模式：教育背景列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "institution": {"type": "string", "description": "学校"},
                            "degree": {"type": "string", "description": "学历，如 本科/硕士"},
                            "field": {"type": "string", "description": "专业"},
                            "start_date": {"type": "string", "description": "开始时间 YYYY-MM"},
                            "end_date": {"type": "string", "description": "结束时间 YYYY-MM"},
                        },
                        "required": ["institution", "degree"],
                    },
                },
                "skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "create 模式：技能列表，如 ['Python', 'React', '项目管理']",
                },
                "projects": {
                    "type": "array",
                    "description": "create 模式：项目经历列表（可选）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "项目名"},
                            "description": {"type": "string", "description": "项目描述"},
                            "technologies": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "使用的技术",
                            },
                        },
                        "required": ["name"],
                    },
                },
                "file_path": {
                    "type": "string",
                    "description": "generate 模式：用户上传的 Word/PDF/图片文件路径（绝对路径）",
                },
                "job_title": {
                    "type": "string",
                    "description": "generate 模式：目标岗位（可选，从文件中推断）",
                },
            },
            "required": ["action"],
        },
    },
}


def execute(args: dict) -> str:
    """执行简历生成并直接导出 PDF。"""
    action = args.get("action", "create")
    language = (args.get("language") or "zh").strip()
    template = (args.get("template") or "classic").strip()

    if action == "create":
        return _create_resume(args, language, template)
    elif action == "generate":
        return _generate_from_file(args, language, template)
    return f"❌ 未知操作: {action}，支持 create / generate"


# ==================== create：LLM 内容直建 ====================

def _create_resume(args: dict, language: str, template: str) -> str:
    name = (args.get("name") or "").strip()
    position = (args.get("position") or "").strip()
    if not name and not position:
        return "❌ create 模式至少需要提供 name（姓名）或 position（岗位）"

    emit_progress("jadeai_resume", 10, "正在整理简历内容...")
    titles = SECTION_TITLES_EN if language == "en" else SECTION_TITLES_ZH
    sections = []

    # 个人信息（照片留空）
    sections.append({
        "type": "personal_info",
        "title": titles["personal_info"],
        "visible": True,
        "content": {
            "fullName": name,
            "jobTitle": position,
            "email": args.get("email") or "",
            "phone": args.get("phone") or "",
            "location": args.get("location") or "",
        },
    })

    summary = (args.get("summary") or "").strip()
    if summary:
        sections.append({
            "type": "summary",
            "title": titles["summary"],
            "visible": True,
            "content": {"text": summary},
        })

    work_items = []
    for w in args.get("work_experience") or []:
        end_date = (w.get("end_date") or "").strip()
        current = end_date in ("至今", "present", "now", "")
        work_items.append({
            "company": w.get("company", ""),
            "position": w.get("position", ""),
            "location": "",
            "startDate": w.get("start_date", ""),
            "endDate": None if current else end_date,
            "current": current,
            "description": w.get("description") or "",
            "highlights": w.get("highlights") or [],
        })
    if work_items:
        sections.append({
            "type": "work_experience",
            "title": titles["work_experience"],
            "visible": True,
            "content": {"items": work_items},
        })

    edu_items = []
    for e in args.get("education") or []:
        edu_items.append({
            "institution": e.get("institution", ""),
            "degree": e.get("degree", ""),
            "field": e.get("field") or "",
            "location": "",
            "startDate": e.get("start_date") or "",
            "endDate": e.get("end_date") or "",
            "highlights": [],
        })
    if edu_items:
        sections.append({
            "type": "education",
            "title": titles["education"],
            "visible": True,
            "content": {"items": edu_items},
        })

    skill_list = [s for s in (args.get("skills") or []) if s]
    if skill_list:
        sections.append({
            "type": "skills",
            "title": titles["skills"],
            "visible": True,
            "content": {"categories": [{"id": str(uuid.uuid4()), "name": titles["skills"], "skills": skill_list}]},
        })

    proj_items = []
    for p in args.get("projects") or []:
        proj_items.append({
            "name": p.get("name", ""),
            "description": p.get("description") or "",
            "technologies": p.get("technologies") or [],
            "highlights": [],
        })
    if proj_items:
        sections.append({
            "type": "projects",
            "title": titles["projects"],
            "visible": True,
            "content": {"items": proj_items},
        })

    resume_title = (args.get("title") or "").strip() or (
        f"{name}的简历" if name and language == "zh" else (name or position or "Resume")
    )

    # ── 1. 创建简历 ──
    emit_progress("jadeai_resume", 30, "正在创建简历...")
    try:
        r = httpx.post(
            f"{JADEAI_API}/resume",
            json={
                "title": resume_title,
                "template": template,
                "language": language,
                "sections": sections,
            },
            headers=HEADERS,
            timeout=30,
        )
    except httpx.ConnectError:
        return "❌ 无法连接 JadeAI 服务 (localhost:3002)，请确保 JadeAI 已启动"
    except Exception as e:
        return f"❌ 创建简历异常: {type(e).__name__}: {e}"

    if r.status_code not in (200, 201):
        return f"❌ 创建简历失败 ({r.status_code}): {_error_detail(r)}"

    resume_id = (r.json() or {}).get("id", "")
    if not resume_id:
        return "❌ 创建简历失败：未获取到简历 ID"

    # ── 2. 导出 PDF ──
    return _export_pdf(resume_id, resume_title)


# ==================== generate：文件解析生成 ====================

def _generate_from_file(args: dict, language: str, template: str) -> str:
    file_path = (args.get("file_path") or "").strip()
    job_title = (args.get("job_title") or "").strip()

    if not file_path or not os.path.isfile(file_path):
        return f"❌ 文件不存在: {file_path}"

    emit_progress("jadeai_resume", 10, "正在读取文件内容...")
    ext = os.path.splitext(file_path)[1].lower()
    file_content = ""
    try:
        if ext == ".pdf":
            from PyPDF2 import PdfReader
            reader = PdfReader(file_path)
            file_content = "\n".join(p.extract_text() or "" for p in reader.pages)
        elif ext in (".docx", ".doc"):
            from docx import Document
            doc = Document(file_path)
            file_content = "\n".join(p.text for p in doc.paragraphs)
        elif ext in (".txt", ".md", ".json"):
            file_content = open(file_path, encoding="utf-8", errors="replace").read()
        elif ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            from PIL import Image
            img = Image.open(file_path)
            file_content = f"[图片文件: {os.path.basename(file_path)}, 尺寸: {img.size[0]}x{img.size[1]}]"
        else:
            try:
                file_content = open(file_path, encoding="utf-8", errors="replace").read()
            except Exception:
                return f"❌ 不支持的文件格式: {ext}"
    except Exception as e:
        return f"❌ 读取文件失败: {type(e).__name__}: {e}"

    if not file_content.strip():
        return "❌ 文件内容为空，无法提取信息"

    # 从内容中推断岗位
    if not job_title:
        title_keywords = ["工程师", "经理", "设计师", "开发", "运营", "产品", "前端", "后端",
                          "Engineer", "Manager", "Designer", "Developer", "Product",
                          "教师", "医生", "律师", "会计", "销售", "市场", "人力资源", "行政"]
        for kw in title_keywords:
            if kw in file_content:
                job_title = kw
                break
    job_title = job_title or "软件工程师"
    exp_years = max(1, min(10, len(file_content.split("\n")) // 20))

    # ── 调用 JadeAI AI 引擎生成 ──
    emit_progress("jadeai_resume", 30, "正在调用 JadeAI AI 引擎生成简历（约 30-60 秒）...")
    try:
        r = httpx.post(
            f"{JADEAI_API}/ai/generate-resume",
            json={
                "jobTitle": job_title,
                "yearsOfExperience": exp_years,
                "skills": _extract_skills(file_content),
                "language": language,
                "template": template,
                "experience": file_content[:3000],
            },
            headers={**HEADERS, "Accept-Language": language},
            timeout=180,
        )
    except httpx.ConnectError:
        return "❌ 无法连接 JadeAI 服务 (localhost:3002)，请确保 JadeAI 已启动"
    except Exception as e:
        return f"❌ 生成异常: {type(e).__name__}: {e}"

    if r.status_code != 200:
        return f"❌ JadeAI 生成失败 ({r.status_code}): {_error_detail(r)}"

    result = r.json()
    resume_id = result.get("resumeId") or result.get("id", "")
    resume_title = result.get("title") or job_title
    if not resume_id:
        return f"❌ 生成失败：未获取到简历 ID（响应: {str(result)[:200]}）"

    return _export_pdf(resume_id, resume_title)


# ==================== 公共：导出 PDF 并落地为静态文件 ====================

def _export_pdf(resume_id: str, resume_title: str) -> str:
    emit_progress("jadeai_resume", 60, "正在渲染 PDF（服务端 Chrome 排版中）...")
    try:
        r = httpx.get(
            f"{JADEAI_API}/resume/{resume_id}/export",
            params={"format": "pdf"},
            headers=HEADERS,
            timeout=180,
        )
    except httpx.ConnectError:
        return "❌ 无法连接 JadeAI 服务 (localhost:3002)"
    except Exception as e:
        return f"❌ 导出 PDF 异常: {type(e).__name__}: {e}"

    editor_link = f"{JADEAI_EDITOR}?load={resume_id}"
    # 保存简历数据，供编辑器加载
    import json as _json
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "data", "resumes")
    os.makedirs(data_dir, exist_ok=True)
    args_copy = {k: v for k, v in args.items() if k not in ("_session_id", "action")}
    args_copy["resume_id"] = resume_id
    import time as _time
    args_copy["generated_at"] = _time.strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(data_dir, f"{resume_id}.json"), "w", encoding="utf-8") as f:
        _json.dump(args_copy, f, ensure_ascii=False, indent=2)

    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("application/pdf"):
        detail = _error_detail(r)
        return (
            f"❌ PDF 导出失败：{detail}\n"
            f"简历已创建成功，可在线查看并手动导出：{editor_link}"
        )

    filename = f"resume_{uuid.uuid4().hex[:8]}.pdf"
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(r.content)

    url = f"/static/papers/{filename}"

    # ── 3. 视觉模型排版质检 ──
    emit_progress("jadeai_resume", 85, "视觉模型正在审查排版...")
    passed, report = _vision_check_layout(filepath)

    lines = [f"✅ 简历《{resume_title}》已生成 PDF 文件。"]
    if passed is True:
        lines.append(f"🔍 视觉质检：排版检查通过（{report}）")
    elif passed is False:
        lines.append(f"🔍 视觉质检发现排版问题：{report}")
        lines.append("如问题影响阅读，请调整内容（精简文字/换 template）后重新调用本工具生成；不影响使用时可忽略。")
    else:
        lines.append(f"🔍 视觉质检：{report}")

    lines.append("请将以下 PDF 原样展示给用户（不要只发链接文字）：")
    lines.append(f"[PAPER:{url}]")
    lines.append(f"如需在线编辑调整，可访问：{editor_link}")
    emit_progress("jadeai_resume", 100, "简历 PDF 生成完成")
    return "\n".join(lines)


# ==================== 视觉排版质检 ====================

_LAYOUT_CHECK_PROMPT = (
    "你是专业的简历排版审查员。上面的图片是一份简历 PDF 的逐页渲染结果。"
    "请检查是否存在以下排版问题："
    "1) 文字溢出、重叠或被截断；"
    "2) 各区块间距明显失衡或错位；"
    "3) 内容在不恰当的位置跨页断裂；"
    "4) 末尾出现几乎空白的多余页面；"
    "5) 乱码或字体缺失。"
    "没有问题则严格回答 JSON：{\"pass\": true, \"issues\": []}；"
    "有问题则：{\"pass\": false, \"issues\": [\"具体问题描述（含页码）\"]}。"
    "只回答 JSON，不要任何其他文字。"
)


def _render_pdf_pages(pdf_path: str, max_pages: int, zoom: float) -> list:
    """将 PDF 前 N 页渲染为 base64 JPEG data URL 列表"""
    import pymupdf

    parts = []
    doc = pymupdf.open(pdf_path)
    try:
        for i in range(min(len(doc), max_pages)):
            pix = doc[i].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            img_b64 = base64.b64encode(pix.tobytes("jpeg")).decode("utf-8")
            parts.append({"type": "text", "text": f"以下是简历第 {i + 1} 页："})
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
            })
    finally:
        doc.close()
    return parts


def _call_vision_api(content_parts: list) -> str:
    """调用视觉模型，连接失败自动重试一次，返回原始文本"""
    last_err = None
    for _ in range(2):
        try:
            resp = httpx.post(
                f"{VISION_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {VISION_API_KEY}"},
                json={
                    "model": VISION_MODEL,
                    "messages": [{"role": "user", "content": content_parts}],
                    "max_tokens": 600,
                },
                timeout=240,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            last_err = e
    raise last_err


def _vision_check_layout(pdf_path: str) -> tuple:
    """将 PDF 渲染为图片，调用视觉模型审查排版。

    优先 2 页 1.5x 清晰度；视觉模型不可用（超时/显存不足）时降级为 1 页 1.0x 重试。

    Returns:
        (passed, report)：passed 为 True/False/None（未能检查），report 为描述文本
    """
    if not VISION_API_KEY:
        return None, "未配置视觉模型，已跳过排版检查"

    try:
        # 先试 2 页高清，失败（超时/显存不足）降级为 1 页标清
        text = None
        for max_pages, zoom in ((2, 1.5), (1, 1.0)):
            content_parts = _render_pdf_pages(pdf_path, max_pages, zoom)
            content_parts.append({"type": "text", "text": _LAYOUT_CHECK_PROMPT})
            try:
                text = _call_vision_api(content_parts)
                break
            except Exception as e:
                if max_pages == 1:
                    return None, f"排版检查异常（{type(e).__name__}），已跳过，不影响 PDF 交付"

        # 容错解析：剥离代码围栏后取第一个 JSON 对象
        cleaned = re.sub(r"^\s*```(?:json)?|```\s*$", "", text.strip(), flags=re.MULTILINE)
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        data = json.loads(match.group(0)) if match else {}

        passed = bool(data.get("pass", True))
        issues = data.get("issues") or []
        if passed:
            return True, "未发现排版问题"
        return False, "；".join(str(x) for x in issues[:5])
    except Exception as e:
        return None, f"排版检查异常（{type(e).__name__}），已跳过，不影响 PDF 交付"


# ==================== 辅助函数 ====================

def _error_detail(r: httpx.Response) -> str:
    try:
        return r.json().get("error", r.text[:200])
    except Exception:
        return r.text[:200] if r.text else "未知错误"


def _extract_skills(text: str) -> list:
    """从文本中提取技能关键词。"""
    skill_pool = [
        "Python", "Java", "JavaScript", "TypeScript", "React", "Vue", "Node.js",
        "SQL", "PostgreSQL", "MongoDB", "Kubernetes", "AWS", "Git",
        "机器学习", "数据分析", "项目管理", "团队领导", "PPT", "Excel",
        "Photoshop", "Figma", "视频剪辑", "文案写作", "英语六级",
        "沟通能力", "Python开发", "前端开发", "后端开发", "全栈开发",
    ]
    found = [s for s in skill_pool if s.lower() in text.lower()]
    return found[:8] if found else ["办公软件", "团队协作", "项目管理"]
