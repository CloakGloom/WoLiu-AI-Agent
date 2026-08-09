# AI Agent

一个个人 AI Agent 伴侣/助手系统：FastAPI + WebSocket 后端、ReAct Agent 循环、向量长期记忆、MCP 工具体系与人格系统，支持电脑端 Web 与 Android 客户端。

## 功能特性

- **ReAct Agent 循环**：基于 OpenAI SDK 调用兼容 API（默认 SiliconFlow DeepSeek-V3），支持流式输出与工具调用
- **长期记忆**：ChromaDB 向量库 + sentence-transformers 嵌入的 RAG 记忆系统
- **MCP 工具体系**：本地 MCP Server + 外部 MCP Server，可回退直连模式；含 PPT 生成（Presenton）、简历生成（JadeAI 反向代理 + Ollama 视觉质检）、天气、邮件、文件转换等工具
- **人格系统**：事件驱动的人格状态与回复风格过滤
- **Web UI**：双主题切换（日间渐变/夜间星空）、玻璃拟态弹窗、粒子与星星交互动画
- **Android 客户端**：轻量 WebView 客户端，连接同一后端
- **集成服务**：ComfyUI（图生视频）、ChatTTS / Confucius4-TTS 语音合成、微信桥接、Ollama 本地模型

## 技术栈

- **后端**：Python 3.12、FastAPI、Uvicorn、WebSocket
- **LLM**：OpenAI 兼容 API（SiliconFlow）、Tavily 搜索
- **记忆**：ChromaDB、sentence-transformers
- **文档**：python-pptx、python-docx、PyMuPDF
- **数据库迁移**：SQLAlchemy + Alembic
- **CI**：GitHub Actions（pytest + pylint）

## 目录结构

```
agent/          # Agent 核心：ReAct 循环、工具、记忆、人格、规则、MCP
server/         # FastAPI 服务、静态前端、代理与 API
client/         # 客户端连接层
android/        # Android WebView 客户端
config/         # JSON 配置（MCP、工具、规则、自启动）
migrations/     # Alembic 数据库迁移
scripts/        # 辅助脚本（备份、检查、测试）
tests/          # pytest 单元测试
docs/           # 架构文档
data/           # 运行时数据（不入库，自动创建）
```

## 快速开始

### 1. 准备环境

需要 Python 3.12+：

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key
```

### 3. 启动服务

```bash
python run_server.py
```

- Web UI：`http://localhost:8081`
- WebSocket：`ws://localhost:8765`

也可双击 `launcher.py` 启动（会自动寻找 `Anaconda/Scripts/python.exe`）。

### 4. 运行测试

```bash
python -m pytest tests/ -v
```

## 配置

统一配置见 `config.yaml`（复制为 `config.local.yaml` 做本地定制，不受 Git 追踪），包含 LLM、视觉模型、外部服务（ComfyUI / TTS / Ollama / JadeAI）、MCP 开关、上传限制等。

## License

见 [LICENSE.md](LICENSE.md)。
