"""
模型配置 —— 模型路径 / 魔搭社区下载 ID

供设置页 UI 和下载 API 使用。
下载优先使用魔搭社区 (modelscope_id)，回退到 url。
"""
import json, os

_CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "drawing_models.json")

_DEFAULT = {
    "anime": {
        "unet": {
            "rel_path": "diffusion_models/NetaYumev35_pretrained_all_in_one.safetensors",
            "modelscope_id": "",
            "url": "", "label": "UNET 主模型 (NetaYume v3.5)"
        },
    },
    "realistic": {
        "unet": {
            "rel_path": "diffusion_models/z_image_turbo_bf16.safetensors",
            "modelscope_id": "",
            "url": "", "label": "UNET 主模型 (Z-Image-Turbo)"
        },
        "vae":  {
            "rel_path": "vae/ae.safetensors",
            "modelscope_id": "",
            "url": "", "label": "VAE 模型 (ae)"
        },
        "clip": {
            "rel_path": "text_encoders/qwen_3_4b.safetensors",
            "modelscope_id": "",
            "url": "", "label": "CLIP 模型 (qwen 3 4b)"
        },
    },
    "video": {
        "unet": {
            "rel_path": "diffusion_models/minimax_h3_fI2va_pruned_int8_convrot.safetensors",
            "modelscope_id": "",
            "url": "", "label": "UNET 主模型 (Minimax H3)"
        },
        "clip": {
            "rel_path": "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
            "modelscope_id": "",
            "url": "", "label": "CLIP 模型 (qwen3vl 32B)"
        },
        "video_vae": {
            "rel_path": "vae/minimax_h3_video_vae_fp16.safetensors",
            "modelscope_id": "",
            "url": "", "label": "VAE 模型 (Minimax H3 vae)"
        },
        "audio_vae": {
            "rel_path": "vae/minimax_h3_audio_vae_fp32.safetensors",
            "modelscope_id": "",
            "url": "", "label": "Audio VAE 模型 (Minimax H3)"
        },
    },
}

def _load() -> dict:
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        for k in _DEFAULT:
            if k not in cfg:
                cfg[k] = dict(_DEFAULT[k])
        return cfg
    except Exception:
        return {k: dict(v) for k, v in _DEFAULT.items()}

def _save(cfg: dict):
    os.makedirs(os.path.dirname(_CONFIG_FILE), exist_ok=True)
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def get_all() -> dict:
    return _load()

def update_model(style: str, part: str, field: str, value: str) -> dict:
    cfg = _load()
    if style in cfg and part in cfg[style]:
        cfg[style][part][field] = value
        _save(cfg)
    return cfg
