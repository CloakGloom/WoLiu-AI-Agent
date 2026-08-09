"""
健康提醒 —— 定时喝水 / 吃饭提醒，人格驱动动态文案

每次提醒时根据 15 维人格 + 拖延次数生成不同的文案。
"""
import time, threading, json, os
from agent.personality.state import get_personality_state

_WS_PUSH = None
_lock = threading.Lock()

# 状态：{water_last_ok, water_deferred, water_last_fired, meal_last_ok, meal_deferred, meal_last_fired}
_state = {"water_last_ok": time.time(), "water_deferred": 0, "water_last_fired": 0,
          "meal_last_ok": time.time(), "meal_deferred": 0, "meal_last_fired": 0}

def set_push(cb):
    global _WS_PUSH; _WS_PUSH = cb

def _push(data: dict):
    if _WS_PUSH:
        try: _WS_PUSH(data)
        except Exception: pass

# ── 持久化配置 ──
_CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "wellness_config.json")

_DEFAULT_CONFIG = {
    "water_interval": 30,        # 喝水间隔（分钟）
    "water_amount": 300,         # 每次建议饮水量（ml）
    "meal_times": [13, 19],      # 吃饭提醒时间（小时）
}

def _load_config() -> dict:
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        for k, v in _DEFAULT_CONFIG.items():
            if k not in cfg:
                cfg[k] = v
        return cfg
    except Exception:
        return dict(_DEFAULT_CONFIG)

def _save_config(cfg: dict):
    os.makedirs(os.path.dirname(_CONFIG_FILE), exist_ok=True)
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def get_config() -> dict:
    return _load_config()

def update_config(data: dict) -> dict:
    """部分更新配置，返回新配置"""
    cfg = _load_config()
    if "water_interval" in data:
        cfg["water_interval"] = max(5, min(180, int(data["water_interval"])))
    if "water_amount" in data:
        cfg["water_amount"] = max(100, min(2000, int(data["water_amount"])))
    if "meal_times" in data:
        times = data["meal_times"]
        if isinstance(times, list) and all(isinstance(t, (int, float)) for t in times):
            cfg["meal_times"] = [max(0, min(23, int(t))) for t in times]
    _save_config(cfg)
    return cfg


def _push(data: dict):
    if _WS_PUSH:
        try:
            _WS_PUSH(data)
        except Exception:
            pass


def _make_water_message(personality: dict, deferred: int, amount_ml: int = None) -> str:
    """调用 LLM 生成动态提醒文案"""
    return _llm_generate(_build_water_prompt(deferred, amount_ml, personality))


def _build_water_prompt(deferred: int, amount_ml: int, pers: dict) -> str:
    sarc = pers.get("sarcasm", 15); warmth = pers.get("warmth", 55)
    humor = pers.get("humor", 40); prof = pers.get("professionalism", 80)
    tone = "调皮幽默" if humor > 65 else "专业正式" if prof > 80 else "温暖体贴" if warmth > 70 else "毒舌吐槽" if sarc > 60 else "日常友好"

    parts = [
        f"你需要生成一段15-30字的喝水提醒文案。",
        f"建议饮水量：{amount_ml}ml。已催第{deferred+1}次。",
        f"你的口吻：{tone}。"
    ]
    if sarc > 60 and deferred >= 2:
        parts.append("用毒舌方式吐槽用户还不喝水。")
    if warmth > 70 and deferred >= 3:
        parts.append("表达你的心疼和担心。")
    if humor > 65:
        parts.append("加点搞笑夸张的比喻。")
    parts.append("只输出文案本身，不要引号不要前缀。")
    return " ".join(parts)


def _make_meal_message(personality: dict, deferred: int) -> str:
    return _llm_generate(_build_meal_prompt(deferred, personality))


def _build_meal_prompt(deferred: int, pers: dict) -> str:
    sarc = pers.get("sarcasm", 15); warmth = pers.get("warmth", 55)
    humor = pers.get("humor", 40); prof = pers.get("professionalism", 80)
    tone = "调皮幽默" if humor > 65 else "专业正式" if prof > 80 else "温暖体贴" if warmth > 70 else "毒舌吐槽" if sarc > 60 else "日常友好"

    parts = [
        f"你需要生成一段15-30字的吃饭提醒文案。",
        f"已催第{deferred+1}次。你的口吻：{tone}。"
    ]
    if deferred >= 2:
        parts.append("适当抱怨催促，但不要真正生气。")
    parts.append("只输出文案本身，不要引号不要前缀。")
    return " ".join(parts)


def _llm_generate(prompt: str) -> str:
    """调用 LLM API 生成文案，失败则回退到本地模板"""
    try:
        from config import API_KEY, API_BASE_URL, MODEL_NAME
        from openai import OpenAI
        client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=80, temperature=0.9,
        )
        text = resp.choices[0].message.content.strip()
        return text if text else _fallback("water", 0, None)
    except Exception:
        return _fallback("water", 0, None)


def _fallback(kind: str, deferred: int, amount_ml: int = None) -> str:
    """LLM 不可用时的回退文案"""
    amt = f"{amount_ml}ml" if amount_ml else "水"
    if kind == "meal":
        return "该吃饭啦，身体是革命的本钱！" if deferred == 0 else f"第{deferred+1}次喊你吃饭了，快去！"
    return f"喝{amt}休息下吧~" if deferred == 0 else f"第{deferred+1}次提醒：快喝{amt}！"


def _make_meal_message(personality: dict, deferred: int) -> str:
    """调用 LLM 生成动态提醒文案"""
    return _llm_generate(_build_meal_prompt(deferred, personality))


def _generate_message(kind: str, deferred: int, water_amount: int = None) -> str:
    try:
        ps = get_personality_state()
        personality = ps.get_state() if ps._loaded else {}
    except Exception:
        personality = {}
    if kind == "meal":
        return _make_meal_message(personality, deferred)
    return _make_water_message(personality, deferred, water_amount)


# ── 调度器 ──

_timer = None


def _check():
    now = time.time()
    hour = time.localtime(now).tm_hour
    cfg = _load_config()
    with _lock:
        s = _state
        # 喝水：距上次确认已过配置的间隔，且距上次触发 > 5 分钟
        water_sec = cfg["water_interval"] * 60
        water_amount = cfg["water_amount"]
        if (now - s["water_last_ok"] > water_sec and
                now - s["water_last_fired"] > 300):
            s["water_last_fired"] = now
            msg = _generate_message("water", s["water_deferred"], water_amount)
            _push({"type": "wellness_reminder", "kind": "water", "message": msg,
                    "deferred": s["water_deferred"], "amount_ml": water_amount})

        # 吃饭：配置的小时，且距上次触发 > 30 分钟
        meal_hours = cfg["meal_times"]
        if (hour in meal_hours and
                now - s["meal_last_fired"] > 1800):
            s["meal_last_fired"] = now
            msg = _generate_message("meal", s["meal_deferred"], None)
            _push({"type": "wellness_reminder", "kind": "meal", "message": msg,
                    "deferred": s["meal_deferred"]})


def start_scheduler():
    global _timer
    def _loop():
        while True:
            time.sleep(30)
            try:
                _check()
            except Exception:
                pass
    _timer = threading.Thread(target=_loop, daemon=True)
    _timer.start()
    print("[健康提醒] 调度器已启动", flush=True)


def record_response(kind: str, action: str) -> dict:
    """
    kind: 'water' | 'meal'
    action: 'done'（喝了/吃完了）| 'not_yet'（还没喝/一会吃）
    """
    with _lock:
        s = _state
        if kind == "water":
            if action == "done":
                s["water_deferred"] = 0
                s["water_last_ok"] = time.time()
            else:
                s["water_deferred"] += 1
                s["water_last_ok"] = time.time() - 1200  # 10 分钟后再提醒
        elif kind == "meal":
            if action == "done":
                s["meal_deferred"] = 0
                s["meal_last_ok"] = time.time()
            else:
                s["meal_deferred"] += 1
                s["meal_last_ok"] = time.time() - 1200

    # 如果选了 not_yet，生成抱怨
    if action == "not_yet":
        complaint = _generate_message(kind, s[f"{kind}_deferred"])
        return {"personality_message": complaint}
    return {"personality_message": ""}
