"""电脑端麦克风"""

from agent.tools.hardware.base import BaseMicrophone


class PcMicrophone(BaseMicrophone):
    def record(self, duration: int) -> str:
        return f"[模拟] 已在电脑上调用麦克风录音 {duration} 秒"