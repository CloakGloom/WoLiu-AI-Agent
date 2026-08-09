"""电脑端扬声器"""

from agent.tools.hardware.base import BaseSpeaker


class PcSpeaker(BaseSpeaker):
    def play(self, text: str) -> str:
        return f"[模拟] 已在电脑上通过扬声器播放：{text}"