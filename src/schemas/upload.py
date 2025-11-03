"""Upload and processing schemas."""
from pydantic import BaseModel
from typing import Optional


class UploadResponse(BaseModel):
    """Schema for upload response."""
    batch_id: str
    message: str
    files_processed: int
    urls_processed: int


class ProcessingStatus(BaseModel):
    """Schema for processing status response."""
    batch_id: str
    status: str  # pending, processing, completed, failed
    progress: Optional[int] = None
    total_items: Optional[int] = None
    completed_at: Optional[str] = None