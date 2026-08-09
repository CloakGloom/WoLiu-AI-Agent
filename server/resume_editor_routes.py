"""
简历在线编辑器路由
路由: /resume-editor → 编辑器页面
      /api/resume-editor/load/{resume_id} → 加载 AI 生成的简历数据
"""
import os, json

RESUME_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume_editor.html")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESUME_DATA_DIR = os.path.join(PROJECT_ROOT, "data", "resumes")


def register(app):
    from fastapi.responses import FileResponse, JSONResponse

    @app.get("/resume-editor")
    async def resume_editor():
        return FileResponse(RESUME_HTML)

    @app.get("/api/resume-editor/load/{resume_id}")
    async def resume_load(resume_id: str):
        """加载 AI 生成的简历数据"""
        path = os.path.join(RESUME_DATA_DIR, f"{resume_id}.json")
        if not os.path.exists(path):
            return JSONResponse({"error": "简历数据未找到"}, status_code=404)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
