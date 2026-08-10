"""
AutoLabel CLI bridge —— 供外部进程安全调用（规避 AGPL import 传染）
用法: python autolabel_cli.py --command <dataset|train|predict> --args '<json>'
输出: JSON on stdout（status + data/error）
"""
import argparse, json, os, sys, time, traceback

# 脚本放在 scripts/ 下，运行时切换到 autolabel 目录
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
AUTOLABEL_ROOT = os.path.join(_PROJECT_ROOT, "side-projects", "autolabel-dock-main")
os.chdir(AUTOLABEL_ROOT)
if AUTOLABEL_ROOT not in sys.path:
    sys.path.insert(0, AUTOLABEL_ROOT)

# ── dataset ──
def _cmd_dataset(action: str, args: dict) -> str:
    from src.core.project import ProjectManager
    project_dir = args.get("project_dir", "").strip()
    if not project_dir or not os.path.isdir(project_dir):
        return error_json("项目目录不存在")
    if not os.path.isfile(os.path.join(project_dir, "project.json")):
        return error_json("不是有效的 autolabel-dock 项目（缺少 project.json）")

    if action == "create":
        name = args.get("project_name", "").strip() or os.path.basename(project_dir)
        image_dir = args.get("image_dir", "").strip() or "images"
        classes_str = args.get("classes", "").strip()
        task_type = args.get("task_type", "detect").strip()
        classes = [c.strip() for c in classes_str.split(",") if c.strip()] if classes_str else ["object"]
        os.makedirs(project_dir, exist_ok=True)
        pm = ProjectManager.create(project_dir=project_dir, name=name, image_dir=image_dir, classes=classes, task_type=task_type)
        return ok_json(f"项目已创建\n名称: {name}\n目录: {project_dir}\n任务: {task_type}\n类别: {', '.join(classes)}\n图片目录: {os.path.join(project_dir, 'images')}")

    elif action == "add_images":
        import shutil
        image_dir = args.get("image_dir", "").strip()
        if not image_dir or not os.path.isdir(image_dir):
            return error_json(f"图片目录不存在：{image_dir}")
        pm = ProjectManager.open(project_dir)
        target = os.path.join(project_dir, "images")
        os.makedirs(target, exist_ok=True)
        count = 0
        for ext in ('.jpg', '.jpeg', '.png', '.bmp', '.webp'):
            for f in os.listdir(image_dir):
                if f.lower().endswith(ext):
                    src = os.path.join(image_dir, f)
                    dst = os.path.join(target, f)
                    if not os.path.exists(dst):
                        shutil.copy2(src, dst)
                        count += 1
        return ok_json(f"已从 {image_dir} 导入 {count} 张图片到 {target}")

    elif action == "add_classes":
        classes_str = args.get("classes", "").strip()
        new = [c.strip() for c in classes_str.split(",") if c.strip()]
        if not new: return error_json("请提供类别名称")
        pm = ProjectManager.open(project_dir)
        existing = set(pm.config.classes)
        added = [c for c in new if c not in existing]
        for c in added: pm.add_class(c)
        msg = f"已添加 {len(added)} 个类别：{', '.join(added)}\n当前全部类别：{', '.join(pm.config.classes)}"
        if len(added) < len(new): msg += "\n（部分类别已存在，跳过）"
        return ok_json(msg)

    elif action == "status":
        pm = ProjectManager.open(project_dir)
        images = pm.list_images()
        confirmed = 0
        total_anns = 0
        from src.core.label_io import load_annotation
        for img_info in images:
            lp = pm.label_path_for(img_info['stem'])
            if os.path.exists(lp):
                try:
                    ann = load_annotation(lp)
                    if ann:
                        total_anns += len(ann.annotations)
                        if any(a.confirmed for a in ann.annotations):
                            confirmed += 1
                except Exception: pass
        models_dir = os.path.join(project_dir, "models")
        trained = []
        if os.path.isdir(models_dir):
            for d in os.listdir(models_dir):
                pt = os.path.join(models_dir, d, "weights", "best.pt")
                if os.path.isfile(pt): trained.append(pt)
        msg = (
            f"项目状态：{pm.config.name}\n"
            f"• 任务类型: {pm.config.task_type}\n• 类别: {', '.join(pm.config.classes)}\n"
            f"• 图片总数: {len(images)}\n• 已标注图片: {confirmed}\n• 标注框总数: {total_anns}\n"
            f"• 已训练模型: {len(trained)} 个"
        )
        if trained: msg += "\n  " + "\n  ".join(trained)
        if 0 < confirmed < 10: msg += "\n\n⚠ 标注不够，建议先标注 20+ 张再训练"
        return ok_json(msg)

    elif action == "export":
        from src.engine.dataset import DatasetPreparer
        pm = ProjectManager.open(project_dir)
        out_dir = os.path.join(project_dir, "datasets", "export")
        preparer = DatasetPreparer(pm)
        data_yaml = preparer.prepare(out_dir, task=pm.config.task_type, val_ratio=0.2)
        return ok_json(f"数据集已导出\n输出目录: {out_dir}\n配置文件: {data_yaml}\n格式: YOLO 标准格式")

    return error_json(f"未知操作: {action}")


# ── train ──
def _cmd_train(args: dict) -> str:
    from src.engine.trainer import TrainConfig, Trainer
    from src.engine.dataset import DatasetPreparer
    from src.core.project import ProjectManager
    from src.engine.model_manager import ModelRegistry
    from src.core.tags import TagFilter

    project_dir = args.get("project_dir", "").strip()
    base_model = args.get("base_model", "yolov8n.pt").strip()
    epochs = int(args.get("epochs", 100))
    batch = int(args.get("batch", 16))
    imgsz = int(args.get("imgsz", 640))
    val_ratio = float(args.get("val_ratio", 0.2))
    tag_filter_str = args.get("tag_filter", "").strip()

    if not os.path.isdir(project_dir): return error_json(f"项目目录不存在：{project_dir}")
    if not os.path.isfile(os.path.join(project_dir, "project.json")): return error_json(f"不是有效的 autolabel-dock 项目：{project_dir}")

    pm = ProjectManager.open(project_dir)
    confirmed_count = 0
    from src.core.label_io import load_annotation
    for img_info in pm.list_images():
        lp = pm.label_path_for(img_info['stem'])
        if os.path.exists(lp):
            try:
                ann = load_annotation(lp)
                if ann and any(a.confirmed and a.class_name for a in ann.annotations):
                    confirmed_count += 1
            except Exception: pass
    if confirmed_count < 5:
        return error_json(f"已确认标注不足（仅 {confirmed_count} 张），建议先标注至少 10-20 张")

    tag_filter = TagFilter(tag_filter_str) if tag_filter_str else None
    datasets_dir = os.path.join(project_dir, "datasets", "current")
    preparer = DatasetPreparer(pm)
    data_yaml = preparer.prepare(datasets_dir, task=pm.config.task_type, val_ratio=val_ratio, seed=42, tag_filter=tag_filter)

    run_name = f"run-{time.strftime('%Y%m%d-%H%M%S')}"
    config = TrainConfig(data_yaml=str(data_yaml), model=base_model, task=pm.config.task_type,
                         epochs=epochs, batch=batch, imgsz=imgsz, project=os.path.join(project_dir, "models"), name=run_name)
    trainer = Trainer()
    trainer.train(config, on_epoch_end=None)
    best_metrics = trainer.get_best_metrics()

    best_pt = os.path.join(project_dir, "models", run_name, "weights", "best.pt")
    model_info = {"name": run_name, "task": pm.config.task_type, "epochs": epochs, "base_model": base_model,
                  "imgsz": imgsz, "batch": batch, "metrics": best_metrics, "path": best_pt, "classes": pm.config.classes}
    ModelRegistry(os.path.join(project_dir, "models")).register(model_info)

    return ok_json(
        f"YOLO 模型训练完成！\n• 模型: {run_name}\n• 任务类型: {pm.config.task_type}\n"
        f"• 数据量: {confirmed_count} 张\n• 轮数: {epochs} epochs\n"
        f"• 指标: {json.dumps(best_metrics, ensure_ascii=False) if best_metrics else '训练中...'}\n• 模型路径: {best_pt}"
    )


# ── predict ──
def _cmd_predict(args: dict) -> str:
    from ultralytics import YOLO
    from src.engine.predictor import Predictor

    image_path = args.get("image_path", "").strip()
    model_path = args.get("model_path", "").strip()
    conf = float(args.get("conf", 0.25))
    iou = float(args.get("iou", 0.45))
    class_filter_str = args.get("class_filter", "").strip()

    if not image_path: return error_json("请提供图片路径")
    if not model_path: return error_json("请提供模型路径")
    if not os.path.exists(model_path): return error_json(f"模型文件不存在：{model_path}")

    images = []
    if os.path.isfile(image_path):
        images = [image_path]
    elif os.path.isdir(image_path):
        for ext in ('.jpg', '.jpeg', '.png', '.bmp', '.webp'):
            for f in os.listdir(image_path):
                if f.lower().endswith(ext): images.append(os.path.join(image_path, f))
        images.sort()
    else:
        return error_json(f"图片路径不存在：{image_path}")
    if not images: return error_json("未找到图片文件")

    class_filter = [c.strip() for c in class_filter_str.split(",") if c.strip()] if class_filter_str else None

    model = YOLO(model_path)
    predictor = Predictor(model)
    all_classes = predictor.class_names()
    task = model.task

    results = []
    for img in images[:50]:
        model_results = model(img, conf=conf, iou=iou, verbose=False)
        for r in model_results:
            boxes_data = []
            if task == "detect":
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    cls_name = all_classes.get(cls_id, str(cls_id))
                    if class_filter and cls_name not in class_filter: continue
                    boxes_data.append({"class": cls_name, "confidence": round(float(box.conf[0]), 3),
                                       "bbox": [round(float(x), 1) for x in box.xyxy[0].tolist()]})
            elif task == "classify":
                top5 = r.probs.top5 if r.probs else []
                for idx in top5:
                    boxes_data.append({"class": all_classes.get(int(idx), str(idx)), "confidence": round(float(r.probs.data[int(idx)]), 3)})
            results.append({"file": os.path.basename(img), "task": task, "detections": len(boxes_data), "objects": boxes_data})

    return ok_json(json.dumps({"task": task, "classes": list(all_classes.values()), "total_images": len(images), "results": results}, ensure_ascii=False))


# ── helpers ──
def ok_json(data: str) -> str:
    return json.dumps({"status": "ok", "data": data})
def error_json(msg: str) -> str:
    return json.dumps({"status": "error", "error": msg})

# ── main ──
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", required=True, choices=["dataset", "train", "predict"])
    parser.add_argument("--args", required=True)
    opts = parser.parse_args()
    try:
        args_dict = json.loads(opts.args)
    except json.JSONDecodeError as e:
        print(error_json(f"JSON 参数解析失败: {e}"))
        sys.exit(1)
    try:
        if opts.command == "dataset":
            action = args_dict.get("action", "status")
            print(_cmd_dataset(action, args_dict))
        elif opts.command == "train":
            print(_cmd_train(args_dict))
        elif opts.command == "predict":
            print(_cmd_predict(args_dict))
    except Exception as e:
        print(error_json(f"{type(e).__name__}: {e}\n{traceback.format_exc()}"))
        sys.exit(1)
