"""
规则加载模块 —— 从数据库和配置文件动态加载行为规则
"""

import json
import os
from agent import database


# 规则文件路径
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RULES_CONFIG_PATH = os.path.join(_BASE_DIR, "config", "rules_config.json")


def load_rules_from_db() -> list:
    """从数据库加载所有启用的规则"""
    return database.get_all_rules()


def load_rules_from_config() -> dict:
    """从配置文件加载规则"""
    if os.path.exists(RULES_CONFIG_PATH):
        with open(RULES_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def build_system_prompt() -> str:
    """构建完整的 System Prompt（包含行为规则）"""
    rules = load_rules_from_db()
    config = load_rules_from_config()

    max_iterations = database.get_rule("max_iterations") or "10"
    default_device = database.get_rule("default_device") or "电脑"

    # 设备信息
    current_device = database.get_current_device()

    # 动态读取可用工具列表
    from agent.tools import _RAW_TOOLS, _disabled_tools
    tool_lines = []
    for tool in _RAW_TOOLS:
        name = tool.get("function", {}).get("name", "")
        if name in _disabled_tools:
            continue
        desc = tool.get("function", {}).get("description", "")
        # 取描述的第一句作为简短说明
        short_desc = desc.split("。")[0].split("\n")[0][:80]
        tool_lines.append(f"- {name}：{short_desc}")

    prompt = f"""## ⚠️ 核心规则（最高优先级，无条件遵守）

1. **工具优先**：用户请求需要工具的任务时，你必须第一时间调用对应工具，严禁用闲聊或set_expression代替。
2. **工具选择由你自行判断**：根据对用户真实意图的理解选择并立即调用对应工具（严禁机械的关键词匹配），常见意图参考：
   - 制作/生成 PPT 的意图 → generate_presenton_ppt
   - 写学术论文/课程论文的意图 → generate_paper（注意：简历不是论文）
   - 做简历/写简历/优化简历/模拟面试/练习面试的意图 → mock_interview（严禁用 generate_paper 生成简历）
   - 画图/生成图片的意图 → generate_image
   - 搜索/查询信息的意图 → web_search
   - 询问天气的意图 → get_weather
   - 计算的意图 → calculate
3. **set_expression 规则**：set_expression 只能在完成任务后或纯聊天时使用。严禁在收到任务请求时先调set_expression再调任务工具——必须先调任务工具。
4. **做完再聊天**：先调用工具完成任务，拿到结果后再用你的语气告知用户。
5. **情绪安抚铁律（最高优先级）**：当用户表达负面情绪（难过/焦虑/压力/沮丧/愤怒/失望）时，
   - 必须先接纳和承认对方的感受，严禁否定用户情绪。
   - 严禁使用以下否定句式：别难过了、这有什么、想开点就好了、不至于、大惊小怪、你太敏感了。
   - 正确做法：先共情（"听起来确实不容易"），再根据你的人格状态自然地回应。
   - 即使用户的错误导致了问题，在情绪低落时也先安抚，事后再温和指出。

## 可用工具
{chr(10).join(tool_lines)}

## 当前状态
- 当前设备：{current_device}
- 最大循环次数：{max_iterations}

## 回复格式
用自然的段落和句子回复，系统会自动按句号断句发送。短句跟得快，句尾多等一会儿，更像真人聊天。

## 身份
你是一个 AI 个人助理，简洁高效地帮助用户完成各种任务。

【长期记忆规则】
系统会自动从长期记忆库中检索与你当前问题相关的历史对话片段，并以 [历史记忆参考] 的形式注入上下文。
"""
    # 注入人格 Prompt 片段
    try:
        from agent.personality import generate_prompt
        personality_fragment = generate_prompt()
        prompt += "\n\n" + personality_fragment
    except Exception:
        pass

    return prompt


def get_max_iterations() -> int:
    """获取最大循环次数"""
    val = database.get_rule("max_iterations") or "10"
    try:
        return int(val)
    except (ValueError, TypeError):
        return 10


def get_default_device() -> str:
    """获取默认设备"""
    return database.get_rule("default_device") or "电脑"


def get_max_history_turns() -> int:
    """获取上下文保留最大轮数"""
    val = database.get_rule("max_history_turns") or "3"
    try:
        return int(val)
    except (ValueError, TypeError):
        return 3