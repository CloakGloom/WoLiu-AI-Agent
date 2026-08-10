"""
模型训练工具 —— 通过子进程调用 autolabel-dock CLI（规避 AGPL import）
"""
import sys, os, json, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _call_cli(command: str, args: dict, timeout: int = 3600) -> str:
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
        "name": "yolo_train",
        "description": "训练 YOLO 模型。需要项目已创建且已标注足够的图片（至少 10-20 张已确认）。",
        "parameters": {
            "type": "object",
            "properties": {
                "project_dir": {"type": "string", "description": "项目目录绝对路径"},
                "base_model": {"type": "string", "description": "基础模型，默认 yolov8n.pt"},
                "epochs": {"type": "integer", "description": "训练轮数，默认 100"},
                "batch": {"type": "integer", "description": "批大小，默认 16"},
                "imgsz": {"type": "integer", "description": "图片尺寸，默认 640"},
                "val_ratio": {"type": "number", "description": "验证集比例，默认 0.2"},
                "tag_filter": {"type": "string", "description": "标注标签过滤（可选）"}
            },
            "required": ["project_dir"]
        }
    }
}


def execute(arguments: dict) -> str:
    return _call_cli("train", arguments)
