"""Query and conversation schemas."""
from pydantic import BaseModel
from typing import List, Optional


class QueryRequest(BaseModel):
    """Schema for query request."""
    query: str
    kb_id: str
    conversation_id: Optional[str] = None  # For continuing conversations


class QueryResponse(BaseModel):
    """Schema for query response."""
    conversation_id: str
    user_message: str
    ai_response: str
    sources: List[dict]
    response_time: float
    handoff_triggered: bool = False


class ConversationResponse(BaseModel):
    """Schema for conversation response."""
    id: str
    kb_id: str
    messages: List[dict]
    status: str
    started_at: str
    resolved_at: Optional[str] = None