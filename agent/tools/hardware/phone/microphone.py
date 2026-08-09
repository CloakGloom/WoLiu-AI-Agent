"""手机端麦克风"""

from agent.tools.hardware.base import BaseMicrophone


class PhoneMicrophone(BaseMicrophone):
    def record(self, duration: int) -> str:
        return f"[模拟] 已在手机上调用麦克风录音 {duration} 秒"