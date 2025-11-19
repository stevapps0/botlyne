"""Pydantic models for AI agent typed dependencies and responses."""

from pydantic import BaseModel, Field
from typing import Optional


class AgentDeps(BaseModel):
    """Dependencies injected into agent context."""
    user_id: str = Field(description="User identifier")
    session_id: Optional[str] = Field(None, description="Conversation session ID")
    timezone: str = Field("UTC", description="User timezone for time-aware operations")
    kb_id: Optional[str] = Field(None, description="Knowledge base ID for RAG context")
    kb_context: Optional[str] = Field(None, description="Retrieved knowledge base context")
    sources: Optional[list[dict]] = Field(None, description="Source documents used")


class ToolResult(BaseModel):
    """Structured tool execution result."""
    success: bool = Field(description="Whether tool executed successfully")
    data: str = Field(description="Tool output data")
    error: Optional[str] = Field(None, description="Error message if failed")


class AgentResponse(BaseModel):
    """Structured agent output with metadata."""
    output: str = Field(description="Agent's primary response text")
    reasoning: Optional[str] = Field(None, description="Agent's internal reasoning or thinking")
    tools_used: list[str] = Field(
        default_factory=list,
        description="List of tools called by agent"
    )
    confidence: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Confidence score (0-1) for response quality"
    )


class QueryContext(BaseModel):
    """Context for building agent queries."""
    user_id: str
    session_id: Optional[str] = None
    timezone: str = "UTC"
    kb_id: Optional[str] = None
    relevant_docs: Optional[list[dict]] = None
    conversation_history: Optional[list[dict]] = None
