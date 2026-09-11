"""Pydantic request models shared by the FastAPI routes."""

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    reset: bool = False


class SessionRequest(BaseModel):
    session_id: str | None = None


class CancelRequest(BaseModel):
    session_id: str = Field(min_length=1)


class TaskCreateRequest(BaseModel):
    subject: str = Field(min_length=1)
    description: str = ""
    blockedBy: list[str] = Field(default_factory=list)
    priority: Literal["low", "medium", "high"] = "medium"


class TaskClaimRequest(BaseModel):
    owner: str = "agent"


class TaskCompleteRequest(BaseModel):
    result: str = ""


class CronCreateRequest(BaseModel):
    cron: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    recurring: bool = True
    name: str = ""
    description: str = ""
    enabled: bool = True


class MCPNameRequest(BaseModel):
    name: str = Field(min_length=1)


class MCPCustomServerRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    tools: list[dict] = Field(min_length=1)


class MCPStdioConnectRequest(BaseModel):
    name: str = Field(min_length=1)
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None


class MCPSseConnectRequest(BaseModel):
    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
