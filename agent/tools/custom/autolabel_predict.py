"""
模型推理工具 —— 通过子进程调用 autolabel-dock CLI（规避 AGPL import）
"""
import sys, os, json, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _call_cli(command: str, args: dict, timeout: int = 300) -> str:
    cli = os.path.join(ROOT, "scripts", "autolabel_cli.py")
    if not os.path.isfile(cli):
        return f"❌ autolabel CLI 未找到: {cli}"
    try:
        r = subprocess.run(
            [sys.executable, cli, "--command", command, "--args", json.dumps(args, ensure_ascii=False)],
            cwd=ROOT, capture_output=True, text=True, timeout=timeout, encoding="utf-8"
        )
        if r.returncode != 0 or not r.stdout.strip():
            stderr_detail = r.stderr.strip()[-500:] or "(无错误输出)"
            return f"❌ autolabel 子进程异常退出 (code={r.returncode})\n{stderr_detail}"
        result = json.loads(r.stdout.strip())
        if result.get("status") == "error":
            return f"❌ {result.get('error', '未知错误')}"
        return result.get("data", "")
    except subprocess.TimeoutExpired:
        return f"❌ autolabel 操作超时（{timeout}秒）"
    except json.JSONDecodeError:
        return f"❌ autolabel 返回异常: {r.stdout[:300] if r.stdout else '(空)'}"
    except Exception as e:
        return f"❌ autolabel 调用失败: {e}"


SCHEMA = {
    "type": "function",
    "tag": "IoT/图像",
    "function": {
        "name": "yolo_predict",
        "description": "使用已训练的 YOLO 模型对新图片进行目标检测/分类。",
        "parameters": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "图片路径（文件或目录），必填"},
                "model_path": {"type": "string", "description": "模型 .pt 文件的绝对路径，必填"},
                "conf": {"type": "number", "description": "置信度阈值，默认 0.25"},
                "iou": {"type": "number", "description": "IOU 阈值，默认 0.45"},
                "class_filter": {"type": "string", "description": "类别过滤，可选"}
            },
            "required": ["image_path", "model_path"]
        }
    }
}


def execute(arguments: dict) -> str:
    return _call_cli("predict", arguments)
