"""天气查询工具（uapis.cn 国内天气接口，支持行政区划代码）"""

import requests

from agent.config import weather_api_url as _cfg_weather
API_URL = _cfg_weather()

SCHEMA = {
    "type": "function",
    "tag": "系统",
    "function": {
        "name": "get_weather",
        "description": "查询指定城市的实时天气和预报信息。中国城市必须使用6位行政区划代码（adcode），如：350100（福州）、350200（厦门）。",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "中国城市必须使用6位行政区划代码，如350100=福州、350200=厦门、350500=泉州、350600=漳州。非中国城市可用英文名。",
                }
            },
            "required": ["city"],
        },
    },
}

# 行政区划代码 → 城市名
_CITY_CODES = {
    "CN": "中国",
    "350000": "福建省",
    "350100": "福州市",
    "350200": "厦门市",
    "350300": "莆田市",
    "350400": "三明市",
    "350500": "泉州市",
    "350600": "漳州市",
    "350700": "南平市",
    "350800": "龙岩市",
    "350900": "宁德市",
}


def execute(arguments: dict) -> str:
    city = arguments.get("city", "").strip()
    if not city:
        return "请提供要查询的城市名称或行政区划代码"

    # 判断输入类型
    if city in _CITY_CODES:
        if city in ("CN", "350000"):
            return f"「{city}」是{_CITY_CODES[city]}的代码，请输入具体城市代码，如：350100（福州）、350200（厦门）"
        adcode = city
        city_name = _CITY_CODES[city]
    elif city.isdigit() and len(city) == 6:
        adcode = city
        city_name = city
    else:
        adcode = None
        city_name = city

    try:
        params = {}
        if adcode:
            params["adcode"] = adcode
        else:
            params["city"] = city_name

        resp = requests.get(API_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        # API 返回格式是扁平结构，非 {code, data} 包装
        if "city" not in data and "weather" not in data:
            return f"天气查询失败：{data}"

        weather = data.get("weather", "未知")
        temp = data.get("temperature", "?")
        feels_like = data.get("feels_like")
        humidity = data.get("humidity")
        wind_dir = data.get("wind_direction", "")
        wind_power = data.get("wind_power", "")
        visibility = data.get("visibility")
        pressure = data.get("pressure")
        uv = data.get("uv")
        aqi = data.get("aqi")
        aqi_category = data.get("aqi_category", "")
        temp_max = data.get("temp_max")
        temp_min = data.get("temp_min")
        report_time = data.get("report_time", "")

        city_display = data.get("city", city_name) or city_name
        province = data.get("province", "")

        title = f"{province}{city_display}" if province else city_display
        title += " 实时天气"
        if adcode:
            title += f" [代码: {adcode}]"

        lines = [title]
        lines.append(f"🌤 天气：{weather}")
        temp_line = f"🌡 温度：{temp}°C"
        if feels_like is not None:
            temp_line += f"（体感 {feels_like}°C）"
        if temp_max is not None and temp_min is not None:
            temp_line += f"  |  最高 {temp_max}°C / 最低 {temp_min}°C"
        lines.append(temp_line)
        if humidity is not None:
            lines.append(f"💧 湿度：{humidity}%")
        if wind_dir:
            lines.append(f"🌬 风力：{wind_dir} {wind_power}")
        if visibility is not None:
            lines.append(f"👁 能见度：{visibility}km")
        if pressure is not None:
            lines.append(f"🌀 气压：{pressure} hPa")
        if uv is not None:
            lines.append(f"☀ 紫外线指数：{uv}")
        if aqi is not None:
            lines.append(f"🍃 空气质量：AQI {aqi}（{aqi_category}）")
        if report_time:
            lines.append(f"📡 {report_time}")

        # 多天预报
        forecast = data.get("forecast", [])
        if forecast:
            lines.append("\n📅 未来预报：")
            for day in forecast[:5]:
                date = day.get("date", "")
                week = day.get("week", "")
                day_weather = day.get("weather_day", "?")
                night_weather = day.get("weather_night", "?")
                high = day.get("temp_max", "?")
                low = day.get("temp_min", "?")
                wind_dir_d = day.get("wind_dir_day", "")
                wind_scale_d = day.get("wind_scale_day", "")
                sunrise = day.get("sunrise", "")
                sunset = day.get("sunset", "")
                line = f"  {date} {week}  {day_weather}转{night_weather}  {low}~{high}°C"
                if wind_dir_d:
                    line += f"  {wind_dir_d}{wind_scale_d}"
                if sunrise and sunset:
                    line += f"  🌅{sunrise} 🌇{sunset}"
                lines.append(line)

        return "\n".join(lines)

    except requests.exceptions.Timeout:
        return f"查询 {city_name} 天气超时，请稍后重试"
    except requests.exceptions.ConnectionError:
        return "无法连接天气服务，请检查网络"
    except Exception as e:
        return f"查询天气时出错：{e}"