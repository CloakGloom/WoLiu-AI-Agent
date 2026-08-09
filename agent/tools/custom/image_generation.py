"""
AI 绘画工具 —— 通过 ComfyUI API 三模型绘画
  - 写实（默认）：Z-Image-Turbo，8 步 turbo 推理，秒级出图
  - 动漫：NetaYume Lumina 3.5，30 步高质量二次元插画
  - 视频：WAN 2.1 T2V，文本生成视频
"""

import os
import time
import uuid
import subprocess
import socket
import requests
import random

from agent.utils import is_port_open, get_comfyui_path
from agent.tools import emit_progress
from agent.config import comfyui_url as _cfg_comfyui_url

COMFYUI_PATH = get_comfyui_path()
COMFYUI_URL = _cfg_comfyui_url()
COMFYUI_PYTHON = os.path.join(COMFYUI_PATH, "python_embeded", "python.exe")
COMFYUI_DIR = os.path.join(COMFYUI_PATH, "ComfyUI")  # main.py 所在目录
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "server", "static", "generated")
CLIENT_ID = str(uuid.uuid4())

_comfyui_proc = None  # ComfyUI 子进程引用
_DRAWING_MODEL = "写实"  # 当前选中的绘画模型：写实 / 动漫 / 视频


def set_drawing_model(model: str):
    """设置当前绘画模型（由前端按钮触发）"""
    global _DRAWING_MODEL
    if model in ("写实", "动漫", "视频"):
        _DRAWING_MODEL = model
        print(f"[AI绘画] 模型已切换为: {model}", flush=True)
        return True
    return False


def get_drawing_model() -> str:
    """获取当前绘画模型"""
    return _DRAWING_MODEL


SCHEMA = {
    "type": "function",
    "tag": "绘画",
    "function": {
        "name": "generate_image",
        "description": (
            "使用AI绘画生成图片或视频。支持三种模型：写实（真实照片级，Z-Image-Turbo，速度快）、"
            "动漫（二次元插画，NetaYume Lumina 3.5）、视频（文本生成视频，WAN 2.1）。"
            "优先使用写实模型，除非用户明确要求动漫风格或视频生成。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "图片/视频描述提示词。写实风格建议用英文描述，动漫风格中英文皆可，视频用英文最佳。"
                },
                "style": {
                    "type": "string",
                    "enum": ["写实", "动漫", "视频"],
                    "description": "生成风格。写实=真实照片级图片(Z-Image-Turbo)，动漫=二次元插画(NetaYume)，视频=文本生成视频(WAN 2.1)。默认使用写实。"
                },
                "negative_prompt": {
                    "type": "string",
                    "description": "负面提示词，描述不想要出现在画面中的内容。动漫和视频风格有效，写实风格不需要。（可选）"
                },
                "seed": {
                    "type": "integer",
                    "description": "随机种子，相同种子+相同提示词会生成相同内容。不填则随机。（可选）"
                }
            },
            "required": ["prompt"]
        }
    }
}

# ==================== 动漫风格（NetaYume Lumina 3.5） ====================

# 默认负向提示词（来自工作流原始配置）
DEFAULT_NEGATIVE = (
    "blurry, worst quality, low quality, jpeg artifacts, signature, watermark, "
    "username, error, deformed hands, bad anatomy, extra limbs, poorly drawn hands, "
    "poorly drawn face, mutation, deformed, extra eyes, extra arms, extra legs, "
    "malformed limbs, fused fingers, too many fingers, long neck, cross-eyed, "
    "bad proportions, missing arms, missing legs, extra digit, fewer digits, cropped"
)

# 正向 System Prompt 前缀（来自工作流节点 52）
POSITIVE_PREFIX = (
    "You are an assistant designed to generate high quality anime images "
    "based on textual prompts. <Prompt Start> "
)

# 负向 System Prompt 前缀（来自工作流节点 41）
NEGATIVE_PREFIX = (
    "You are an assistant designed to generate low-quality images "
    "based on textual prompts <Prompt Start> "
)


def _build_neta_api_prompt(user_prompt: str, negative_prompt: str, seed: int) -> dict:
    """
    NetaYume Lumina 3.5 动漫工作流。
    节点拓扑：
      34(CheckpointLoaderSimple) → 32(ModelSamplingAuraFlow) → 33(KSampler)
      34 → CLIP → 50(CLIPTextEncode正) → 33
      34 → CLIP → 43(CLIPTextEncode负) → 33
      52(SystemPrompt) → 49(StringConcat) ← 51(UserPrompt)
      49 → 50(text)
      41(SystemPrompt) → 40(StringConcat) ← 42(NegPrompt)
      40 → 43(text)
      31(EmptyLatent) → 33(latent)
      33 → 36(VAEDecode) → 9(SaveImage)
    """
    return {
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["36", 0],
                "filename_prefix": "NetaYume_Lumina_3.5"
            }
        },
        "31": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": 1024, "height": 1024, "batch_size": 1}
        },
        "32": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {"model": ["34", 0], "shift": 4}
        },
        "33": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["32", 0],
                "positive": ["50", 0],
                "negative": ["43", 0],
                "latent_image": ["31", 0],
                "seed": seed,
                "steps": 30,
                "cfg": 4,
                "sampler_name": "res_multistep",
                "scheduler": "simple",
                "denoise": 1,
            }
        },
        "34": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "NetaYumev35_pretrained_all_in_one.safetensors"}
        },
        "36": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["33", 0], "vae": ["34", 2]}
        },
        "40": {
            "class_type": "StringConcatenate",
            "inputs": {"string_a": ["41", 0], "string_b": ["42", 0], "delimiter": ""}
        },
        "41": {
            "class_type": "PrimitiveStringMultiline",
            "inputs": {"value": NEGATIVE_PREFIX}
        },
        "42": {
            "class_type": "PrimitiveStringMultiline",
            "inputs": {"value": negative_prompt}
        },
        "43": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["34", 1], "text": ["40", 0]}
        },
        "49": {
            "class_type": "StringConcatenate",
            "inputs": {"string_a": ["52", 0], "string_b": ["51", 0], "delimiter": ""}
        },
        "50": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["34", 1], "text": ["49", 0]}
        },
        "51": {
            "class_type": "PrimitiveStringMultiline",
            "inputs": {"value": user_prompt}
        },
        "52": {
            "class_type": "PrimitiveStringMultiline",
            "inputs": {"value": POSITIVE_PREFIX}
        },
    }


# ==================== 写实风格（Z-Image-Turbo） ====================

# Z-Image-Turbo 所需的三个模型文件及下载地址
ZIMAGE_MODELS = {
    "unet": {
        "rel_path": "diffusion_models/z_image_turbo_bf16.safetensors",
        "url": "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors",
        "label": "UNET (z_image_turbo_bf16)",
    },
    "clip": {
        "rel_path": "text_encoders/qwen_3_4b.safetensors",
        "url": "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors",
        "label": "CLIP (qwen_3_4b)",
    },
    "vae": {
        "rel_path": "vae/ae.safetensors",
        "url": "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors",
        "label": "VAE (ae)",
    },
}


def _check_zimage_models() -> str:
    """检查 Z-Image-Turbo 模型文件是否就位，返回缺失信息或空字符串"""
    models_dir = os.path.join(COMFYUI_PATH, "ComfyUI", "models")
    missing = []
    for key, info in ZIMAGE_MODELS.items():
        full_path = os.path.join(models_dir, info["rel_path"])
        if not os.path.exists(full_path):
            missing.append(f"  - {info['label']}: {info['rel_path']}")
    if missing:
        return (
            "Z-Image-Turbo 写实模型缺失，请先下载以下文件到 ComfyUI models 目录：\n"
            + "\n".join(missing)
            + "\n\n下载地址：https://huggingface.co/Comfy-Org/z_image_turbo"
        )
    return ""


def _build_zimage_api_prompt(user_prompt: str, seed: int) -> dict:
    """
    Z-Image-Turbo 写实工作流（SamplerCustomAdvanced 版，避 tqdm Windows bug）。
    节点拓扑：
      28(UNETLoader) → 11(ModelSamplingAuraFlow) → 6(BasicScheduler) → SIGMAS
      28(UNETLoader) → 11 → 16(BasicGuider) ← 27(CLIPTextEncode) ← 30(CLIPLoader)
      17(KSamplerSelect) → SAMPLER
      15(RandomNoise) → NOISE
      13(EmptySD3LatentImage) → LATENT
      NOISE+GUIDER+SAMPLER+SIGMAS+LATENT → 3(SamplerCustomAdvanced) → 8(VAEDecode) → 9(SaveImage)
    """
    return {
        "3": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["15", 0],
                "guider": ["16", 0],
                "sampler": ["17", 0],
                "sigmas": ["6", 0],
                "latent_image": ["13", 0],
            },
        },
        "6": {
            "class_type": "BasicScheduler",
            "inputs": {
                "model": ["11", 0],
                "scheduler": "simple",
                "steps": 8,
                "denoise": 1,
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["29", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "z-image-turbo"},
        },
        "11": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {"model": ["28", 0], "shift": 3},
        },
        "13": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": 1024, "height": 1024, "batch_size": 1},
        },
        "15": {
            "class_type": "RandomNoise",
            "inputs": {"noise_seed": seed},
        },
        "16": {
            "class_type": "BasicGuider",
            "inputs": {"model": ["11", 0], "conditioning": ["27", 0]},
        },
        "17": {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": "res_multistep"},
        },
        "27": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["30", 0], "text": user_prompt},
        },
        "28": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "z_image_turbo_bf16.safetensors",
                "weight_dtype": "default",
            },
        },
        "29": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "ae.safetensors"},
        },
        "30": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "qwen_3_4b.safetensors",
                "type": "lumina2",
                "device": "default",
            },
        },
    }


# ==================== 视频风格（WAN 2.1 T2V） ====================

# WAN 2.1 T2V 模型文件
WAN_MODELS = {
    "unet": {
        "rel_path": "diffusion_models/wan2.1_t2v_14B_bf16.safetensors",
        "label": "WAN2.1 T2V UNET (wan2.1_t2v_14B)",
    },
    "vae": {
        "rel_path": "vae/wan_2.1_vae.safetensors",
        "label": "WAN2.1 VAE",
    },
    "clip": {
        "rel_path": "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "label": "WAN2.1 CLIP (umt5_xxl)",
    },
}

# WAN 视频生成默认负向提示词
WAN_DEFAULT_NEGATIVE = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，"
    "整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，"
    "画得不好的手部，画得不好的面部，畸形的，变形，模糊，糟糕的解剖结构，"
    "糟糕的比例，多余的肢体，克隆的脸，毁容，总体比例，畸形，最差质量，"
    "正常质量，低质量，低分辨率，糟糕的阴影，多余的腿，畸形的手指，扭曲的手指"
)


def _check_wan_models() -> str:
    """检查 WAN 2.1 模型文件是否就位"""
    models_dir = os.path.join(COMFYUI_PATH, "ComfyUI", "models")
    missing = []
    for key, info in WAN_MODELS.items():
        full_path = os.path.join(models_dir, info["rel_path"])
        if not os.path.exists(full_path):
            missing.append(f"  - {info['label']}: {info['rel_path']}")
    if missing:
        return (
            "WAN 2.1 视频模型缺失，请先下载以下文件到 ComfyUI models 目录：\n"
            + "\n".join(missing)
            + "\n\n下载地址：https://huggingface.co/Wan-AI/Wan2.1-T2V-14B"
        )
    return ""


def _build_wan_api_prompt(user_prompt: str, negative_prompt: str, seed: int,
                          width: int = 832, height: int = 480, length: int = 33) -> dict:
    """
    WAN 2.1 T2V 视频生成工作流（简易版）。
    节点拓扑（仅用原生节点，无需 WANVideo 自定义节点包）：
      10(UNETLoader) → 20(KSampler)
      14(VAELoader) → 22(VAEDecode)
      11(CLIPLoader) → 15(CLIPTextEncode正) → 20(positive)
      11(CLIPLoader) → 17(CLIPTextEncode负) → 20(negative)
      13(EmptyHunyuanLatentVideo) → 20(latent)
      20(KSampler) → 22(VAEDecode) → 24(VHS_VideoCombine) → 25(SaveImage)
    """
    return {
        "10": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "wan2.1_t2v_14B_bf16.safetensors",
                "weight_dtype": "fp8_e4m3fn",
            },
        },
        "11": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                "type": "wan",
                "device": "default",
            },
        },
        "13": {
            "class_type": "EmptyHunyuanLatentVideo",
            "inputs": {
                "width": width,
                "height": height,
                "length": length,
                "batch_size": 1,
            },
        },
        "14": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "wan_2.1_vae.safetensors"},
        },
        "15": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["11", 0], "text": user_prompt},
        },
        "17": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["11", 0], "text": negative_prompt},
        },
        "20": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 20,
                "cfg": 6,
                "sampler_name": "uni_pc",
                "scheduler": "simple",
                "denoise": 1,
                "model": ["10", 0],
                "positive": ["15", 0],
                "negative": ["17", 0],
                "latent_image": ["13", 0],
            },
        },
        "22": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["20", 0], "vae": ["14", 0]},
        },
        "24": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["22", 0],
                "frame_rate": 16,
                "loop_count": 0,
                "filename_prefix": "wan2.1_t2v",
                "format": "video/h264-mp4",
                "pix_fmt": "yuv420p",
                "crf": 19,
                "save_metadata": True,
                "pingpong": False,
            },
        },
        "25": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["22", 0],
                "filename_prefix": "wan2.1_t2v_frames",
            },
        },
    }


# ==================== 风格自动识别 ====================

# 动漫风格的触发关键词
_ANIME_KEYWORDS = [
    "动漫", "二次元", "anime", "插画", "卡通", "cartoon", "漫画", "manga",
    "赛璐璐", "cel shading", "手绘", "线稿", "平涂",
]

# 视频生成的触发关键词
_VIDEO_KEYWORDS = [
    "视频", "video", "动画", "动态", "短视频", "短片", "生成视频",
    "拍摄", "录像", "录制", "画面连续", "运动", "动作",
]


def _detect_style(user_prompt: str, explicit_style: str = None) -> str:
    """根据显式参数或提示词内容判断风格，返回 "写实" / "动漫" / "视频" """
    if explicit_style:
        return explicit_style
    prompt_lower = user_prompt.lower()
    # 优先检测视频关键词
    for kw in _VIDEO_KEYWORDS:
        if kw in prompt_lower:
            return "视频"
    # 检测动漫关键词
    for kw in _ANIME_KEYWORDS:
        if kw in prompt_lower:
            return "动漫"
    return "写实"  # 默认写实


# ==================== 共享基础设施（启动/提交/等待/下载） ====================

def _start_comfyui() -> str:
    """启动 ComfyUI 服务，返回状态信息"""
    global _comfyui_proc

    if is_port_open():
        print("[AI绘画] ComfyUI 已在运行 (端口 8188)，跳过启动", flush=True)
        return ""

    print("[AI绘画] 正在启动 ComfyUI...", flush=True)
    print(f"[AI绘画] Python: {COMFYUI_PYTHON}", flush=True)
    print(f"[AI绘画] 目录: {COMFYUI_PATH}", flush=True)

    if not os.path.exists(COMFYUI_PYTHON):
        return f"ComfyUI Python 未找到：{COMFYUI_PYTHON}"
    if not os.path.isdir(COMFYUI_DIR):
        return f"ComfyUI 目录未找到：{COMFYUI_DIR}"

    try:
        env = os.environ.copy()
        env["PYTHONNOUSERSITE"] = "1"
        git_path = os.path.join(COMFYUI_PATH, "python_embeded", "Scripts", "git.exe")
        if os.path.exists(git_path):
            env["GIT_PYTHON_GIT_EXECUTABLE"] = git_path

        _comfyui_proc = subprocess.Popen(
            [COMFYUI_PYTHON, "-s", "ComfyUI/main.py", "--port", "8188",
             "--disable-auto-launch", "--windows-standalone-build", "--lowvram"],
            cwd=COMFYUI_PATH,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return "ComfyUI 已启动，等待就绪..."
    except Exception as e:
        return f"启动 ComfyUI 失败：{e}"


def _ensure_comfyui_running() -> str:
    """确保 ComfyUI 正在运行，如未运行则自动启动，返回错误信息或空字符串"""
    if is_port_open():
        return ""

    start_msg = _start_comfyui()
    if "失败" in start_msg or "未找到" in start_msg:
        return start_msg

    print("[AI绘画] 等待 ComfyUI 就绪（首次加载模型约需 30-60 秒）...", flush=True)
    for i in range(60):
        time.sleep(2)
        if _comfyui_proc is not None and _comfyui_proc.poll() is not None:
            try:
                err = _comfyui_proc.stdout.read().decode("utf-8", errors="replace")[-1000:]
            except Exception:
                err = "(无法读取输出)"
            msg = f"ComfyUI 进程异常退出（退出码 {_comfyui_proc.returncode}）"
            print(f"[AI绘画] {msg}", flush=True)
            print(f"[AI绘画] === 错误输出 ===\n{err}", flush=True)
            return f"{msg}：{err[-200:]}"
        if is_port_open():
            print("[AI绘画] ComfyUI 已就绪 (端口 8188)", flush=True)
            return ""
        if i % 5 == 0:
            print(f"[AI绘画] 等待中... ({i*2}s/{120}s)", flush=True)
    print("[AI绘画] 启动超时 (120s)", flush=True)
    return "ComfyUI 启动超时 (120s)"


def _submit_prompt(api_prompt: dict) -> str:
    payload = {"prompt": api_prompt, "client_id": CLIENT_ID}
    resp = requests.post(f"{COMFYUI_URL}/prompt", json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if "prompt_id" not in data:
        raise Exception(f"ComfyUI 返回异常: {data}")
    return data["prompt_id"]


def _wait_for_result(prompt_id: str, timeout: int = 300, is_turbo: bool = False) -> dict:
    """
    等待生成完成。turbo 模式（8 steps）预估时间更短，进度条更紧凑。
    """
    start = time.time()
    last_pct = 9  # 从 10% 开始，确保前端立即看到进度条
    emit_progress("generate_image", 10, "AI 绘画生成中...")
    # turbo 模型预估 10-20s，非 turbo 30-120s
    est_secs = 15 if is_turbo else 60
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if prompt_id in data:
                    return data[prompt_id]
        except requests.exceptions.ConnectionError:
            raise Exception("ComfyUI 服务连接中断，可能因显存不足崩溃。请重启 ComfyUI 后重试。")
        except Exception:
            pass
        elapsed = time.time() - start
        pct = min(10 + int(elapsed / est_secs * 80), 90)
        if pct > last_pct:
            last_pct = pct
            emit_progress("generate_image", pct, "AI 绘画生成中...")
        time.sleep(1 if is_turbo else 2)
    raise TimeoutError(f"图片生成超时（{timeout}秒）")


def _download_image(prompt_id: str, history: dict) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    outputs = history.get("outputs", {})
    for node_id, node_output in outputs.items():
        # 图片输出（SaveImage / PreviewImage）
        for img in node_output.get("images", []):
            filename = img["filename"]
            subfolder = img.get("subfolder", "")
            img_type = img.get("type", "output")
            params = {"filename": filename, "type": img_type}
            if subfolder:
                params["subfolder"] = subfolder
            resp = requests.get(f"{COMFYUI_URL}/view", params=params, timeout=30)
            resp.raise_for_status()
            save_path = os.path.join(OUTPUT_DIR, filename)
            with open(save_path, "wb") as f:
                f.write(resp.content)
            return f"/static/generated/{filename}"
        # 视频输出（VHS_VideoCombine）
        for vid in node_output.get("gifs", []):
            filename = vid["filename"]
            subfolder = vid.get("subfolder", "")
            vid_type = vid.get("type", "output")
            params = {"filename": filename, "subfolder": subfolder, "type": vid_type}
            if not subfolder:
                params.pop("subfolder", None)
            resp = requests.get(f"{COMFYUI_URL}/view", params=params, timeout=60)
            resp.raise_for_status()
            save_path = os.path.join(OUTPUT_DIR, filename)
            with open(save_path, "wb") as f:
                f.write(resp.content)
            return f"/static/generated/{filename}"
    return None


# ==================== 统一执行入口 ====================

def execute(arguments: dict) -> str:
    user_prompt = arguments.get("prompt", "")
    explicit_style = arguments.get("style")
    negative_prompt = arguments.get("negative_prompt", "")
    seed = arguments.get("seed")

    if not user_prompt:
        return "请提供图片描述（prompt 参数）。"

    # 确定风格：优先使用 AI 传入的 style 参数，其次使用前端选中的模型，最后自动检测
    if explicit_style:
        style = explicit_style
    else:
        # 使用前端选择的默认模型
        style = _DRAWING_MODEL
        # 如果前端选择了写实但 prompt 明显是动漫/视频内容，则自动切换
        if style == "写实":
            style = _detect_style(user_prompt, None)

    if seed is None:
        seed = random.randint(1, 2**63 - 1)

    try:
        # 自动启动 ComfyUI（如未运行）
        emit_progress("generate_image", 5, "正在检查 ComfyUI 服务...")
        err = _ensure_comfyui_running()
        if err:
            return err

        if style == "视频":
            # 检查视频模型是否就位
            model_err = _check_wan_models()
            if model_err:
                return model_err

            if not negative_prompt:
                negative_prompt = WAN_DEFAULT_NEGATIVE

            emit_progress("generate_image", 10, "已提交视频生成任务（WAN 2.1）...")
            api_prompt = _build_wan_api_prompt(user_prompt, negative_prompt, seed)
            prompt_id = _submit_prompt(api_prompt)
            history = _wait_for_result(prompt_id, timeout=600, is_turbo=False)
            style_label = "视频生成 (WAN 2.1)"

        elif style == "写实":
            # 检查模型是否就位
            model_err = _check_zimage_models()
            if model_err:
                return model_err

            emit_progress("generate_image", 10, f"已提交写实风格生成任务（Z-Image-Turbo）...")
            api_prompt = _build_zimage_api_prompt(user_prompt, seed)
            prompt_id = _submit_prompt(api_prompt)
            history = _wait_for_result(prompt_id, timeout=120, is_turbo=True)
            style_label = "写实风格 (Z-Image-Turbo)"

        else:  # 动漫
            if not negative_prompt:
                negative_prompt = DEFAULT_NEGATIVE

            emit_progress("generate_image", 10, "已提交动漫风格生成任务（NetaYume）...")
            api_prompt = _build_neta_api_prompt(user_prompt, negative_prompt, seed)
            prompt_id = _submit_prompt(api_prompt)
            history = _wait_for_result(prompt_id, timeout=180, is_turbo=False)
            style_label = "动漫风格 (NetaYume Lumina 3.5)"

        emit_progress("generate_image", 95, "正在保存文件...")
        image_url = _download_image(prompt_id, history)
        emit_progress("generate_image", 100, "生成完成")

        if image_url:
            media_type = "视频" if style == "视频" else "图片"
            return f"[IMAGE:{image_url}]{style_label}{media_type}已生成！（种子: {seed}）"
        else:
            return "生成完成，但无法获取输出文件。"

    except requests.exceptions.ConnectionError:
        return "ComfyUI 服务未连接，请确认 ComfyUI 已启动（端口 8188）。"
    except TimeoutError as e:
        return f"生成超时：{e}"
    except Exception as e:
        return f"生成失败：{e}"

execute._timeout = 600.0  # AI 绘画/视频最长 600 秒
