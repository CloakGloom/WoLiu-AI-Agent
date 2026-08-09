"""
AI 图生视频工具 —— MiniMax H3 Image-to-Video
通过 ComfyUI API，将一张静态图 + 运动描述 生成为带音频的视频。
工作流展开自：video_minimax_h3_i2v图生视频.json
"""

import os
import time
import uuid
import shutil
import subprocess
import requests
import random

from agent.utils import is_port_open, get_comfyui_path, get_comfyui_url, get_static_dir
from agent.tools import emit_progress

COMFYUI_PATH = get_comfyui_path()
COMFYUI_URL = get_comfyui_url()
COMFYUI_PYTHON = os.path.join(COMFYUI_PATH, "python_embeded_py313_bak", "python.exe")
COMFYUI_DIR = os.path.join(COMFYUI_PATH, "ComfyUI")
COMFYUI_INPUT = os.path.join(COMFYUI_DIR, "input")
COMFYUI_OUTPUT = os.path.join(COMFYUI_DIR, "output")

STATIC_DIR = str(get_static_dir())
OUTPUT_DIR = os.path.join(STATIC_DIR, "generated")
CLIENT_ID = str(uuid.uuid4())

from agent.config import load as _load_cfg

def _cfg_res(key: str, default: int) -> int:
    return _load_cfg().get("generation", {}).get(key, default)

_comfyui_proc = None

SCHEMA = {
    "type": "function",
    "tag": "视频",
    "function": {
        "name": "generate_video_i2v",
        "description": (
            "图生视频：将一张静态图片变为动态视频。需要提供图片路径和运动描述，"
            "基于 MiniMax H3 模型生成带音频的高质量视频。适合让一张照片/画作'动起来'。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "输入图片路径。支持：1) 直接传上一步生成的 [IMAGE:xxx] 标记；2) 绝对路径如 I:/Agent/server/static/generated/xxx.png；3) 相对路径如 /static/generated/xxx.png"
                },
                "prompt": {
                    "type": "string",
                    "description": "视频动作/运镜描述，描述画面中应该发生什么运动、镜头如何变化。支持中英文。"
                },
                "duration": {
                    "type": "number",
                    "description": "视频时长（秒），默认 5 秒。建议 2-10 秒。"
                },
                "seed": {
                    "type": "integer",
                    "description": "随机种子。不填则随机。"
                }
            },
            "required": ["image_path", "prompt"]
        }
    }
}

# MiniMax H3 所需模型文件
MINIMAX_MODELS = {
    "unet": {
        "rel_path": "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        "label": "UNET (minimax_h3_fl2va)",
    },
    "clip": {
        "rel_path": "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        "label": "CLIP (qwen3vl_32b)",
    },
    "video_vae": {
        "rel_path": "vae/minimax_h3_video_vae_fp16.safetensors",
        "label": "Video VAE",
    },
    "audio_vae": {
        "rel_path": "vae/minimax_h3_audio_vae_fp32.safetensors",
        "label": "Audio VAE",
    },
}
from agent.config import model_url_minimax_h3 as _cfg_minimax_h3
MODELS_URL = _cfg_minimax_h3()


def _check_models() -> str:
    """检查 MiniMax H3 模型是否就位"""
    models_dir = os.path.join(COMFYUI_DIR, "models")
    missing = []
    for key, info in MINIMAX_MODELS.items():
        full_path = os.path.join(models_dir, info["rel_path"])
        if not os.path.exists(full_path):
            missing.append(f"  - {info['label']}: {info['rel_path']}")
    if missing:
        return (
            "MiniMax H3 视频模型缺失，请先下载到 ComfyUI models 目录：\n"
            + "\n".join(missing)
            + f"\n\n下载地址：{MODELS_URL}"
        )
    return ""


def _compute_length(duration_sec: float) -> int:
    """根据时长计算视频帧数（与工作流中 ComfyMathExpression 逻辑一致）"""
    base = max(5, round(duration_sec * 24))
    padding = (5 - (base % 17)) % 17
    return base + padding


def _build_api_prompt(image_filename: str, user_prompt: str, duration: float, seed: int) -> dict:
    """
    构建 MiniMax H3 I2V 展开工作流。
    节点拓扑：
      UNETLoader(6) ─┬─→ BasicScheduler(9) → SamplerCustomAdvanced(14)
                      │    ┌─────────────────────────────────────┘
                      └─→ BasicGuider(16) ← MiniMaxH3ImageToVideo(104)
                           CLIPLoader(13) ──→ 104
                           VAELoader(11)  ──→ 104 + VAEDecode(10)
                           LoadImage(114) ──→ 104 (first_frame)
                           RandomNoise(15) ─→ SamplerCustomAdvanced(14)
                           KSamplerSelect(17) → SamplerCustomAdvanced(14)
      VAELoader(24) → VAEDecodeAudio(23) → CreateVideo(91) ← VAEDecode(10)
      CreateVideo(91) → SaveVideo(92)
    """
    length = _compute_length(duration)

    return {
        "6": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                "weight_dtype": "default",
            },
        },
        "9": {
            "class_type": "BasicScheduler",
            "inputs": {"model": ["6", 0], "scheduler": "simple", "steps": 20, "denoise": 1},
        },
        "10": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["14", 0], "vae": ["11", 0]},
        },
        "11": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"},
        },
        "13": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                "type": "minimax",
                "device": "default",
            },
        },
        "14": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["15", 0],
                "guider": ["16", 0],
                "sampler": ["17", 0],
                "sigmas": ["9", 0],
                "latent_image": ["104", 1],
            },
        },
        "15": {
            "class_type": "RandomNoise",
            "inputs": {"noise_seed": seed},
        },
        "16": {
            "class_type": "BasicGuider",
            "inputs": {"model": ["6", 0], "conditioning": ["104", 0]},
        },
        "17": {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": "res_multistep"},
        },
        "23": {
            "class_type": "VAEDecodeAudio",
            "inputs": {"samples": ["14", 0], "vae": ["24", 0]},
        },
        "24": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"},
        },
        "91": {
            "class_type": "CreateVideo",
            "inputs": {"images": ["10", 0], "fps": 24.0, "audio": ["23", 0], "bit_depth": 8},
        },
        "92": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["91", 0],
                "filename_prefix": "video/MiniMax_H3_I2V",
                "format": "auto",
                "codec": "auto",
            },
        },
        "104": {
            "class_type": "MiniMaxH3ImageToVideo",
            "inputs": {
                "clip": ["13", 0],
                "vae": ["11", 0],
                "first_frame": ["114", 0],
                "prompt": user_prompt,
                "width": _cfg_res("i2v_width", 640),
                "height": _cfg_res("i2v_height", 640),
                "length": length,
            },
        },
        "114": {
            "class_type": "LoadImage",
            "inputs": {"image": image_filename},
        },
    }


# ==================== ComfyUI 基础设施 ====================

def _start_comfyui() -> str:
    global _comfyui_proc
    if is_port_open():
        print("[图生视频] ComfyUI 已在运行，跳过启动", flush=True)
        return ""
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
            [COMFYUI_PYTHON, "-s", "ComfyUI/main.py", "--port", "8188", "--windows-standalone-build"],
            cwd=COMFYUI_PATH, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        return "ComfyUI 已启动，等待就绪..."
    except Exception as e:
        return f"启动 ComfyUI 失败：{e}"


def _ensure_comfyui_running() -> str:
    if is_port_open():
        return ""
    start_msg = _start_comfyui()
    if "失败" in start_msg or "未找到" in start_msg:
        return start_msg
    for i in range(60):
        time.sleep(2)
        if _comfyui_proc is not None and _comfyui_proc.poll() is not None:
            try:
                err = _comfyui_proc.stdout.read().decode("utf-8", errors="replace")[-1000:]
            except Exception:
                err = "(无法读取输出)"
            return f"ComfyUI 进程异常退出（退出码 {_comfyui_proc.returncode}）：{err[-200:]}"
        if is_port_open():
            print("[图生视频] ComfyUI 已就绪", flush=True)
            return ""
    return "ComfyUI 启动超时 (120s)"


def _submit_prompt(api_prompt: dict) -> str:
    resp = requests.post(f"{COMFYUI_URL}/prompt", json={"prompt": api_prompt, "client_id": CLIENT_ID}, timeout=60)
    if not resp.ok:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise Exception(f"ComfyUI 返回 {resp.status_code} 错误：{detail}")
    data = resp.json()
    if "prompt_id" not in data:
        raise Exception(f"ComfyUI 返回异常（缺少 prompt_id）: {data}")
    return data["prompt_id"]


def _wait_for_video(prompt_id: str, timeout: int = None) -> dict:
    """等待视频生成完成。超时从 config.yaml generation.video_timeout 读取。"""
    if timeout is None:
        timeout = _load_cfg().get("generation", {}).get("video_timeout", 1800)
    start = time.time()
    last_pct = -1
    est_secs = 120  # 预估 2 分钟（实际可能更长）
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if prompt_id in data:
                    return data[prompt_id]
        except requests.exceptions.ConnectionError:
            raise Exception("ComfyUI 服务连接中断，可能因显存不足崩溃。")
        except Exception:
            pass
        elapsed = time.time() - start
        pct = min(10 + int(elapsed / est_secs * 80), 90)
        if pct > last_pct:
            last_pct = pct
            emit_progress("generate_video_i2v", pct, "视频生成中（MiniMax H3）...")
        time.sleep(3)
    raise TimeoutError(f"视频生成超时（{timeout}秒）")


def _download_video(prompt_id: str, history: dict) -> str:
    """从 ComfyUI 输出目录获取生成的视频文件，复制到 static/generated/"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    outputs = history.get("outputs", {})
    for node_id, node_output in outputs.items():
        # SaveVideo 输出在 "gifs" 键下（ComfyUI 历史命名）
        media_list = node_output.get("gifs", []) or node_output.get("videos", []) or node_output.get("images", [])
        for item in media_list:
            filename = item["filename"]
            subfolder = item.get("subfolder", "")
            media_type = item.get("type", "output")
            params = {"filename": filename, "type": media_type}
            if subfolder:
                params["subfolder"] = subfolder
            resp = requests.get(f"{COMFYUI_URL}/view", params=params, timeout=120)
            resp.raise_for_status()
            save_path = os.path.join(OUTPUT_DIR, filename)
            with open(save_path, "wb") as f:
                f.write(resp.content)
            return f"/static/generated/{filename}"
    return None


# ==================== 执行入口 ====================

def execute(arguments: dict) -> str:
    import re
    image_path = arguments.get("image_path", "")
    user_prompt = arguments.get("prompt", "")
    duration = arguments.get("duration", 5)
    seed = arguments.get("seed")

    # 支持 [IMAGE:path] 格式（直接传之前生成的图片标记）
    m = re.match(r'\[IMAGE:([^\]]+)\]', image_path)
    if m:
        image_path = m.group(1)

    if not image_path:
        return "请提供输入图片路径（image_path 参数）。"
    if not user_prompt:
        return "请提供视频运动描述（prompt 参数）。"

    if seed is None:
        seed = random.randint(1, 2**63 - 1)

    # 校验图片是否存在
    if not os.path.exists(image_path):
        # 处理 /static/generated/xxx.png → 去掉 /static/ 前缀
        alt = image_path.lstrip("/")
        if alt.startswith("static/"):
            alt = alt[len("static/"):]
        alt_path = os.path.join(STATIC_DIR, alt)
        if os.path.exists(alt_path):
            image_path = alt_path
        else:
            return f"图片文件未找到：{image_path}（尝试过 {alt_path}）"

    try:
        # 检查模型
        model_err = _check_models()
        if model_err:
            return model_err

        # 确保 ComfyUI 运行
        emit_progress("generate_video_i2v", 3, "正在检查 ComfyUI 服务...")
        err = _ensure_comfyui_running()
        if err:
            return err

        # 将图片复制到 ComfyUI input 目录
        emit_progress("generate_video_i2v", 5, "正在准备输入图片...")
        os.makedirs(COMFYUI_INPUT, exist_ok=True)
        img_basename = os.path.basename(image_path)
        # 避免文件名冲突
        img_copy_name = f"_i2v_{uuid.uuid4().hex[:8]}_{img_basename}"
        img_dest = os.path.join(COMFYUI_INPUT, img_copy_name)
        shutil.copy2(image_path, img_dest)

        # 构建并提交工作流
        emit_progress("generate_video_i2v", 10, f"已提交图生视频任务（{duration}秒）...")
        api_prompt = _build_api_prompt(img_copy_name, user_prompt, duration, seed)
        prompt_id = _submit_prompt(api_prompt)
        history = _wait_for_video(prompt_id)

        emit_progress("generate_video_i2v", 95, "正在保存视频...")
        video_url = _download_video(prompt_id, history)
        emit_progress("generate_video_i2v", 100, "视频生成完成")

        if video_url:
            return f"[VIDEO:{video_url}]图生视频已生成！（种子: {seed}）"
        else:
            return "视频生成完成，但无法获取视频文件。请检查 ComfyUI 输出目录。"

    except requests.exceptions.ConnectionError:
        return "ComfyUI 服务未连接，请确认 ComfyUI 已启动（端口 8188）。"
    except TimeoutError as e:
        return f"视频生成超时：{e}"
    except Exception as e:
        return f"图生视频失败：{e}"

execute._timeout = 3000.0  # 视频生成耗时较长
