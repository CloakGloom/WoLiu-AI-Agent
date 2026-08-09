# WoLiu AI Agent

个人 AI 伴侣 —— FastAPI + WebSocket 后端、ReAct Agent 循环、15 维演化人格、MCP 可插拔工具体系、长期向量记忆。

## 架构一览

```
聊天输入 → ReAct Agent 循环 → LLM (OpenAI 兼容)
              │
  ┌───────────┼───────────┐
  ▼           ▼           ▼
MCP 工具    15维人格     向量记忆
 (可插拔)   (动态演化)   (ChromaDB)
  │
  ├── ComfyUI (图/视频生成)
  ├── ChatTTS (语音合成)
  ├── Presenton (PPT 生成)
  ├── JadeAI  (简历生成)
  ├── 提醒系统 (定时推送)
  └── 健康提醒 (喝水/吃饭)
```

| 特性 | 说明 |
|------|------|
| ReAct Agent | 基于 OpenAI SDK，流式输出 + 工具调用 |
| 15 维演化人格 | warmth / sarcasm / sexual_openness 等，随对话自动演化 |
| 长期记忆 | ChromaDB 向量库 + sentence-transformers RAG |
| MCP 工具体系 | 文件夹即模块、本地 + 外部 MCP Server、自动发现 |
| Web UI | 双主题（日间渐变 / 夜间星空）、玻璃拟态、雷达图 |
| Android | 轻量 WebView 客户端 |
| 可插拔 | 人格系统一键开关 (`config/settings.json` → `personality_enabled`) |

## 快速开始

```bash
# 1. 环境
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY 等，或启动后在设置页 UI 填写

# 3. 启动
python run_server.py
```

Web UI → `http://localhost:8000`

## 项目结构

```
agent/
├── core.py                  # ReAct Agent 循环
├── tools/custom/            # MCP 工具
│   ├── image_generation.py  # 写实/动漫/视频三模型绘画
│   ├── reminder.py          # 定时提醒
│   └── drawing_model_config.py  # 模型路径+下载配置
├── mcp_modules/             # 可插拔 MCP 模块
│   ├── personality/         # 15 维人格模块
│   ├── comfyui/             # AI 绘画
│   ├── tts/                 # 语音合成
│   └── ...
├── personality/             # 代理层 → side-projects/personality/
├── memory/                  # ChromaDB 向量记忆
└── rules/                   # AI 规则引擎

server/
├── app.py                   # FastAPI + WebSocket 主入口
├── static/                  # 前端 JS/CSS
├── templates/               # Jinja2 HTML
└── settings_manager.py      # 设置管理（密钥分离）

side-projects/
└── personality/             # 15 维人格核心
    ├── dimensions.py        # 15 维定义 + 演化规则
    ├── evolution.py         # 演化引擎
    ├── filter.py            # 输出过滤
    ├── generator.py         # Prompt 生成
    ├── wellness.py          # 健康提醒调度器
    └── state.py             # 加密状态存储
```

## 安全

- 所有 API Key 写入 `.env`，`settings.json` 不存真实密钥
- 导出/导入设置自动去除密钥字段
- `.env` / `.gitignore` 排除，不会提交到仓库
- 人格数据加密存储

## License

见 [LICENSE.md](LICENSE.md)
