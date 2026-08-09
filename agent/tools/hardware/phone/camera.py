"""手机端摄像头"""

from agent.tools.hardware.base import BaseCamera


class PhoneCamera(BaseCamera):
    def capture(self) -> str:
        return "[模拟] 已在手机上调用摄像头拍照"