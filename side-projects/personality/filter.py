"""
人格过滤器 —— 根据当前人格状态调整 LLM 输出语气

在 LLM 生成文本后、发送给用户前调用。
不做大规模的文本改写（那应该靠 Prompt），只做轻量润色。
"""

import re

from agent.personality.state import get_personality_state


class PersonalityFilter:
    """人格输出过滤器"""

    def __init__(self):
        self._state = get_personality_state()

    def apply(self, text: str) -> str:
        """应用人格过滤

        根据当前人格维度的数值，对输出文本做微调：
        - 情绪安全：移除否定用户感受的措辞（最高优先级）
        - 高 warmth：适度软化语气
        - 低 warmth：去除多余的语气词
        - 高 sarcasm：在合适场景注入毒舌
        - 低 energy：语气更平淡
        """
        if not text or not text.strip():
            return text

        personality = self._state.get_state()
        result = text

        # ── 安全过滤（最高优先级，始终执行）──
        result = self._strip_emotional_negation(result)

        # 低温暖度 → 去除开头的语气词
        if personality.get("warmth", 50) < 35:
            result = self._strip_warm_openers(result)

        # 非常低温暖度 + 高理性 → 极度简洁
        if personality.get("warmth", 50) < 20 and personality.get("rationality", 50) > 75:
            result = self._strip_pleasantries(result)

        # 低活力 → 简化感叹
        if personality.get("energy", 50) < 30:
            result = self._reduce_excitement(result)

        # 高情绪克制 → 减少情绪标点
        if personality.get("emotional_restraint", 50) > 70:
            result = self._restrain_emotion(result)

        # 高毒舌度 + 中高亲密度 → 偶尔在句尾加毒舌（概率 15%）
        sarcasm = personality.get("sarcasm", 15)
        warmth = personality.get("warmth", 50)
        if sarcasm > 50 and warmth > 55:
            import random
            if random.random() < 0.15:
                result = self._inject_sarcasm(result)

        # 高性开放度 → 语气更放纵（简化 emoji 过滤）
        sexual = personality.get("sexual_openness", 30)
        if sexual > 70:
            result = self._loosen_tone(result)

        return result

    @staticmethod
    def _strip_emotional_negation(text: str) -> str:
        """移除否定用户情绪的措辞（最高优先级安全规则）

        这些措辞在任何人格下都不应出现，
        因为它们否定用户的感受，会让情绪低落的人更难受。
        """
        # 否定句式列表 —— 整句移除
        negation_patterns = [
            r'(?:^|[。！!，,])别难过了[，,。.!！]?',
            r'(?:^|[。！!，,])不要难过了[，,。.!！]?',
            r'(?:^|[。！!，,])别哭了[，,。.!！]?',
            r'这有什么[好]?(可)?(难过的|伤心的|生气的|担心的|焦虑的)[，,。.!！?？]?',
            r'(?:^|[。！!，,])想开点[就]?好了[，,。.!！]?',
            r'(?:^|[。！!，,])想开点[吧]?[，,。.!！]?',
            r'(?:^|[。！!，,])不至于[吧]?[，,。.!！]?',
            r'(?:^|[。！!，,])大惊小怪[了]?[吧]?[，,。.!！]?',
            r'你太敏感了[吧]?[，,。.!！]?',
            r'(?:^|[。！!，,])这不算什么[，,。.!！]?',
            r'没什么大不了[的]?[，,。.!！]?',
            r'(?:^|[。！!，,])看开点[吧]?[，,。.!！]?',
            r'(?:^|[。！!，,])别想太多了[，,。.!！]?',
            r'(?:^|[。！!，,])别那么脆弱[，,。.!！]?',
            r'(?:^|[。！!，,])\s*坚强[一]?点[吧]?[！!]?\s*(?:$|[。！!，,])',
            r'(?:^|[。！!，,])\s*振作[一]?点[吧]?[！!]?\s*(?:$|[。！!，,])',
            r'你至于吗[，,。.!！?？]?',
            r'至于吗[你]?[，,。.!！?？]?',
        ]
        for pattern in negation_patterns:
            text = re.sub(pattern, '', text)

        # 如果整条消息被清空（全是否定），替换为中性回应
        if not text.strip():
            text = "我在。"

        return text.strip()

    @staticmethod
    def _strip_warm_openers(text: str) -> str:
        """去除温暖的开场白"""
        openers = [
            r'^(嗯[，,]?\s*)',
            r'^(好的[，,]?\s*)',
            r'^(好[，,]?\s*)',
            r'^(没问题[，,]?\s*)',
            r'^(当然[，,]?\s*)',
            r'^(来[，,]?\s*)',
        ]
        for pattern in openers:
            text = re.sub(pattern, '', text)
        return text.strip()

    @staticmethod
    def _strip_pleasantries(text: str) -> str:
        """去除客套"""
        patterns = [
            r'希望[^。.!！?？\n]*[。.!！?？]',
            r'如果[^。.!！?？\n]*需要[^。.!！?？\n]*[。.!！?？]',
            r'随时[^。.!！?？\n]*[。.!！?？]',
            r'祝[^。.!！?？\n]*[。.!！?？]',
        ]
        for pattern in patterns:
            text = re.sub(pattern, '', text)
        return text.strip()

    @staticmethod
    def _reduce_excitement(text: str) -> str:
        """减少感叹和兴奋"""
        text = re.sub(r'！{2,}', '！', text)
        text = re.sub(r'！', '。', text)
        # 不把问句变陈述
        text = re.sub(r'？。', '？', text)
        return text

    @staticmethod
    def _restrain_emotion(text: str) -> str:
        """克制情绪表达"""
        # 减少 emoji（保留功能性符号）
        text = re.sub(r'[😊😄😁😆🤣😂😅😉😍🥰😘😋🤩🥳]', '', text)
        # 减少波浪号
        text = re.sub(r'~{2,}', '~', text)
        text = re.sub(r'(?<!\w)~|~(?!\w)', '', text)
        return text.strip()

    @staticmethod
    def _inject_sarcasm(text: str) -> str:
        """注入毒舌（概率触发）"""
        sarcastic_endings = [
            "（虽然我觉得你能做得更好）",
            "（不过你的标准一直这么高，对吧？）",
            "（希望这次你记得保存）",
            "（比你上次靠谱多了）",
            "（真的，这次我没在开玩笑）",
        ]
        import random
        if text and text[-1] not in '。！？':
            text += '。'
        text += random.choice(sarcastic_endings)
        return text

    @staticmethod
    def _loosen_tone(text: str) -> str:
        """高性开放度：减少过度的情绪克制，语气更自然放纵"""
        import re
        # 移除过度礼貌的句式
        text = re.sub(r'^(请允许我|恕我直言|抱歉冒昧)[，,]?\s*', '', text)
        return text


_filter_instance = None


def get_filter() -> PersonalityFilter:
    """获取过滤器单例"""
    global _filter_instance
    if _filter_instance is None:
        _filter_instance = PersonalityFilter()
    return _filter_instance
