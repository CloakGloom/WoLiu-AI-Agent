"""
Pydantic 请求/响应 Schema —— 统一校验与 OpenAPI 文档自动生成
"""
from pydantic import BaseModel, Field
from typing import Optional, List


# ── 聊天 ──
class ChatRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000, description="用户消息内容")
    device: Optional[str] = Field(default=None, pattern="^(电脑|手机)$", description="发送者设备")


class ChatResponse(BaseModel):
    reply: str
    session_id: str


# ── 会话 ──
class CreateSessionRequest(BaseModel):
    device: str = Field(default="手机", pattern="^(电脑|手机)$")


class PinSessionRequest(BaseModel):
    pinned: bool = True


class RenameSessionRequest(BaseModel):
    title: str = Field(default="", max_length=100)


class BatchDeleteRequest(BaseModel):
    session_ids: List[str] = Field(..., min_length=1)


# ── 规则 / 人格 / 工具 ──
class RuleUpdateRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=100)
    value: str = Field(..., max_length=5000)


class PersonalityUpdateRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=100)
    value: str = Field(..., max_length=5000)


class ToolToggleRequest(BaseModel):
    tool_name: str = Field(..., min_length=1)
    disabled: bool


# ── 迁移 ──
class MigrateRequest(BaseModel):
    target_device: str = Field(..., pattern="^(电脑|手机)$")


# ── 配置 ──
class ConfigUpdateRequest(BaseModel):
    key: str
    value: str
