"""
JadeAI 模拟面试工具
通过我流 Agent 对话触发，引导用户使用 JadeAI 的 AI 模拟面试功能。

触发方式：由 AI 根据用户意图自行判断（不依赖固定关键词），
只要用户表达了模拟面试、练习面试、询问面试功能等语义即可调用。
注意：制作/生成简历请改用 jadeai_resume 工具（可直接输出 PDF），本工具不处理简历。
"""

import httpx


SCHEMA = {
    "type": "function",
    "tag": "工具",
    "function": {
        "name": "mock_interview",
        "description": "JadeAI 模拟面试（不处理简历，简历请用 jadeai_resume 工具直接生成 PDF）。link 获取面试页面地址，status 检查服务。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "link"],
                    "description": "操作类型：status 检查 JadeAI 服务是否在线，link 获取模拟面试页面完整 URL",
                },
            },
            "required": ["action"],
        },
    },
}


def execute(args: dict) -> str:
    """执行模拟面试工具操作。

    Args:
        args: {"action": "status"|"link"}

    Returns:
        操作结果描述字符串
    """
    from agent.config import jadeai_url as _cfg_jadeai
    _jade_base = _cfg_jadeai()
    action = args.get("action", "status")
    jade_url = f"{_jade_base}/jade/zh/interview"
    resume_url = f"{_jade_base}/jade/zh/dashboard"

    if action == "status":
        try:
            resp = httpx.get(f"{_jade_base}/jade/", timeout=5)
            return (
                f"JadeAI 服务已在线（状态码 {resp.status_code}）。"
                f"模拟面试地址：{jade_url} ，"
                f"简历管理：{resume_url}"
            )
        except httpx.ConnectError:
            return (
                "JadeAI 服务当前未启动。"
                "请等待服务启动后重试（通常需要 30-60 秒），"
                "或联系管理员检查 side-projects/JadeAI-0.4.1 配置。"
            )
        except Exception as exc:
            return f"JadeAI 服务状态检查失败：{exc}"

    elif action == "link":
        return (
            f"🎯 JadeAI 模拟面试系统\n\n"
            f"📋 模拟面试：{jade_url}\n"
            f"📝 简历管理：{resume_url}\n"
            f"\n功能亮点：\n"
            f"  · 6 种预设面试官（HR面 / 技术面 / 场景面 / 行为面 / 项目深挖 / Leader 面）\n"
            f"  · 自定义面试官与考察维度\n"
            f"  · AI 自适应追问——回答不到位会自动深入提问\n"
            f"  · 面试控制：跳过 / 提示 / 标记复习 / 暂停\n"
            f"  · 逐题评分 + 能力雷达图 + 改进建议 + 历史对比\n"
            f"  · 支持 PDF / Markdown 报告导出\n"
            f"  · 50 套专业简历模板 + AI 简历生成 / JD 匹配分析 / 语法检查"
        )

    return f"未知操作: {action}。支持的操作: status, link"
