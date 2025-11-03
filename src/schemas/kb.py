"""Knowledge base schemas."""
from pydantic import BaseModel
from typing import List


class CreateKBRequest(BaseModel):
    """Schema for knowledge base creation request."""
    name: str


class KBResponse(BaseModel):
    """Schema for knowledge base response."""
    id: str
    org_id: str
    name: str
    created_at: str


class KBListResponse(BaseModel):
    """Schema for knowledge base list response."""
    id: str
    name: str
    created_at: str
    document_count: int = 0