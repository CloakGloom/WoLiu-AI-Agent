"""
独立天气查询工具 —— 与 Agent 解耦的外部工具
"""

import json
import os

# 天气数据文件路径
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEATHER_DATA_FILE = os.path.join(_BASE_DIR, "weather_data.json")

# 默认天气数据
_DEFAULT_WEATHER = {
    "北京": {"temp": 25, "weather": "晴", "humidity": 45, "wind": "北风 3级"},
    "上海": {"temp": 28, "weather": "多云", "humidity": 65, "wind": "东南风 2级"},
    "深圳": {"temp": 30, "weather": "阵雨", "humidity": 80, "wind": "南风 4级"},
    "广州": {"temp": 31, "weather": "雷阵雨", "humidity": 85, "wind": "南风 3级"},
    "杭州": {"temp": 26, "weather": "阴", "humidity": 70, "wind": "东风 2级"},
    "成都": {"temp": 24, "weather": "小雨", "humidity": 75, "wind": "北风 1级"},
    "武汉": {"temp": 29, "weather": "晴转多云", "humidity": 60, "wind": "南风 3级"},
    "西安": {"temp": 27, "weather": "晴", "humidity": 40, "wind": "东风 2级"},
    "南京": {"temp": 27, "weather": "多云", "humidity": 55, "wind": "东风 3级"},
    "重庆": {"temp": 30, "weather": "阴转小雨", "humidity": 78, "wind": "北风 2级"},
}


def load_weather_data() -> dict:
    """加载天气数据（优先从文件读取）"""
    if os.path.exists(WEATHER_DATA_FILE):
        with open(WEATHER_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return _DEFAULT_WEATHER


def save_weather_data(data: dict):
    """保存天气数据到文件"""
    with open(WEATHER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_weather(city: str) -> str:
    """查询城市天气"""
    data = load_weather_data()
    if city in data:
        w = data[city]
        return f"{city}天气：{w['weather']}，温度 {w['temp']}°C，湿度 {w['humidity']}%，{w['wind']}"
    return f"暂无 {city} 的天气数据"


def update_weather(city: str, temp: int, weather: str, humidity: int, wind: str):
    """更新/添加城市天气数据"""
    data = load_weather_data()
    data[city] = {
        "temp": temp,
        "weather": weather,
        "humidity": humidity,
        "wind": wind,
    }
    save_weather_data(data)
    return f"已更新 {city} 的天气数据"


def list_cities() -> list:
    """列出所有支持的城市"""
    return list(load_weather_data().keys())


if __name__ == "__main__":
    # 命令行测试
    import sys
    if len(sys.argv) > 1:
        city = sys.argv[1]
        print(get_weather(city))
    else:
        print("支持的城市：", ", ".join(list_cities()))