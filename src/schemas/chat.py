"""Chat integration schemas for webapp chat functionality."""
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Literal
from datetime import datetime
import uuid


class ChatMessage(BaseModel):
    """Individual chat message."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique message ID")
    role: Literal["user", "assistant"] = Field(..., description="Message sender role")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Message timestamp")

    @validator('content')
    def validate_content(cls, v):
        if not v or not v.strip():
            raise ValueError('Message content cannot be empty')
        if len(v) > 10000:  # Reasonable limit
            raise ValueError('Message content too long (max 10000 characters)')
        return v.strip()


class ChatSession(BaseModel):
    """Chat session container."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique session ID")
    org_id: str = Field(..., description="Organization ID")
    kb_id: Optional[str] = Field(None, description="Knowledge base ID")
    integration_id: Optional[str] = Field(None, description="Integration ID if applicable")
    messages: List[ChatMessage] = Field(default_factory=list, description="Conversation messages")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Session creation time")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update time")
    is_active: bool = Field(True, description="Whether session is active")

    @validator('messages')
    def validate_messages(cls, v):
        if len(v) > 100:  # Prevent excessive message history
            raise ValueError('Too many messages in session (max 100)')
        return v


class ChatRequest(BaseModel):
    """Request to send a chat message."""
    message: str = Field(..., description="User message content")
    session_id: Optional[str] = Field(None, description="Existing session ID, creates new if not provided")
    stream: bool = Field(False, description="Whether to stream the response")

    @validator('message')
    def validate_message(cls, v):
        return ChatMessage(role="user", content=v).content  # Reuse validation


class ChatResponse(BaseModel):
    """Response from chat API."""
    session_id: str = Field(..., description="Chat session ID")
    message: ChatMessage = Field(..., description="AI response message")
    sources: Optional[List[dict]] = Field(None, description="Source documents/references")
    response_time: float = Field(..., description="Response generation time in seconds")
    handoff_triggered: bool = Field(False, description="Whether human handoff was triggered")


class ChatSessionSummary(BaseModel):
    """Summary of a chat session."""
    id: str
    org_id: str
    kb_id: Optional[str]
    message_count: int
    created_at: datetime
    updated_at: datetime
    is_active: bool


class StreamingChatResponse(BaseModel):
    """Streaming response chunk."""
    chunk: str = Field(..., description="Response text chunk")
    finished: bool = Field(False, description="Whether this is the final chunk")
    sources: Optional[List[dict]] = Field(None, description="Sources (included in final chunk)")
    response_time: Optional[float] = Field(None, description="Total response time (in final chunk)")