"""
YOLO 模型推理工具 —— 基于 autolabel-dock + ultralytics

AI 可调用此工具对图片进行目标检测、姿态估计、图像分类。
支持从 autolabel-dock 项目或直接指定模型路径。
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
        "name": "yolo_predict",
        "description": (
            "对图片进行 YOLO 目标检测/姿态估计/分类。"
            "支持单张图片或多张图片，返回检测到的物体及其位置和置信度。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "图片路径。可以是单张图片的绝对路径，或包含多张图片的目录路径。"
                },
                "model_path": {
                    "type": "string",
                    "description": "模型权重路径（.pt 文件）。可以是 autolabel-dock 项目的 models/ 下的 best.pt 或任意 YOLO 权重。"
                },
                "conf": {
                    "type": "number",
                    "description": "置信度阈值，默认 0.25",
                    "default": 0.25
                },
                "iou": {
                    "type": "number",
                    "description": "IoU 阈值（NMS），默认 0.45",
                    "default": 0.45
                },
                "class_filter": {
                    "type": "string",
                    "description": "只返回指定类别的检测结果，多个用逗号分隔。留空返回所有类别。如 'person,car'",
                    "default": ""
                }
            },
            "required": ["image_path", "model_path"]
        }
    }
}


def execute(arguments: dict) -> str:
    image_path = arguments.get("image_path", "").strip()
    model_path = arguments.get("model_path", "").strip()
    conf = float(arguments.get("conf", 0.25))
    iou = float(arguments.get("iou", 0.45))
    class_filter_str = arguments.get("class_filter", "").strip()

    if not image_path:
        return "请提供图片路径（image_path）"
    if not model_path:
        return "请提供模型路径（model_path）"

    if not os.path.exists(model_path):
        return f"模型文件不存在：{model_path}"

    # 收集图片
    images = []
    if os.path.isfile(image_path):
        images = [image_path]
    elif os.path.isdir(image_path):
        for ext in ('.jpg','.jpeg','.png','.bmp','.webp'):
            for f in os.listdir(image_path):
                if f.lower().endswith(ext):
                    images.append(os.path.join(image_path, f))
        images.sort()
    else:
        return f"图片路径不存在：{image_path}"

    if not images:
        return "未找到图片文件"

    class_filter = None
    if class_filter_str:
        class_filter = [c.strip() for c in class_filter_str.split(",") if c.strip()]

    try:
        from ultralytics import YOLO
        from src.engine.predictor import Predictor

        model = YOLO(model_path)
        predictor = Predictor(model)
        all_classes = predictor.class_names()
        task = model.task  # detect / classify / pose / segment

        results = []
        for img in images[:50]:  # 最多 50 张
            name = os.path.basename(img)
            try:
                if task == "classify":
                    r = predictor.predict_classify(img, filter_to_project=False)
                    if r:
                        cname, cconf = r
                        if not class_filter or cname in class_filter:
                            results.append({
                                "image": name,
                                "class": cname,
                                "confidence": round(cconf, 3),
                            })
                else:
                    anns = predictor.predict(img, conf=conf, iou=iou,
                            project_classes=class_filter,
                            class_match_mode="class_id")
                    for a in anns:
                        item = {
                            "image": name,
                            "class": a.class_name,
                            "confidence": round(a.confidence, 3),
                        }
                        if a.bbox:
                            item["bbox_cxcywh"] = [round(x, 4) for x in a.bbox]
                        if a.keypoints:
                            item["keypoints_count"] = len(a.keypoints)
                        results.append(item)
            except Exception as e:
                results.append({"image": name, "error": str(e)})

        # 格式化输出
        total = len(results)
        if total == 0:
            return f"未检测到任何物体（conf={conf}）。可尝试降低置信度阈值。"

        by_class = {}
        for r in results:
            c = r.get("class", "unknown")
            by_class.setdefault(c, 0)
            by_class[c] += 1

        summary = "\n".join(f"• {k}: {v} 个" for k, v in sorted(by_class.items(), key=lambda x: -x[1]))
        detail = "\n".join(
            f"  {r['image']}: {r.get('class','?')}"
            f"{' bbox=' + str(r.get('bbox_cxcywh','')) if r.get('bbox_cxcywh') else ''}"
            f"{' conf=' + str(r['confidence']) if r.get('confidence') else ''}"
            for r in results[:20]
        )

        return (
            f"检测完成（{len(images)} 张图片，共 {total} 个目标）\n\n"
            f"{summary}\n\n"
            f"详细结果（前20个）：\n{detail}"
            + ("\n...（更多结果已省略）" if total > 20 else "")
        )

    except Exception as e:
        import traceback
        return f"推理失败：{e}\n{traceback.format_exc()}"
