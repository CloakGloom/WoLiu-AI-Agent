"""手机端扬声器"""

from agent.tools.hardware.base import BaseSpeaker


class PhoneSpeaker(BaseSpeaker):
    def play(self, text: str) -> str:
        return f"[模拟] 已在手机上通过扬声器播放：{text}"