"""
数据集管理工具 —— 基于 autolabel-dock

AI 可调用此工具创建标注项目、导入图片、管理类别、导出数据。
"""

import sys, os, json
from pathlib import Path

_AUTOLABEL_ROOT = None


def _get_autolabel_root():
    global _AUTOLABEL_ROOT
    if _AUTOLABEL_ROOT is None:
        from agent.config import load as _lc
        cfg = _lc()
        d = cfg.get("services", {}).get("autolabel", {}).get("project_dir", "")
        if d:
            p = Path(d) if Path(d).is_absolute() else Path(__file__).resolve().parent.parent.parent.parent / d
        else:
            p = Path(__file__).resolve().parent.parent.parent.parent / "side-projects" / "autolabel-dock-main"
        _AUTOLABEL_ROOT = str(p)
    return _AUTOLABEL_ROOT


AUTOLABEL_ROOT = _get_autolabel_root()
if AUTOLABEL_ROOT not in sys.path:
    sys.path.insert(0, AUTOLABEL_ROOT)

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
                    "description": "操作类型：create（创建项目）、add_images（添加图片目录）、add_classes（添加类别）、status（查看状态）、export（导出数据集）",
                    "enum": ["create", "add_images", "add_classes", "status", "export"]
                },
                "project_dir": {
                    "type": "string",
                    "description": "项目目录的绝对路径"
                },
                "project_name": {
                    "type": "string",
                    "description": "（仅 create）项目名称"
                },
                "image_dir": {
                    "type": "string",
                    "description": "（仅 add_images）图片目录路径"
                },
                "classes": {
                    "type": "string",
                    "description": "（仅 add_classes / create）类别名称，逗号分隔。如 'person,car,bike'"
                },
                "task_type": {
                    "type": "string",
                    "description": "（仅 create）任务类型: detect(检测)/classify(分类)/pose(姿态)",
                    "default": "detect",
                    "enum": ["detect", "classify", "pose"]
                }
            },
            "required": ["action", "project_dir"]
        }
    }
}


def execute(arguments: dict) -> str:
    from src.core.project import ProjectManager

    action = arguments.get("action", "").strip()
    project_dir = arguments.get("project_dir", "").strip()

    if not action:
        return "请指定操作类型（action）"
    if not project_dir:
        return "请指定项目目录（project_dir）"

    try:
        # ── CREATE ──
        if action == "create":
            name = arguments.get("project_name", "").strip() or os.path.basename(project_dir)
            image_dir = arguments.get("image_dir", "").strip() or "images"
            classes_str = arguments.get("classes", "").strip()
            task_type = arguments.get("task_type", "detect").strip()
            classes = [c.strip() for c in classes_str.split(",") if c.strip()] if classes_str else ["object"]

            os.makedirs(project_dir, exist_ok=True)
            pm = ProjectManager.create(
                project_dir=project_dir,
                name=name,
                image_dir=image_dir,
                classes=classes,
                task_type=task_type,
            )
            return (
                f"项目已创建\n"
                f"• 名称: {name}\n"
                f"• 目录: {project_dir}\n"
                f"• 任务: {task_type}\n"
                f"• 类别: {', '.join(classes)}\n"
                f"• 图片目录: {os.path.join(project_dir, 'images')}\n\n"
                f"提示：把图片放到 images/ 目录后，打开 autolabel-dock GUI 开始标注。"
                f"或运行 'add_images' 操作从外部目录导入。"
            )

        # ── ADD IMAGES ──
        elif action == "add_images":
            image_dir = arguments.get("image_dir", "").strip()
            if not image_dir or not os.path.isdir(image_dir):
                return f"图片目录不存在：{image_dir}"

            pm = ProjectManager.open(project_dir)
            target = os.path.join(project_dir, "images")
            os.makedirs(target, exist_ok=True)

            import shutil
            count = 0
            for ext in ('.jpg','.jpeg','.png','.bmp','.webp'):
                for f in os.listdir(image_dir):
                    if f.lower().endswith(ext):
                        src = os.path.join(image_dir, f)
                        dst = os.path.join(target, f)
                        if not os.path.exists(dst):
                            shutil.copy2(src, dst)
                            count += 1

            return f"已从 {image_dir} 导入 {count} 张图片到 {target}"

        # ── ADD CLASSES ──
        elif action == "add_classes":
            classes_str = arguments.get("classes", "").strip()
            new = [c.strip() for c in classes_str.split(",") if c.strip()]
            if not new:
                return "请提供类别名称"

            pm = ProjectManager.open(project_dir)
            existing = set(pm.config.classes)
            added = [c for c in new if c not in existing]
            for c in added:
                pm.add_class(c)

            return (
                f"已添加 {len(added)} 个类别：{', '.join(added)}\n"
                f"当前全部类别：{', '.join(pm.config.classes)}"
                + ("\n（部分类别已存在，跳过）" if len(added) < len(new) else "")
            )

        # ── STATUS ──
        elif action == "status":
            pm = ProjectManager.open(project_dir)
            images = pm.list_images()
            confirmed = 0
            total_anns = 0
            for img_info in images:
                lp = pm.label_path_for(img_info['stem'])
                if os.path.exists(lp):
                    try:
                        from src.core.label_io import load_annotation
                        ann = load_annotation(lp)
                        if ann:
                            total_anns += len(ann.annotations)
                            if any(a.confirmed for a in ann.annotations):
                                confirmed += 1
                    except Exception:
                        pass

            models_dir = os.path.join(project_dir, "models")
            trained = []
            if os.path.isdir(models_dir):
                for d in os.listdir(models_dir):
                    pt = os.path.join(models_dir, d, "weights", "best.pt")
                    if os.path.isfile(pt):
                        trained.append(pt)

            return (
                f"项目状态：{pm.config.name}\n"
                f"• 任务类型: {pm.config.task_type}\n"
                f"• 类别: {', '.join(pm.config.classes)}\n"
                f"• 图片总数: {len(images)}\n"
                f"• 已标注图片: {confirmed}\n"
                f"• 标注框总数: {total_anns}\n"
                f"• 已训练模型: {len(trained)} 个"
                + ("\n  " + "\n  ".join(trained) if trained else "")
                + ("\n\n⚠ 标注不够，建议先用 autolabel-dock GUI 标 20+ 张再训练" if confirmed < 10 and confirmed > 0 else "")
            )

        # ── EXPORT ──
        elif action == "export":
            pm = ProjectManager.open(project_dir)
            from src.engine.dataset import DatasetPreparer
            out_dir = os.path.join(project_dir, "datasets", "export")
            preparer = DatasetPreparer(pm)
            data_yaml = preparer.prepare(out_dir, task=pm.config.task_type, val_ratio=0.2)

            return (
                f"数据集已导出\n"
                f"• 输出目录: {out_dir}\n"
                f"• 配置文件: {data_yaml}\n"
                f"• 格式: YOLO 标准格式\n"
                f"• 可直接用于 ultralytics / autolabel-dock 训练"
            )

        else:
            return f"未知操作: {action}。有效操作: create, add_images, add_classes, status, export"

    except Exception as e:
        import traceback
        return f"操作失败：{e}\n{traceback.format_exc()}"
