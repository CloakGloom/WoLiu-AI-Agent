# WoLiu AI Agent

个人 AI 伴侣/住手系统 —— 基于 ReAct Agent 架构，支持多模态交互、可插拔工具体系、15 维演化人格与长期向量记忆。

## 核心架构

```
用户输入 (PC / 手机)
       │
       ▼
┌─────────────────────────────────────┐
│         ReAct Agent 循环             │
│   Think → Act → Observe → Think     │
│         (OpenAI 兼容 LLM)            │
└─────────────────────────────────────┘
       │
       ├── 工具调度中心 ──────────────────
       │   ├── 内建工具 (计算/搜索/天气/诊断...)
       │   ├── 自定义工具 (图像生成/PPT/简历/提醒...)
       │   ├── 硬件工具 (摄像头/麦克风/扬声器)
       │   └── MCP 工具 (浏览器/标注/动画/...)
       │
       ├── 15 维人格系统 ─────────────────
       │   └── 动态演化 → 行为过滤 → 回复风格
       │
       ├── 向量记忆 (ChromaDB) ────────────
       │   └── 短期滑动窗口 + 长期 RAG 检索
       │
       └── 规则引擎 ─────────────────────
           └── System Prompt 动态构建
```

## 功能特性

| 模块 | 说明 |
|------|------|
| **智能对话** | 多轮对话、流式输出、Markdown 渲染、多会话管理、分支回复 |
| **工具系统** | 内建 8 个 + 自定义 15+ 个工具，支持运行态启用/禁用 |
| **MCP 协议** | Model Context Protocol 可插拔工具体系，本地 + 远程 Server |
| **15 维人格** | warmth / sarcasm / openness 等维度，随对话自动演化 |
| **长期记忆** | ChromaDB 向量库 + Sentence-Transformers 语义检索 |
| **设备迁移** | 状态机驱动的 PC ↔ 手机无缝切换，断线自动回迁 |
| **多媒体生成** | ComfyUI 图像/视频、TTS 语音合成、Presenton PPT、JadeAI 简历 |
| **提醒系统** | 自然语言定时提醒 + edge-tts 语音播报 + WebSocket 推送 |
| **健康提醒** | 基于人格状态的喝水/吃饭智能调度 |
| **双端 UI** | 电脑端 Web 全功能面板 + 手机端轻量界面 |
| **服务管理** | Web UI 一键启动/停止/重启 ComfyUI、TTS、Ollama 等外部服务 |

## 快速开始

### 方式一：一键安装（Windows）

```bash
setup.bat
```

自动创建虚拟环境、安装所有依赖、生成默认配置。

### 方式二：手动安装

```bash
# 1. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate # Linux / macOS

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API Key
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY 等

# 4. 启动
python run_server.py
```

启动后访问 **http://localhost:8081** 进入 Web 界面。

### 可选：本地部署 Ollama

```bash
# Windows: 从 https://ollama.com/download 下载安装
# 安装后自动运行在 http://localhost:11434
ollama pull qwen3-vl:4b             # 推荐模型
```

### 手机端（Android Termux）

```bash
python run_client.py
```

## 配置体系

采用多层配置结构，密钥与配置分离：

| 文件 | 用途 | 是否入库 |
|------|------|----------|
| `config.yaml` | 主配置文件（服务地址、端口、模型参数） | ✅ |
| `config.local.yaml` | 本地覆盖配置 | ❌ |
| `.env` | API Key 等敏感信息 | ❌ |
| `config/settings.json` | 运行时设置（通过 Web UI 修改） | ❌ |
| `config/mcp.json` | MCP Server 配置参考 | ✅ |
| `config/autostart.json` | 服务自启动配置 | ❌ |

默认使用 SiliconFlow 云服务的 DeepSeek-V3 模型，也支持切换为 OpenAI、Ollama 本地模型等任何兼容 OpenAI API 格式的后端。

## 项目结构

```
agent/                    # 核心 Agent 逻辑
├── core.py               # ReAct Agent 主循环
├── database.py           # SQLite 数据持久化
├── config.py             # 统一配置加载器
├── memory/               # 向量记忆系统 (ChromaDB)
├── personality/          # 15 维人格系统代理层
├── mcp_client/           # MCP 客户端（工具发现与连接）
├── mcp_server/           # 本地 MCP Server（Tools/Prompts/Resources/Sampling）
├── mcp_modules/          # MCP 模块插件（9 个已集成模块）
├── rules/                # 规则引擎（System Prompt 构建）
└── tools/                # 工具调度中心
    ├── builtin/          # 内建工具
    ├── custom/           # 自定义工具
    └── hardware/         # 硬件工具（PC/手机自动分发）

server/                   # Web 服务器
├── app.py                # FastAPI + WebSocket 主入口（30 个 WS handler）
├── api.py                # REST API 路由
├── templates/            # Jinja2 模板（PC / 移动端 / TTS 工作室）
├── static/               # 前端静态资源（JS / CSS / Spine 动画）
└── settings_manager.py   # 设置管理器

client/                   # 手机端客户端（Termux）
├── client.py             # HTTP 终端交互客户端
└── config/               # 客户端配置

side-projects/            # 第三方子项目
├── personality/          # 15 维人格核心引擎
├── JadeAI/               # 简历 AI
├── presenton/            # PPT 生成
├── ComfyUI/              # AI 绘图
└── Confucius4-TTS/       # 语音合成

config/                   # 配置文件
docs/                     # 文档
migrations/               # Alembic 数据库迁移
scripts/                  # 辅助脚本
tests/                    # 测试
data/                     # 运行时数据（数据库 / 向量库 / 日志）
```

## WebSocket 通信

系统通过 WebSocket 实现全双工实时通信，主要消息类型包括：

- **chat** — 核心对话（支持流式输出 `stream_delta` / `stream_done`）
- **register** — 客户端注册绑定
- **switch_session** — 多会话切换
- **migrate_ack** — 设备迁移握手
- **personality_state** — 人格状态查询
- **wellness_*** — 健康提醒推送
- **reminder_fired** — 定时提醒触发
- **comfyui_* / tts_* / ollama_*** — 外部服务状态管理

## 打包发布

```bash
pyinstaller AI_Agent.spec
```

输出在 `dist/` 目录，可双击 `AI_Agent.exe` 直接运行。

## 安全

- 所有 API Key 仅存在于 `.env`，配置文件不存真实密钥
- 导出/导入设置自动剥离密钥字段
- `.env` 已加入 `.gitignore`，不会提交到仓库
- 人格数据使用加密存储

## 集成项目
语音合成：
ChatTTS：
https://github.com/2noise/ChatTTS
Confucius4-TTS：
https://github.com/netease-youdao/Confucius4-TTS/blob/main/README.zh.md

简历制作：
JadeAI-0.4.1：
https://github.com/LingyiChen-AI/JadeAI

PPT制作：
https://github.com/presenton/presenton

Live2D动画：
https://github.com/ampersante/spine2d-animation-mcp

目标检测：
https://github.com/xzcGit/autolabel-dock

ComfyUI：
https://github.com/Comfy-Org/ComfyUI

## 全工具展示
<img width="1671" height="792" alt="image" src="https://github.com/user-attachments/assets/46fdbb76-7a85-411f-b33c-e4f61d77b1d5" />
<img width="1737" height="1007" alt="image" src="https://github.com/user-attachments/assets/93549c55-5bc8-4767-a131-719df6df8200" />
<img width="666" height="459" alt="image" src="https://github.com/user-attachments/assets/adc486f8-2531-4ad7-afc4-d126a5b48550" />
<img width="1638" height="1233" alt="image" src="https://github.com/user-attachments/assets/993e1df8-f1b1-4d48-8f22-ac6e9d6b8509" />
<img width="633" height="594" alt="image" src="https://github.com/user-attachments/assets/50bb5315-86df-4fa7-9b80-ad6016919a98" />
<img width="732" height="432" alt="image" src="https://github.com/user-attachments/assets/d139b784-ec01-4372-a9c3-a5ba8e6f1dfe" />
<img width="1116" height="495" alt="image" src="https://github.com/user-attachments/assets/6d0e94ec-df68-4eb9-b871-3900a35d8a6a" />
<img width="1134" height="675" alt="image" src="https://github.com/user-attachments/assets/28a17c12-f1e2-4b7c-8471-4c29c588b637" />
<img width="2162" height="840" alt="image" src="https://github.com/user-attachments/assets/7b6baafc-dc17-4fe8-a9a6-2f2b54ae7b03" />
<img width="1119" height="707" alt="image" src="https://github.com/user-attachments/assets/fa00c611-48af-443d-8f98-549583cc67b7" />
<img width="1185" height="384" alt="image" src="https://github.com/user-attachments/assets/969e04b8-fc42-4632-88d9-9cc9f39a31e5" />
<img width="1295" height="627" alt="image" src="https://github.com/user-attachments/assets/d39c4983-49a5-4307-a640-85a6f9b7bbf0" />
<img width="1361" height="644" alt="image" src="https://github.com/user-attachments/assets/6ffb45f1-cf87-4e51-8c12-549a644c0c1a" />
<img width="2175" height="840" alt="image" src="https://github.com/user-attachments/assets/a134201d-7b38-400b-be7c-317ac0f78753" />

## License

见 [LICENSE.md](LICENSE.md)
