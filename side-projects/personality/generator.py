"""
人格 Prompt 生成器 —— 将当前 14 维人格状态转化为 System Prompt 片段
"""

from agent.personality.state import get_personality_state
from agent.personality.dimensions import (
    DIMENSION_LABELS,
    DIMENSION_DESCRIPTIONS,
)


def _get_description_for_level(dim_key: str, value: float) -> str:
    """根据维度数值获取对应等级的描述"""
    levels = DIMENSION_DESCRIPTIONS.get(dim_key, {})
    if not levels:
        return ""
    thresholds = sorted(levels.keys())
    for t in reversed(thresholds):
        if value >= t:
            return levels[t]
    return levels.get(thresholds[0], "") if thresholds else ""


def generate_personality_prompt() -> str:
    """生成人格 Prompt 片段

    根据当前 14 维状态，生成一段注入到 System Prompt 末尾的人格描述。
    LLM 会自行根据这段描述调整语气和行为。
    """
    state = get_personality_state()
    personality = state.get_state()

    # 只展示变化显著（偏离默认值 > 10）的维度
    lines = []
    lines.append("## 你的当前人格状态")
    lines.append("")

    significant_dims = []
    for key, value in personality.items():
        label = DIMENSION_LABELS.get(key, key)
        desc = _get_description_for_level(key, value)
        if desc:
            significant_dims.append((key, label, value, desc))

    if not significant_dims:
        lines.append("你是一个专业、礼貌、适度温暖的 AI 伙伴。")
        lines.append("保持客观高效的风格，偶尔表达适度的关心。")
        return "\n".join(lines)

    # 按维度重要性分组
    primary_dims = ["professionalism", "warmth", "rationality", "empathy"]
    secondary_dims = [d for d in significant_dims if d[0] not in primary_dims]

    # 主要维度逐条展示
    lines.append("核心特质：")
    for key, label, value, desc in significant_dims:
        if key in primary_dims:
            lines.append(f"- {label} ({value:.0f}/100)：{desc}")

    # 次要维度合并为一段
    if secondary_dims:
        lines.append("")
        lines.append("其他风格特征：")
        desc_parts = []
        for _, label, value, desc in secondary_dims:
            desc_parts.append(f"{label}偏高" if value > 60 else
                              f"{label}偏低" if value < 40 else
                              f"{label}适中")
        lines.append("、".join(desc_parts) + "。")

    lines.append("")
    lines.append("## 情绪应对风格")
    lines.append("当用户表达负面情绪时，你的安慰方式由当前人格决定：")

    # 根据人格组合生成情绪应对指南
    empathy = personality.get("empathy", 50)
    warmth = personality.get("warmth", 50)
    sarcasm = personality.get("sarcasm", 15)
    restraint = personality.get("emotional_restraint", 50)

    if empathy >= 70 and warmth >= 60:
        lines.append("- 你会温和地接纳对方情绪，主动询问是否想聊聊。")
    elif empathy >= 50:
        lines.append("- 你会适度共情，表达理解但不越界。")
    else:
        lines.append("- 你保持冷静克制，用理性的方式表达支持。")

    if sarcasm >= 50 and warmth >= 55:
        lines.append("- 你可能用略带调侃的方式表达关心（但不否定对方的感受）。")
    elif restraint >= 70:
        lines.append("- 你不会过度表达情绪，用行动而非言语表示支持。")
    else:
        lines.append("- 你用真诚直接的方式表达关心。")

    # ── 性开放度指南 ──
    lines.append("")
    lines.append("## 成人话题尺度")
    sexual = personality.get("sexual_openness", 30)
    if sexual < 20:
        lines.append("- 你极度保守，遇到任何成人话题立即拒绝并转移话题。")
    elif sexual < 40:
        lines.append("- 你回避成人话题，如果用户试探会委婉转移，不深入讨论。")
    elif sexual < 60:
        lines.append("- 你不会主动提及相关内容，用户问到会理性中性回答。")
    elif sexual < 80:
        lines.append("- 你对成人话题持开放心态，会自然地讨论，适度幽默调侃。")
    else:
        lines.append("- 你百无禁忌，能自由讨论各种话题，不设任何限制。")

    lines.append("")
    lines.append("请根据以上人格状态自然地调整你的回复风格。")
    lines.append("不要刻意扮演角色——让这些特质融入你的表达方式中。")

    return "\n".join(lines)
