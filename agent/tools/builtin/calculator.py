"""数学计算工具"""

import math

SCHEMA = {
    "type": "function",
    "tag": "系统",
    "function": {
        "name": "calculate",
        "description": "执行数学计算，支持加减乘除、幂运算、三角函数等",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "数学表达式，如：2+3*4、sqrt(16)、sin(pi/2)",
                }
            },
            "required": ["expression"],
        },
    },
}

_SAFE_GLOBALS = {
    "__builtins__": {},
    "abs": abs, "round": round,
    "max": max, "min": min, "sum": sum,
    "pow": pow, "sqrt": math.sqrt,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "pi": math.pi, "e": math.e,
    "log": math.log, "log10": math.log10, "log2": math.log2,
    "ceil": math.ceil, "floor": math.floor,
}

_ALLOWED_CHARS = set("0123456789+-*/.() eEpPiImnafstqrlodcgh")


def execute(arguments: dict) -> str:
    expression = arguments.get("expression", "")
    safe = all(c in _ALLOWED_CHARS for c in expression.lower())
    if not safe:
        return "表达式包含不允许的字符，仅支持基本数学运算"
    try:
        val = eval(expression, _SAFE_GLOBALS, {})
        return f"计算结果：{expression} = {val}"
    except Exception as e:
        return f"计算错误：{e}"