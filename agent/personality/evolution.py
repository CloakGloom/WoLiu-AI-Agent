"""
演化引擎 —— 用户交互事件 → 维度变化计算
"""

import time
from collections import defaultdict
from datetime import datetime

from agent.personality.dimensions import (
    DIMENSION_KEYS,
    EVOLUTION_RULES,
    INTERACTION_PATTERNS,
    MAX_DAILY_DELTA,
)
from agent.personality.state import get_personality_state


class EvolutionEngine:
    """人格演化引擎"""

    def __init__(self):
        self._state = get_personality_state()
        self._daily_accumulated: dict = defaultdict(float)
        self._last_reset_date: str = ""

    def _reset_daily_if_needed(self):
        """跨天重置每日累计"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._last_reset_date:
            self._daily_accumulated.clear()
            self._last_reset_date = today

    def analyze_interaction(self, user_msg: str) -> list[str]:
        """分析用户消息，返回匹配的交互类型列表

        规则：检测关键词，按匹配数量排序，取最可能的 1-2 个类型。
        """
        if not user_msg or not user_msg.strip():
            return ["quick_command"]

        msg = user_msg.strip()
        scores = {}

        for event_type, patterns in INTERACTION_PATTERNS.items():
            if not patterns:
                continue
            matched = sum(1 for p in patterns if p in msg)
            if matched > 0:
                scores[event_type] = matched

        # 短消息 + 无匹配 → 快速指令
        if not scores:
            if len(msg) < 10:
                return ["quick_command"]
            return []

        # 按匹配数排序，返回最高的
        sorted_types = sorted(scores.items(), key=lambda x: -x[1])
        result = [sorted_types[0][0]]
        if len(sorted_types) > 1 and sorted_types[1][1] >= sorted_types[0][1] * 0.7:
            result.append(sorted_types[1][0])

        return result

    def analyze_conversation(self, user_msg: str, assistant_msg: str,
                             turn_count: int = 0) -> list[str]:
        """综合分析对话（用户消息 + AI 回复），返回交互类型"""
        types = self.analyze_interaction(user_msg)

        # 额外规则
        # 长时间工作：turn_count > 5 且对话仍在继续
        if turn_count > 5:
            if "long_work_session" not in types:
                types.append("long_work_session")

        # 回复包含幽默元素 → 用户接受了 jokes
        has_humor = any(w in assistant_msg for w in
                        ["😂", "哈哈", "笑", "幽默", "有趣", "梗"])
        if has_humor and "joke_response" in types:
            pass  # 已匹配

        return types

    def record_interaction(self, event_types: list[str],
                           session_id: str = "") -> dict:
        """记录一次交互，返回应用的维度变化"""
        if not event_types:
            return {}

        self._reset_daily_if_needed()
        deltas = {}

        for etype in event_types:
            if etype not in EVOLUTION_RULES:
                continue
            for dim, delta in EVOLUTION_RULES[etype].items():
                if dim not in DIMENSION_KEYS:
                    continue
                deltas[dim] = round(deltas.get(dim, 0) + delta, 2)

        # 每日上限检查
        capped_deltas = {}
        for dim, delta in deltas.items():
            accumulated = self._daily_accumulated.get(dim, 0)
            remaining = MAX_DAILY_DELTA - accumulated
            if remaining <= 0:
                continue
            capped = min(abs(delta), remaining) * (1 if delta > 0 else -1)
            if abs(capped) < 0.01:
                continue
            capped_deltas[dim] = round(capped, 2)
            self._daily_accumulated[dim] = round(accumulated + abs(capped), 2)

        if capped_deltas:
            reason = f"交互类型: {', '.join(event_types)}"
            self._state.apply_deltas(capped_deltas, reason, session_id)

        return capped_deltas

    def process_turn(self, user_msg: str, assistant_msg: str = "",
                     turn_count: int = 0, session_id: str = "") -> dict:
        """处理一轮对话的完整流程：分析 → 计算 → 应用

        Returns:
            dict: 本次应用的维度变化
        """
        event_types = self.analyze_conversation(user_msg, assistant_msg, turn_count)
        return self.record_interaction(event_types, session_id)


_engine_instance = None


def get_evolution_engine() -> EvolutionEngine:
    """获取演化引擎单例"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = EvolutionEngine()
    return _engine_instance
