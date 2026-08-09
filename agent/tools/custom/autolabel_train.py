"""
YOLO 模型训练工具 —— 基于 autolabel-dock + ultralytics

AI 可调用此工具根据已标注数据集训练自定义目标检测/分类/姿态估计模型。
训练完成后模型自动注册到 autolabel-dock 项目，可立即用于推理。
"""

import sys, os, uuid, json, time
from dataclasses import dataclass, field, asdict
from typing import Optional

_AUTOLABEL_ROOT = None


def _get_autolabel_root():
    global _AUTOLABEL_ROOT
    if _AUTOLABEL_ROOT is None:
        from agent.config import load as _lc
        cfg = _lc()
        d = cfg.get("services", {}).get("autolabel", {}).get("project_dir", "")
        from pathlib import Path as _P
        if d:
            p = _P(d) if _P(d).is_absolute() else _P(__file__).resolve().parent.parent.parent.parent / d
        else:
            p = _P(__file__).resolve().parent.parent.parent.parent / "side-projects" / "autolabel-dock-main"
        _AUTOLABEL_ROOT = str(p)
    return _AUTOLABEL_ROOT


AUTOLABEL_ROOT = _get_autolabel_root()
if AUTOLABEL_ROOT not in sys.path:
    sys.path.insert(0, AUTOLABEL_ROOT)

SCHEMA = {
    "type": "function",
    "tag": "IoT/图像",
    "function": {
        "name": "yolo_train",
        "description": (
            "训练 YOLO 目标检测/姿态估计/图像分类模型。需要先有一个标注完成的 autolabel-dock 项目。"
            "支持自定义训练参数（轮数、批大小、图片尺寸等），训练完成后自动注册模型。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_dir": {
                    "type": "string",
                    "description": "autolabel-dock 项目目录的绝对路径（包含 project.json 的文件夹）"
                },
                "base_model": {
                    "type": "string",
                    "description": "基础预训练模型，默认 yolov8n.pt（nano），可选 yolov8s/m/l/x.pt",
                    "default": "yolov8n.pt"
                },
                "epochs": {
                    "type": "number",
                    "description": "训练轮数，默认 100",
                    "default": 100
                },
                "batch": {
                    "type": "number",
                    "description": "批大小，默认 16（显存不够可减小）",
                    "default": 16
                },
                "imgsz": {
                    "type": "number",
                    "description": "图片输入尺寸，默认 640",
                    "default": 640
                },
                "val_ratio": {
                    "type": "number",
                    "description": "验证集比例，默认 0.2",
                    "default": 0.2
                },
                "tag_filter": {
                    "type": "string",
                    "description": "按标签筛选训练数据（如 'indoor & night'），留空则用全部",
                    "default": ""
                }
            },
            "required": ["project_dir"]
        }
    }
}


def execute(arguments: dict) -> str:
    from src.engine.trainer import TrainConfig, Trainer
    from src.engine.dataset import DatasetPreparer
    from src.core.project import ProjectManager
    from src.engine.model_manager import ModelRegistry
    from src.core.tags import TagFilter

    project_dir = arguments.get("project_dir", "").strip()
    base_model = arguments.get("base_model", "yolov8n.pt").strip()
    epochs = int(arguments.get("epochs", 100))
    batch = int(arguments.get("batch", 16))
    imgsz = int(arguments.get("imgsz", 640))
    val_ratio = float(arguments.get("val_ratio", 0.2))
    tag_filter_str = arguments.get("tag_filter", "").strip()

    if not os.path.isdir(project_dir):
        return f"项目目录不存在：{project_dir}"
    prog_json = os.path.join(project_dir, "project.json")
    if not os.path.isfile(prog_json):
        return f"不是有效的 autolabel-dock 项目（缺少 project.json）：{project_dir}"

    try:
        pm = ProjectManager.open(project_dir)

        # 检查标注数量
        images = pm.list_images()
        confirmed_count = 0
        for img_info in images:
            try:
                from src.core.label_io import load_annotation
                from src.core.label_store import LabelStore
                lp = pm.label_path_for(img_info['stem'])
                if os.path.exists(lp):
                    ann = load_annotation(lp)
                    if ann and any(a.confirmed and a.class_name for a in ann.annotations):
                        confirmed_count += 1
            except Exception:
                continue

        if confirmed_count < 5:
            return (
                f"已确认标注的图片不足（仅 {confirmed_count} 张）。"
                f"建议先用 autolabel-dock GUI 标注至少 10-20 张图片后再训练。"
            )

        # 准备数据集
        tag_filter = None
        if tag_filter_str:
            tag_filter = TagFilter(tag_filter_str)

        datasets_dir = os.path.join(project_dir, "datasets", "current")
        preparer = DatasetPreparer(pm)
        data_yaml = preparer.prepare(
            datasets_dir,
            task=pm.config.task_type,
            val_ratio=val_ratio,
            seed=42,
            tag_filter=tag_filter,
        )

        # 配置训练
        run_name = f"run-{time.strftime('%Y%m%d-%H%M%S')}"
        config = TrainConfig(
            data_yaml=str(data_yaml),
            model=base_model,
            task=pm.config.task_type,
            epochs=epochs,
            batch=batch,
            imgsz=imgsz,
            project=os.path.join(project_dir, "models"),
            name=run_name,
        )

        # 训练
        last_pct = [0]
        def on_epoch_end(metrics):
            ep = metrics.get("epoch", 0)
            pct = min(ep * 100 // epochs, 99)
            if pct > last_pct[0]:
                last_pct[0] = pct
                try:
                    from agent.tools import emit_progress
                    emit_progress("yolo_train", pct,
                        f'训练中... epoch {ep}/{epochs}')
                except Exception:
                    pass

        trainer = Trainer()
        trainer.train(config, on_epoch_end=on_epoch_end)
        best_metrics = trainer.get_best_metrics()

        # 注册模型
        best_pt = os.path.join(project_dir, "models", run_name, "weights", "best.pt")
        model_info = {
            "name": run_name,
            "task": pm.config.task_type,
            "epochs": epochs,
            "base_model": base_model,
            "imgsz": imgsz,
            "batch": batch,
            "metrics": best_metrics,
            "path": best_pt,
            "classes": pm.config.classes,
        }

        registry = ModelRegistry(os.path.join(project_dir, "models"))
        registry.register(model_info)

        try:
            from agent.tools import emit_progress
            emit_progress("yolo_train", 100, "训练完成")
        except Exception:
            pass

        return (
            f"YOLO 模型训练完成！\n"
            f"• 模型: {run_name}\n"
            f"• 任务类型: {pm.config.task_type}\n"
            f"• 数据量: {confirmed_count} 张已确认标注\n"
            f"• 轮数: {epochs} epochs\n"
            f"• 指标: {json.dumps(best_metrics, ensure_ascii=False) if best_metrics else '训练中...'}\n"
            f"• 模型路径: {best_pt}"
        )

    except Exception as e:
        import traceback
        return f"训练失败：{e}\n{traceback.format_exc()}"
