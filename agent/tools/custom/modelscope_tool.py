"""
魔搭 ModelScope 模型搜索与下载工具

AI 可调用此工具在魔搭社区搜索模型、查看模型详情、下载模型文件。
"""

import os, json

SCHEMA = {
    "type": "function",
    "tag": "工具/模型",
    "function": {
        "name": "modelscope_model",
        "description": (
            "在魔搭社区（ModelScope）搜索和下载 AI 模型。"
            "支持：搜索模型、查看详情、下载模型文件到本地。"
            "魔搭是国内最大的开源模型平台，涵盖 LLM、视觉、语音、多模态等。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作类型：search（搜索模型）、info（查看模型详情）、download（下载模型）",
                    "enum": ["search", "info", "download"]
                },
                "query": {
                    "type": "string",
                    "description": "（仅 search）搜索关键词，如 'yolo'、'qwen'、'chattts'"
                },
                "model_id": {
                    "type": "string",
                    "description": "（仅 info / download）模型 ID，如 'qwen/Qwen2.5-7B'、'iic/ChatTTS'"
                },
                "save_dir": {
                    "type": "string",
                    "description": "（仅 download）下载到哪个目录，默认为 D:/Downloads/models"
                }
            },
            "required": ["action"]
        }
    }
}


def execute(arguments: dict) -> str:
    action = arguments.get("action", "").strip()
    query = arguments.get("query", "").strip()
    model_id = arguments.get("model_id", "").strip()
    from agent.config import modelscope_cache_dir as _cfg_ms_cache
    save_dir = arguments.get("save_dir", "").strip() or _cfg_ms_cache()

    if not action:
        return "请指定操作类型（action）"

    try:
        # ── SEARCH ──
        if action == "search":
            if not query:
                return "请提供搜索关键词（query）"

            from modelscope.hub.api import HubApi
            api = HubApi()
            results = api.list_models(query, limit=15)
            if not results:
                return f"未找到与 '{query}' 相关的模型"

            lines = [f"魔搭搜索结果（关键词: {query}）:\n"]
            for m in results[:10]:
                name = m.get('Name', m.get('ModelId', '?'))
                task = m.get('Task', '')
                desc = (m.get('Description', '') or '')[:80]
                downloads = m.get('Downloads', 0)
                lines.append(f"• {name}")
                if task: lines[-1] += f" [{task}]"
                if desc: lines.append(f"  {desc}")
                if downloads: lines.append(f"  下载量: {downloads}")

            return "\n".join(lines)

        # ── INFO ──
        elif action == "info":
            if not model_id:
                return "请提供模型 ID（model_id）"

            from modelscope.hub.api import HubApi
            api = HubApi()
            info = api.get_model(model_id)
            if not info:
                return f"模型未找到：{model_id}"

            name = info.get('Name', model_id)
            task = info.get('Task', '未知')
            desc = info.get('Description', '无描述')
            tags = info.get('Tags', [])
            created = info.get('GmtCreate', '')
            modified = info.get('GmtModified', '')

            return (
                f"模型详情：{name}\n"
                f"• ID: {model_id}\n"
                f"• 任务类型: {task}\n"
                f"• 标签: {', '.join(tags) if tags else '无'}\n"
                f"• 创建时间: {created}\n"
                f"• 更新时间: {modified}\n"
                f"• 描述: {desc[:300]}"
            )

        # ── DOWNLOAD ──
        elif action == "download":
            if not model_id:
                return "请提供模型 ID（model_id）"

            os.makedirs(save_dir, exist_ok=True)

            from modelscope.hub.api import HubApi
            api = HubApi()

            try:
                from agent.tools import emit_progress
                emit_progress("modelscope_model", 10, f"正在下载 {model_id} ...")
            except Exception:
                pass

            # 获取文件列表
            files = api.get_model_files(model_id)
            if not files:
                return f"无法获取模型文件列表：{model_id}"

            total = len(files)
            downloaded = []
            for i, f in enumerate(files):
                fname = f.get('Name', '')
                if not fname:
                    continue
                dst = os.path.join(save_dir, fname)
                if os.path.exists(dst):
                    downloaded.append(fname)
                    continue
                # 只下载小文件（<200MB），大文件提示手动下载
                fsize = f.get('Size', 0)
                if fsize > 200 * 1024 * 1024:
                    downloaded.append(f"{fname} (跳过，太大，请手动下载)")
                    continue

                try:
                    api.download_file(model_id, fname, dst)
                    downloaded.append(fname)
                    pct = int((i + 1) / total * 90) + 5
                    try:
                        from agent.tools import emit_progress
                        emit_progress("modelscope_model", pct, f"下载中... {fname}")
                    except Exception:
                        pass
                except Exception as e:
                    downloaded.append(f"{fname} (失败: {e})")

            return (
                f"模型下载完成：{model_id}\n"
                f"• 保存目录: {save_dir}\n"
                f"• 文件: {len(downloaded)}/{total}\n"
                + "\n".join(f"  {d}" for d in downloaded[:20])
                + ("\n...（更多文件已省略）" if len(downloaded) > 20 else "")
            )

        else:
            return f"未知操作: {action}"

    except ImportError:
        return "modelscope SDK 未安装。请在 WSL 或 Anaconda 环境中运行: pip install modelscope"
    except Exception as e:
        import traceback
        return f"操作失败：{e}\n{traceback.format_exc()}"
