# AI Agent MCP 改造方案

> 版本: v1.0 | 日期: 2026-08-09 | 作者: AI Agent Team

---

## 目录

1. [现状分析](#一现状分析)
2. [目标架构](#二目标架构)
3. [改造策略总览](#三改造策略总览)
4. [Phase 1: 工具层 MCP 标准化](#四phase-1-工具层-mcp-标准化)
5. [Phase 2: Agent 核心 MCP Client 集成](#五phase-2-agent-核心-mcp-client-集成)
6. [Phase 3: 子项目 MCP 统一接入](#六phase-3-子项目-mcp-统一接入)
7. [Phase 4: MCP 高级特性](#七phase-4-mcp-高级特性)
8. [实施时间线](#八实施时间线)
9. [风险与回滚方案](#九风险与回滚方案)

---

## 一、现状分析

### 1.1 当前架构

```
┌──────────────────────────────────────────────────────┐
│                    Web 前端 (Browser)                  │
│                     WebSocket 自定义协议                │
└───────────────────────┬──────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────┐
│              Server (FastAPI + WebSocket)              │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │ REST API     │  │ WS Handler   │  │ 服务管理器   │ │
│  │ /api/*       │  │ 30+ 消息类型 │  │ ComfyUI/TTS │ │
│  └──────────────┘  └──────────────┘  └─────────────┘ │
└───────────────────────┬──────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────┐
│              Agent Core (agent/core.py)                │
│  ┌─────────────────────────────────────────────────┐ │
│  │  ReAct Loop                                      │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │ │
│  │  │ LLM Call │→│ Tool     │→│ Result       │  │ │
│  │  │ (OpenAI) │  │ Execute  │  │ Processing   │  │ │
│  │  └──────────┘  └──────────┘  └──────────────┘  │ │
│  └─────────────────────────────────────────────────┘ │
└───────────────────────┬──────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────┐
│          Tool Registry (agent/tools/__init__.py)       │
│  ┌─────────────────────────────────────────────────┐ │
│  │ TOOLS 列表 (OpenAI function schema)              │ │
│  │ _EXECUTORS 字典 (name → module)                  │ │
│  │ 硬编码 import + 动态 ai_custom 扫描              │ │
│  └─────────────────────────────────────────────────┘ │
│                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │ builtin/ (6) │  │ hardware/ (3)│  │ custom/    │ │
│  │ time weather │  │ mic speaker  │  │ (18 tools) │ │
│  │ calc search   │  │ camera       │  │ PPT TTS    │ │
│  │ migrate diag  │  │              │  │ image YOLO │ │
│  └──────────────┘  └──────────────┘  └────────────┘ │
└──────────────────────────────────────────────────────┘
```

### 1.2 核心问题

| 问题 | 影响 |
|------|------|
| 工具硬编码注册，无法热插拔 | 新增工具需修改 `__init__.py` 的 import 列表 |
| 无标准工具发现协议 | 外部系统无法动态发现可用工具 |
| 子项目集成走文件参数桥接 | PPTAgent 调用链复杂（写 mcp.json → 启动子进程 → 轮询结果） |
| 工具结果无结构化元数据 | 只有字符串返回，缺少错误码/类型信息 |
| 无工具版本管理 | 工具变更后无兼容性保证 |
| 缺少标准化的资源/提示管理 | 文档、模板、system prompt 散落各处 |

### 1.3 已有 MCP 基础设施（可直接复用）

| 组件 | 位置 | 状态 |
|------|------|------|
| `mcp` SDK v1.29.0 | Anaconda 系统环境 | 已安装，可直接使用 |
| `fastmcp` v3.4.6 | Anaconda 系统环境 | 已安装，可直接使用 |
| PPTAgent MCP Server | `tools/PPTAgent/pptagent/` | 已有 FastMCP 2.x 实现 |
| agent-browser MCP | `tools/agent-browser-0.33.2/` | 已有 Rust 原生实现 |
| spine2d MCP | `side-projects/spine2d-animation-mcp/` | 已有 FastMCP 实现 |
| MCPClient 参考实现 | `tools/PPTAgent/deeppresenter/utils/mcp_client.py` | 可参考的 client 模式 |

---

## 二、目标架构

### 2.1 终态架构图

```
┌──────────────────────────────────────────────────────────────┐
│                      Web 前端 / 手机客户端                      │
│              WebSocket (保持现有协议不变)  /  HTTP REST          │
└─────────────────────────┬────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────┐
│            Server (FastAPI) — 协议适配层                        │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  MCP Host (新增)                                          │ │
│  │  ┌─────────────┐  ┌───────────────────────────────────┐  │ │
│  │  │ MCP Client  │  │ MCP Server Manager                │  │ │
│  │  │ (stdio/SSE) │  │ - 启动/停止/监控子进程              │  │ │
│  │  └──────┬──────┘  │ - mcp.json 配置热加载              │  │ │
│  │         │         └───────────────────────────────────┘  │ │
│  └─────────┼────────────────────────────────────────────────┘ │
│            │                                                   │
└────────────┼───────────────────────────────────────────────────┘
             │
     ┌───────┼───────────────────────────────────────┐
     │       │        Agent Core (agent/core.py)     │
     │  ┌────▼──────────────────────────────────┐   │
     │  │  MCP Tool Adapter (新增)               │   │
     │  │  - tools/list → OpenAI schema 转换    │   │
     │  │  - tools/call → execute_tool 路由     │   │
     │  │  - 统一进度/错误/超时处理             │   │
     │  └──────────────────────────────────────┘   │
     └──────────────────────────────────────────────┘
             │
     ┌───────┼───────────────────────────────────────────────┐
     │       ▼                                                │
     │  ┌─────────────────────────────────────────┐          │
     │  │       MCP Tool Bus (新增)                │          │
     │  │  ┌─────────┐  ┌─────────┐  ┌─────────┐ │          │
     │  │  │ Local   │  │ Remote  │  │ External│ │          │
     │  │  │ Tools   │  │ MCP Srv │  │ MCP Srv │ │          │
     │  │  │ (内置)  │  │ (stdio) │  │ (SSE)   │ │          │
     │  │  └─────────┘  └─────────┘  └─────────┘ │          │
     │  └─────────────────────────────────────────┘          │
     └───────────────────────────────────────────────────────┘
             │
     ┌───────┼───────────────────────────────────────────────┐
     │       ▼         工具实现层                             │
     │  ┌──────────────────────────────────────────┐         │
     │  │  Local MCP Server (agent/mcp_server/)     │         │
     │  │  ┌────────┐ ┌────────┐ ┌──────────────┐ │         │
     │  │  │builtin │ │hardware│ │ custom tools │ │         │
     │  │  │ tools  │ │ tools  │ │ (migrated)   │ │         │
     │  │  └────────┘ └────────┘ └──────────────┘ │         │
     │  └──────────────────────────────────────────┘         │
     │                                                        │
     │  ┌──────────────────────────────────────────┐         │
     │  │  External MCP Servers (子进程)            │         │
     │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ │         │
     │  │  │ PPTAgent │ │Browser   │ │ Spire2D  │ │         │
     │  │  │ (已有)   │ │(已有)    │ │ (已有)   │ │         │
     │  │  └──────────┘ └──────────┘ └──────────┘ │         │
     │  └──────────────────────────────────────────┘         │
     └───────────────────────────────────────────────────────┘
```

### 2.2 核心设计原则

1. **渐进式迁移**：不破坏现有功能，新旧工具系统并行运行
2. **向后兼容**：现有 `SCHEMA + execute()` 工具无需修改即可接入
3. **热插拔**：工具可动态加载/卸载，无需重启服务
4. **传输层无关**：工具可在本地进程内调用（直连），也可通过 stdio/SSE 远程调用
5. **统一接口**：无论工具来源，对 Agent 都是统一的 `tools/list` + `tools/call`

---

## 三、改造策略总览

### 3.1 四阶段路线图

```
Phase 1 (Week 1-2): 工具层 MCP 标准化
  ├─ 创建 agent/mcp_server/ 本地 MCP Server
  ├─ 封装现有 30 个工具为 MCP Tools
  ├─ 保持 SCHEMA + execute() 兼容
  └─ 输出: 本地 MCP Server 可独立运行

Phase 2 (Week 3-4): Agent 核心 MCP Client 集成
  ├─ 实现 MCP Tool Adapter
  ├─ Agent Core 通过 tools/list + tools/call 调用工具
  ├─ 保留直连调用作为性能 fallback
  └─ 输出: Agent 支持 MCP 工具发现与调用

Phase 3 (Week 5-6): 子项目 MCP 统一接入
  ├─ 标准化外部 MCP Server 配置 (mcp.json)
  ├─ PPTAgent / agent-browser / spine2d 统一接入
  ├─ MCP Server 进程生命周期管理
  └─ 输出: 多 MCP Server 协同工作

Phase 4 (Week 7-8): MCP 高级特性
  ├─ Resources: 文档/模板/图片资源管理
  ├─ Prompts: 标准化 Prompt 模板
  ├─ Sampling: LLM 采样协商
  └─ 输出: 完整的 MCP 能力矩阵
```

### 3.2 兼容性矩阵

| 功能 | 改造前 | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|------|--------|---------|---------|---------|---------|
| 内置工具调用 | SCHEMA+execute | MCP Tool | MCP Tool | MCP Tool | MCP Tool |
| 工具发现 | 硬编码列表 | tools/list | tools/list | tools/list | tools/list |
| AI 自定义工具 | 动态 import | MCP Tool | MCP Tool | MCP Tool | MCP Tool |
| WebSocket 协议 | 自定义 | 不变 | 不变 | 不变 | 不变 |
| REST API | /api/* | 不变 | 不变 | 不变 | 不变 |
| PPTAgent 调用 | 文件桥接 | 不变 | 不变 | MCP stdio | MCP stdio |
| 前端工具面板 | /api/tools | 不变 | 不变 | 增强 | 增强 |
| 资源管理 | 无 | 无 | 无 | 无 | resources/* |
| Prompt 模板 | 散落 | 无 | 无 | 无 | prompts/* |

---

## 四、Phase 1: 工具层 MCP 标准化

### 4.1 新增目录结构

```
agent/
├── mcp_server/                    # 新增: 本地 MCP Server
│   ├── __init__.py                # 导出 create_local_mcp_server()
│   ├── server.py                  # FastMCP 实例 + 生命周期
│   ├── adapters.py                # SCHEMA→MCP Tool 适配器
│   ├── resources.py               # Phase 4 使用
│   └── prompts.py                 # Phase 4 使用
├── tools/                         # 现有: 保持不变
│   ├── __init__.py                # 小幅修改: 注册表增加 MCP 桥接
│   ├── builtin/
│   ├── hardware/
│   ├── custom/
│   └── ai_custom/
└── core.py                        # Phase 2 修改
```

### 4.2 适配器设计: `adapters.py`

核心思路：**将现有 `SCHEMA + execute()` 自动包装为 FastMCP Tool**

```python
# agent/mcp_server/adapters.py

from typing import Any, Callable
from fastmcp import FastMCP
import functools
import asyncio
import json

def wrap_as_mcp_tool(
    mcp: FastMCP,
    tool_name: str,
    schema: dict,
    execute_fn: Callable,
    need_device: bool = False,
    timeout: float = 60.0,
):
    """
    将现有的 SCHEMA + execute() 工具自动包装为 MCP Tool

    Args:
        mcp: FastMCP 实例
        tool_name: 工具名称 (对应 SCHEMA.function.name)
        schema: OpenAI function schema
        execute_fn: 原始 execute 函数
        need_device: 是否需要注入 current_device
        timeout: 超时秒数
    """
    func_info = schema.get("function", {})
    description = func_info.get("description", "")
    parameters = func_info.get("parameters", {})
    param_props = parameters.get("properties", {})

    # 动态创建带类型注解的函数
    # FastMCP 支持通过 @mcp.tool() 装饰器 + 类型注解自动生成 JSON Schema
    # 但我们已有现成的 JSON Schema，可以用底层 API

    @mcp.tool(
        name=tool_name,
        description=description,
        # 直接传入已有的 JSON Schema 参数定义
    )
    async def tool_impl(**kwargs) -> str:
        """自动生成的 MCP Tool 包装器"""
        loop = asyncio.get_event_loop()

        # 如果需要注入 current_device
        if need_device:
            kwargs["current_device"] = _get_current_device()

        # 在线程池中执行（避免阻塞事件循环）
        result = await loop.run_in_executor(
            None,  # 默认线程池
            lambda: execute_fn(kwargs)
        )

        # 结构化返回
        if isinstance(result, str):
            return result
        elif isinstance(result, dict):
            return json.dumps(result, ensure_ascii=False)
        return str(result)

    return tool_impl
```

**更优雅的方案（推荐）**：使用 FastMCP 的底层注册 API，直接传入 JSON Schema：

```python
# agent/mcp_server/adapters.py (推荐实现)

from fastmcp import FastMCP
from fastmcp.tools import Tool
import asyncio
from concurrent.futures import ThreadPoolExecutor

class ToolAdapter:
    """将现有 SCHEMA+execute 工具适配为 MCP Tool"""

    def __init__(self, mcp: FastMCP):
        self.mcp = mcp
        self._executor = ThreadPoolExecutor(max_workers=4)

    def register(
        self,
        tool_name: str,
        schema: dict,
        execute_fn,
        need_device: bool = False,
        timeout: float = 60.0,
    ):
        """注册一个现有工具为 MCP Tool"""
        func_info = schema.get("function", {})

        # 创建异步包装函数
        async def wrapper(**kwargs) -> str:
            if need_device:
                kwargs["current_device"] = _get_current_device()

            loop = asyncio.get_event_loop()
            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(self._executor, execute_fn, kwargs),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                return f"Error: Tool '{tool_name}' timed out after {timeout}s"

            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False, default=str)

        # 使用 FastMCP Tool 对象注册
        tool = Tool.from_fn(
            fn=wrapper,
            name=tool_name,
            description=func_info.get("description", ""),
            parameters=func_info.get("parameters", {}),
        )
        self.mcp.add_tool(tool)
```

### 4.3 MCP Server 实现: `server.py`

```python
# agent/mcp_server/server.py

from fastmcp import FastMCP
from agent.mcp_server.adapters import ToolAdapter
from agent.tools import TOOLS, _EXECUTORS

# 创建 MCP Server 实例
mcp = FastMCP(
    name="AI-Agent",
    instructions="""
    AI Agent 本地工具服务器。
    提供系统工具、硬件控制、文档生成、AI 模型调用等能力。
    """,
)

# 工具注册
def register_all_tools():
    """从现有工具注册表批量注册到 MCP Server"""
    adapter = ToolAdapter(mcp)

    for tool in TOOLS:
        name = tool.get("function", {}).get("name", "")
        if not name or name not in _EXECUTORS:
            continue

        mod, need_device = _EXECUTORS[name]
        if mod is None:
            continue  # 硬件工具特殊处理

        adapter.register(
            tool_name=name,
            schema=tool,
            execute_fn=mod.execute,
            need_device=need_device,
            timeout=getattr(mod.execute, "_timeout", 60.0),
        )

    # 注册硬件工具
    _register_hardware_tools(adapter)

def _register_hardware_tools(adapter: ToolAdapter):
    """硬件工具的特殊注册（按设备分派）"""
    from agent.tools import _exec_hardware

    for tool_name in ["use_microphone", "use_speaker", "use_camera"]:
        # 从 _TOOLS_SCHEMA 获取对应的 schema
        schema = _HARDWARE_SCHEMAS[tool_name]
        adapter.register(
            tool_name=tool_name,
            schema=schema,
            execute_fn=lambda args, tn=tool_name: _exec_hardware(tn, args),
            need_device=True,
            timeout=120.0,
        )

# 启动入口
def main():
    register_all_tools()
    mcp.run(transport="stdio")  # 或 "sse" 通过环境变量控制

if __name__ == "__main__":
    main()
```

### 4.4 工具注册表增强: `agent/tools/__init__.py` 修改

在现有 `_TOOL_REGISTRY` 基础上增加 MCP 导出能力：

```python
# agent/tools/__init__.py (新增部分)

# === MCP 集成接口 ===

def get_tool_registry() -> list[dict]:
    """
    导出工具注册表，供 MCP Server 使用。
    返回格式:
    [
        {
            "name": "tool_name",
            "schema": {...},        # OpenAI function schema
            "execute": callable,
            "need_device": bool,
            "timeout": float,
            "tag": str,
        },
        ...
    ]
    """
    registry = []
    for tool in TOOLS:
        name = tool.get("function", {}).get("name", "")
        if name in _EXECUTORS:
            mod, need_device = _EXECUTORS[name]
            if mod is not None:
                registry.append({
                    "name": name,
                    "schema": tool,
                    "execute": mod.execute,
                    "need_device": need_device,
                    "timeout": getattr(mod.execute, "_timeout", 60.0),
                    "tag": tool.get("tag", ""),
                })
    return registry
```

### 4.5 Phase 1 验收标准

- [ ] `agent/mcp_server/` 目录创建完成
- [ ] `python -m agent.mcp_server` 可以启动本地 MCP Server
- [ ] 通过 MCP Inspector 或 `fastmcp dev` 可查看所有 30 个工具
- [ ] 现有功能完全不受影响（所有 `import agent.tools` 保持不变）
- [ ] 工具调用结果格式与现有保持一致

---

## 五、Phase 2: Agent 核心 MCP Client 集成

### 5.1 MCP Tool Adapter 设计

```python
# agent/mcp_client/__init__.py

"""
Agent 核心的 MCP Client 集成层。
负责:
1. 连接本地/远程 MCP Server
2. tools/list → OpenAI function schema 转换
3. tools/call → 现有 execute_tool 路由
"""

import asyncio
from typing import Any
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool as MCPTool

class MCPToolManager:
    """管理所有 MCP Server 连接和工具注册"""

    def __init__(self):
        self._sessions: dict[str, ClientSession] = {}
        self._tools: dict[str, tuple[str, MCPTool]] = {}  # tool_name → (server_id, tool)
        self._server_configs: list[dict] = []

    async def connect_local_server(self):
        """连接本地 MCP Server (同进程内的直连模式)"""
        # 方案 A: stdio 子进程
        params = StdioServerParameters(
            command="python",
            args=["-m", "agent.mcp_server"],
        )
        transport = await stdio_client(params)
        session = await ClientSession(transport[0], transport[1])
        await session.initialize()
        self._sessions["local"] = session
        await self._discover_tools("local")

        # 方案 B: 进程内直连（性能优化，跳过 stdio）
        # 直接 import agent.mcp_server 并调用其内部 API

    async def connect_remote_server(self, server_id: str, config: dict):
        """连接远程 MCP Server (SSE 或 stdio)"""
        if config.get("command"):
            # stdio 模式
            params = StdioServerParameters(
                command=config["command"],
                args=config.get("args", []),
                env=config.get("env"),
            )
            transport = await stdio_client(params)
        elif config.get("url"):
            # SSE 模式
            from mcp.client.sse import sse_client
            transport = await sse_client(config["url"])
        else:
            raise ValueError(f"Invalid config for {server_id}")

        session = await ClientSession(transport[0], transport[1])
        await session.initialize()
        self._sessions[server_id] = session
        await self._discover_tools(server_id)

    async def _discover_tools(self, server_id: str):
        """发现并注册 MCP Server 的所有工具"""
        session = self._sessions[server_id]
        result = await session.list_tools()

        for tool in result.tools:
            # 如果工具名冲突，以后注册的为准（或按优先级）
            self._tools[tool.name] = (server_id, tool)

    def get_openai_tools(self) -> list[dict]:
        """
        将所有 MCP 工具转换为 OpenAI function calling 格式。
        这是关键桥接点: MCP Tool → OpenAI Schema
        """
        openai_tools = []
        for tool_name, (server_id, mcp_tool) in self._tools.items():
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": mcp_tool.name,
                    "description": mcp_tool.description or "",
                    "parameters": mcp_tool.inputSchema,  # JSON Schema
                },
            })
        return openai_tools

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """
        调用 MCP 工具。Agent Core 通过此方法执行工具。
        """
        if tool_name not in self._tools:
            # 回退到本地直连工具
            return await self._call_local_tool(tool_name, arguments)

        server_id, mcp_tool = self._tools[tool_name]
        session = self._sessions[server_id]

        try:
            result = await session.call_tool(tool_name, arguments)
            # MCP 返回的是 CallToolResult，包含 content 列表
            return _extract_text_content(result.content)
        except Exception as e:
            return f"Error calling tool '{tool_name}': {e}"

    async def _call_local_tool(self, tool_name: str, arguments: dict) -> str:
        """回退到现有 execute_tool 机制（保证兼容）"""
        from agent.tools import execute_tool
        return execute_tool(tool_name, arguments)
```

### 5.2 Agent Core 修改: `agent/core.py`

```python
# agent/core.py (修改部分)

from agent.mcp_client import MCPToolManager

# 全局 MCP 工具管理器（在 run_agent 外初始化，避免重复连接）
_mcp_manager: MCPToolManager | None = None

async def init_mcp():
    """初始化 MCP 连接（在服务启动时调用一次）"""
    global _mcp_manager
    _mcp_manager = MCPToolManager()
    await _mcp_manager.connect_local_server()

    # 加载外部 MCP Server 配置
    mcp_config = load_mcp_config()  # 从 mcp.json 或 config.yaml
    for server_id, config in mcp_config.get("servers", {}).items():
        if config.get("enabled", True):
            await _mcp_manager.connect_remote_server(server_id, config)

async def run_agent(messages, session_id, ...):
    # 获取工具列表（优先 MCP，回退现有）
    if _mcp_manager and _mcp_manager._tools:
        tools_for_llm = _mcp_manager.get_openai_tools()
    else:
        tools_for_llm = TOOLS_FOR_LLM  # 现有 fallback

    while iteration < max_iterations:
        # ... LLM 调用逻辑不变 ...

        if tool_calls:
            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)

                # 执行工具（优先 MCP，回退现有）
                if _mcp_manager and tool_name in _mcp_manager._tools:
                    result = await _mcp_manager.call_tool(tool_name, arguments)
                else:
                    result = execute_tool(tool_name, arguments)

                # ... 结果处理不变 ...
```

### 5.3 Server 启动流程修改: `server/app.py`

```python
# server/app.py (新增启动逻辑)

from agent.core import init_mcp

@app.on_event("startup")
async def startup():
    # ... 现有启动逻辑 ...

    # 初始化 MCP 连接
    try:
        await init_mcp()
        logger.info("MCP initialized successfully")
    except Exception as e:
        logger.warning(f"MCP init failed, falling back to direct tools: {e}")
```

### 5.4 Phase 2 验收标准

- [ ] Agent 可通过 MCP `tools/list` 获取工具列表
- [ ] Agent 可通过 MCP `tools/call` 执行工具
- [ ] MCP 不可用时自动回退到直连模式
- [ ] 工具调用延迟增加不超过 50ms（本地直连模式）
- [ ] 所有 30 个工具通过 MCP 调用结果与直连一致
- [ ] WebSocket 进度推送在 MCP 模式下正常

---

## 六、Phase 3: 子项目 MCP 统一接入

### 6.1 MCP 配置文件标准化: `config/mcp.json`

```json
{
  "mcpServers": {
    "local-tools": {
      "type": "embedded",
      "description": "AI Agent 内置工具集"
    },
    "pptagent": {
      "command": "python",
      "args": ["-m", "pptagent.mcp_server"],
      "cwd": "./tools/PPTAgent",
      "description": "PPT 生成服务 (DeepPresenter-9B)",
      "enabled": true,
      "env": {
        "PYTHONPATH": "./tools/PPTAgent"
      },
      "startupTimeout": 30000,
      "toolFilter": {
        "include": ["create_slide", "generate_slide", "save_generated_slides"]
      }
    },
    "agent-browser": {
      "command": "npx",
      "args": ["agent-browser", "mcp", "--tools", "core,network"],
      "description": "浏览器自动化工具",
      "enabled": true,
      "toolFilter": {
        "exclude": ["screenshot_full_page"]
      }
    },
    "spine2d": {
      "command": "python",
      "args": ["-m", "spine2d_mcp.server"],
      "cwd": "./side-projects/spine2d-animation-mcp-main",
      "description": "PSD 转 Spine 动画",
      "enabled": false,
      "startupTimeout": 10000
    }
  }
}
```

### 6.2 MCP Server 生命周期管理

```python
# agent/mcp_client/server_manager.py

import asyncio
import subprocess
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

@dataclass
class MCPServerConfig:
    id: str
    command: str
    args: list[str] = field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    startup_timeout: float = 30.0
    restart_on_failure: bool = True
    max_restarts: int = 3

class MCPServerManager:
    """管理外部 MCP Server 进程的生命周期"""

    def __init__(self):
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._sessions: dict[str, ClientSession] = {}
        self._restart_counts: dict[str, int] = {}
        self._health_check_tasks: dict[str, asyncio.Task] = {}

    async def start_server(self, config: MCPServerConfig) -> bool:
        """启动一个外部 MCP Server 进程"""
        try:
            # 使用 stdio_client 自动管理子进程
            params = StdioServerParameters(
                command=config.command,
                args=config.args,
                env={**os.environ, **config.env} if config.env else None,
            )

            transport = await asyncio.wait_for(
                stdio_client(params),
                timeout=config.startup_timeout,
            )

            session = await ClientSession(transport[0], transport[1])
            init_result = await session.initialize()

            self._sessions[config.id] = session
            logger.info(
                f"MCP Server '{config.id}' started: "
                f"{init_result.serverInfo.name} v{init_result.serverInfo.version}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to start MCP Server '{config.id}': {e}")
            return False

    async def stop_server(self, server_id: str):
        """停止 MCP Server"""
        if server_id in self._sessions:
            session = self._sessions.pop(server_id)
            # 发送关闭通知
            try:
                await session.send_notification("notifications/cancelled", {})
            except Exception:
                pass

        if server_id in self._health_check_tasks:
            self._health_check_tasks.pop(server_id).cancel()

        logger.info(f"MCP Server '{server_id}' stopped")

    async def restart_server(self, server_id: str):
        """重启 MCP Server"""
        await self.stop_server(server_id)
        config = self._get_config(server_id)
        if config:
            return await self.start_server(config)
        return False

    async def health_check_loop(self, server_id: str, interval: float = 30.0):
        """定期健康检查"""
        while True:
            await asyncio.sleep(interval)
            try:
                session = self._sessions.get(server_id)
                if session:
                    await asyncio.wait_for(session.send_ping(), timeout=5.0)
            except Exception:
                logger.warning(f"MCP Server '{server_id}' health check failed")
                if self._restart_counts.get(server_id, 0) < 3:
                    self._restart_counts[server_id] = \
                        self._restart_counts.get(server_id, 0) + 1
                    await self.restart_server(server_id)
```

### 6.3 与 PPTAgent Bridge 的平滑过渡

保留现有 `pptagent_bridge.py` 作为 MCP fallback，同时增加 MCP 路径：

```python
# agent/tools/custom/pptagent_bridge.py (新增部分)

# 在 execute() 开头增加 MCP 路径检测
def execute(arguments: dict) -> str:
    """
    PPT 生成工具。
    优先通过 MCP 调用，MCP 不可用时回退到现有桥接模式。
    """
    from agent.mcp_client import _mcp_manager

    # 尝试 MCP 路径
    if _mcp_manager and "pptagent" in _mcp_manager._sessions:
        try:
            result = asyncio.run(
                _mcp_manager.call_tool("create_slide", arguments)
            )
            return result
        except Exception as e:
            logger.warning(f"MCP pptagent call failed: {e}, falling back")

    # 回退到现有桥接模式
    return _legacy_bridge_execute(arguments)
```

### 6.4 Phase 3 验收标准

- [ ] `config/mcp.json` 配置文件可用
- [ ] 通过配置可动态启用/禁用外部 MCP Server
- [ ] PPTAgent 通过 MCP stdio 调用成功（与现有桥接结果一致）
- [ ] agent-browser 通过 MCP stdio 调用成功
- [ ] 外部 MCP Server 崩溃后自动重启（3 次限制）
- [ ] 工具冲突时有明确的优先级规则
- [ ] `/api/tools` 接口显示工具来源（本地/远程）

---

## 七、Phase 4: MCP 高级特性

### 7.1 Resources: 文档与模板管理

```python
# agent/mcp_server/resources.py

@mcp.resource("paper://templates/{name}")
def get_paper_template(name: str) -> str:
    """获取论文 LaTeX 模板"""
    ...

@mcp.resource("config://system")
def get_system_config() -> str:
    """获取系统配置"""
    ...

@mcp.resource("memory://session/{session_id}")
def get_session_context(session_id: str) -> str:
    """获取会话上下文摘要"""
    ...
```

### 7.2 Prompts: 标准化 Prompt 模板

```python
# agent/mcp_server/prompts.py

@mcp.prompt()
def code_review(code: str, language: str = "python") -> str:
    """代码审查 Prompt 模板"""
    return f"""请审查以下 {language} 代码:
    
{code}

请关注:
1. 代码正确性
2. 性能优化建议
3. 安全漏洞
4. 最佳实践
"""

@mcp.prompt()
def paper_writing(topic: str, style: str = "academic") -> list:
    """论文写作 Prompt 模板（多消息）"""
    return [
        {"role": "system", "content": f"你是{style}论文写作助手"},
        {"role": "user", "content": f"请帮我写关于'{topic}'的论文大纲"},
    ]
```

### 7.3 Sampling: LLM 采样协商

利用 MCP Sampling 能力让工具在需要时请求 LLM 辅助：

```python
@mcp.tool()
async def generate_with_review(content: str) -> str:
    """生成内容并自我审查"""
    # 第一步：生成
    result = await mcp.request_sampling(
        messages=[{"role": "user", "content": f"生成关于 {content} 的内容"}],
        max_tokens=1000,
    )
    
    # 第二步：审查
    review = await mcp.request_sampling(
        messages=[
            {"role": "user", "content": f"审查以下内容的质量:\n{result.content}"}
        ],
        max_tokens=500,
    )
    
    return f"内容:\n{result.content}\n\n审查意见:\n{review.content}"
```

### 7.4 Phase 4 验收标准

- [ ] 至少 5 个 Resources 端点可用
- [ ] 至少 3 个 Prompt 模板可用
- [ ] Sampling 能力在至少 1 个工具中可用
- [ ] `/api/resources` 和 `/api/prompts` 端点可用

---

## 八、实施时间线

```
Week 1-2  ████████████  Phase 1: 工具层 MCP 标准化
          ├─ Day 1-3: 创建 agent/mcp_server/ 框架
          ├─ Day 4-7: 实现适配器，注册所有 30 个工具
          ├─ Day 8-10: 测试、修复兼容性问题
          └─ Day 11-14: 文档 + 代码审查

Week 3-4  ████████████  Phase 2: Agent 核心 MCP Client 集成
          ├─ Day 1-3: 实现 MCPToolManager
          ├─ Day 4-7: 修改 agent/core.py 集成 MCP
          ├─ Day 8-10: 回退机制 + 性能测试
          └─ Day 11-14: 全量回归测试

Week 5-6  ████████████  Phase 3: 子项目 MCP 统一接入
          ├─ Day 1-3: mcp.json 配置 + ServerManager
          ├─ Day 4-7: PPTAgent MCP 接入 + 测试
          ├─ Day 8-10: agent-browser + spine2d 接入
          └─ Day 11-14: 压力测试 + 稳定性测试

Week 7-8  ████████████  Phase 4: MCP 高级特性
          ├─ Day 1-3: Resources 实现
          ├─ Day 4-6: Prompts 实现
          ├─ Day 7-9: Sampling 实现
          └─ Day 10-14: 文档 + 发布
```

---

## 九、风险与回滚方案

### 9.1 风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| FastMCP SDK 版本不兼容 | 中 | 高 | 锁定版本，使用 Anaconda 已验证的 mcp 1.29.0 + fastmcp 3.4.6 |
| 工具调用延迟增加 | 中 | 中 | 本地工具用进程内直连模式，跳过 stdio 开销 |
| MCP 子进程崩溃 | 高 | 中 | 健康检查 + 自动重启 + 回退机制 |
| 现有 WebSocket 协议受影响 | 低 | 高 | MCP 仅在工具层生效，WS 层完全不变 |
| PPTAgent MCP 版本差异 | 高 | 中 | PPTAgent 使用 FastMCP 2.x，需单独隔离环境 |
| 工具名称冲突 | 中 | 低 | 命名空间前缀 + 优先级规则 |

### 9.2 回滚方案

```
┌─────────────────────────────────────────────┐
│           回滚开关设计                        │
│                                              │
│  config.yaml:                                │
│    mcp:                                      │
│      enabled: true/false    ← 一键关闭 MCP   │
│      fallback: direct       ← 自动回退直连   │
│                                              │
│  环境变量:                                   │
│    MCP_ENABLED=0             ← 紧急回滚       │
│                                              │
│  运行时:                                     │
│    POST /api/mcp/disable     ← 运行时关闭    │
│    POST /api/mcp/enable      ← 运行时开启    │
└─────────────────────────────────────────────┘
```

### 9.3 测试策略

```
Phase 1: 单元测试 (每个工具的 MCP 包装器)
Phase 2: 集成测试 (Agent 通过 MCP 完成端到端对话)
Phase 3: 系统测试 (多 MCP Server 协同 + 故障注入)
Phase 4: 性能测试 (延迟/吞吐量对比)

回归测试套件:
- 所有 30 个工具的功能测试
- 10 个典型对话场景的端到端测试
- 工具启用/禁用动态测试
- WebSocket 协议兼容性测试
- 手机端 REST API 兼容性测试
```

---

## 附录 A: 关键文件清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `agent/mcp_server/__init__.py` | MCP Server 包入口 |
| `agent/mcp_server/server.py` | FastMCP 实例 + 启动逻辑 |
| `agent/mcp_server/adapters.py` | SCHEMA→MCP Tool 适配器 |
| `agent/mcp_server/resources.py` | Resources 定义 (Phase 4) |
| `agent/mcp_server/prompts.py` | Prompts 定义 (Phase 4) |
| `agent/mcp_client/__init__.py` | MCPToolManager 实现 |
| `agent/mcp_client/server_manager.py` | MCP 子进程管理 |
| `config/mcp.json` | MCP Server 配置文件 |

### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `agent/tools/__init__.py` | 增加 `get_tool_registry()` 导出接口 |
| `agent/core.py` | 集成 MCPToolManager，增加 MCP 调用路径 |
| `server/app.py` | 启动时初始化 MCP 连接 |
| `config.yaml` | 增加 `mcp:` 配置段 |
| `agent/tools/custom/pptagent_bridge.py` | 增加 MCP 调用路径（保留回退） |

---

## 附录 B: 依赖版本

```txt
# requirements-mcp.txt (新增)
mcp>=1.14.0,<2.0.0       # MCP Python SDK (与 PPTAgent 兼容)
fastmcp>=3.0.0,<4.0.0    # FastMCP 框架 (系统已安装 3.4.6)
```

注意：PPTAgent 子项目锁定 `fastmcp>=2.10.0,<2.14.0`（老版本），需要独立 venv 隔离，不与主项目的 fastmcp 3.x 冲突。

---

> **下一步行动**: 确认方案后，从 Phase 1 开始逐步实施。建议先在 `feature/mcp-migration` 分支上进行，通过所有测试后合并到主分支。
