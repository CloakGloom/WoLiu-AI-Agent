"""电脑端摄像头"""

from agent.tools.hardware.base import BaseCamera


class PcCamera(BaseCamera):
    def capture(self) -> str:
        return "[模拟] 已在电脑上调用摄像头拍照"