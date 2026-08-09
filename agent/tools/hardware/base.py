"""硬件工具抽象基类 —— 定义 pc/ 和 phone/ 的接口规范"""

from abc import ABC, abstractmethod


class BaseMicrophone(ABC):
    """麦克风抽象基类"""

    @abstractmethod
    def record(self, duration: int) -> str:
        """录音指定时长（秒），返回结果文本"""
        pass


class BaseSpeaker(ABC):
    """扬声器抽象基类"""

    @abstractmethod
    def play(self, text: str) -> str:
        """播放文本，返回结果文本"""
        pass


class BaseCamera(ABC):
    """摄像头抽象基类"""

    @abstractmethod
    def capture(self) -> str:
        """拍照，返回结果文本"""
        pass