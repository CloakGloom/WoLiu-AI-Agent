"""
数据集管理工具 —— 通过子进程调用 autolabel-dock CLI（规避 AGPL import）
"""
import sys, os, json, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _call_cli(command: str, args: dict, timeout: int = 120) -> str:
    """通过子进程调用 autolabel CLI，返回结果字符串"""
    cli = os.path.join(ROOT, "scripts", "autolabel_cli.py")
    if not os.path.isfile(cli):
        return f"❌ autolabel CLI 未找到: {cli}"
    try:
        r = subprocess.run(
            [sys.executable, cli, "--command", command, "--args", json.dumps(args, ensure_ascii=False)],
            cwd=ROOT, capture_output=True, text=True, timeout=timeout, encoding="utf-8"
        )
        if r.returncode != 0 or not r.stdout.strip():
            stderr_detail = r.stderr.strip()[-500:] if r.stderr else "(无错误输出)"
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
        "name": "yolo_dataset_manage",
        "description": (
            "管理 YOLO 标注项目：创建新项目、导入图片、增删类别、查看项目状态。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "add_images", "add_classes", "status", "export"],
                    "description": "操作类型：create=创建项目, add_images=导入图片, add_classes=添加类别, status=查看状态, export=导出数据集"
                },
                "project_dir": {
                    "type": "string",
                    "description": "项目目录的绝对路径"
                },
                "project_name": {"type": "string", "description": "项目名称（create 时需要）"},
                "image_dir": {"type": "string", "description": "图片目录路径（create/add_images 时需要）"},
                "classes": {"type": "string", "description": "类别名称，多个用逗号分隔"},
                "task_type": {"type": "string", "description": "任务类型 detect/classify/pose，默认 detect"}
            },
            "required": ["action", "project_dir"]
        }
    }
}


def execute(arguments: dict) -> str:
    return _call_cli("dataset", arguments)
