from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional
import os
import uuid
import logging

# Import existing modules
from src.archive.extract import ItemProcessor, Config as ExtractConfig
from src.archive.transform import vectorize_and_chunk
from src.archive.load import load_to_supabase

# Initialize logging
logger = logging.getLogger(__name__)

from src.core.database import supabase
from src.core.config import settings

# Pydantic models for dependencies
class TokenData(BaseModel):
    user_id: str
    org_id: str | None = None

# Dependency to get current user
async def get_current_user(token: str = Depends(lambda: None)):
    """Extract and validate user from JWT token."""
    try:
        # This is a simplified version - in real implementation you'd validate the token
        # For now, return a mock user
        return TokenData(user_id="mock_user", org_id="mock_org")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed"
        )

router = APIRouter()

# Pydantic models
class UploadResponse(BaseModel):
    batch_id: str
    message: str
    files_processed: int
    urls_processed: int

class ProcessingStatus(BaseModel):
    batch_id: str
    status: str  # pending, processing, completed, failed
    progress: Optional[int] = None
    total_items: Optional[int] = None
    completed_at: Optional[str] = None

# In-memory status tracking (use Redis/DB for production)
processing_status = {}

async def process_batch_async(batch_id: str, kb_id: str, files_data: List[dict], urls: List[str]):
    """Background task to process uploaded files and URLs"""
    try:
        processing_status[batch_id] = ProcessingStatus(
            batch_id=batch_id,
            status="processing",
            progress=0,
            total_items=len(files_data) + len(urls)
        )

        total_processed = 0

        # Process files
        for file_data in files_data:
            try:
                # Extract content
                processed = await ItemProcessor.process(file_data, str(uuid.uuid4()))
                if processed.status == "success":
                    # Transform and load
                    vectorized_data = vectorize_and_chunk(processed.content, {"source": file_data["filename"]})
                    load_to_supabase(vectorized_data, kb_id)
                total_processed += 1
                processing_status[batch_id].progress = total_processed
            except Exception as e:
                logger.error(f"Failed to process file {file_data['filename']}: {e}")

        # Process URLs
        for url in urls:
            try:
                # Extract content
                processed = await ItemProcessor.process(url, str(uuid.uuid4()))
                if processed.status == "success":
                    # Transform and load
                    vectorized_data = vectorize_and_chunk(processed.content, {"source": url})
                    load_to_supabase(vectorized_data, kb_id)
                total_processed += 1
                processing_status[batch_id].progress = total_processed
            except Exception as e:
                logger.error(f"Failed to process URL {url}: {e}")

        processing_status[batch_id].status = "completed"
        processing_status[batch_id].completed_at = "now"

    except Exception as e:
        logger.error(f"Batch processing failed: {e}")
        processing_status[batch_id].status = "failed"

@router.post("/kbs/{kb_id}/upload", response_model=UploadResponse)
async def upload_knowledge(
    kb_id: str,
    background_tasks: BackgroundTasks,
    files: Optional[List[UploadFile]] = File(None),
    urls: Optional[List[str]] = None,
    current_user: TokenData = Depends(get_current_user)
):
    """Upload files and URLs to knowledge base"""
    try:
        # Verify KB access
        kb_check = supabase.table("knowledge_bases").select("org_id").eq("id", kb_id).single().execute()
        if not kb_check.data or kb_check.data["org_id"] != current_user.org_id:
            raise HTTPException(status_code=403, detail="Access denied")

        batch_id = str(uuid.uuid4())
        files_data = []
        urls_list = urls or []

        # Process uploaded files
        if files:
            for file in files:
                if file.size and file.size > settings.MAX_FILE_SIZE:
                    raise HTTPException(status_code=400, detail=f"File {file.filename} exceeds max size")

                content = await file.read()
                files_data.append({
                    "filename": file.filename,
                    "content": content
                })

        if not files_data and not urls_list:
            raise HTTPException(status_code=400, detail="No files or URLs provided")

        # Start background processing
        background_tasks.add_task(process_batch_async, batch_id, kb_id, files_data, urls_list)

        # Record files in database
        for file_data in files_data:
            file_record = {
                "kb_id": kb_id,
                "filename": file_data["filename"],
                "file_type": file_data["filename"].split(".")[-1] if "." in file_data["filename"] else "unknown",
                "size_bytes": len(file_data["content"]),
                "uploaded_by": current_user.user_id
            }
            supabase.table("files").insert(file_record).execute()

        for url in urls_list:
            file_record = {
                "kb_id": kb_id,
                "filename": url,
                "url": url,
                "file_type": "url",
                "uploaded_by": current_user.user_id
            }
            supabase.table("files").insert(file_record).execute()

        return UploadResponse(
            batch_id=batch_id,
            message="Upload initiated. Processing in background.",
            files_processed=len(files_data),
            urls_processed=len(urls_list)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Upload failed"
        )

@router.get("/upload/status/{batch_id}", response_model=ProcessingStatus)
async def get_upload_status(
    batch_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """Get processing status for an upload batch"""
    if batch_id not in processing_status:
        raise HTTPException(status_code=404, detail="Batch not found")

    return processing_status[batch_id]

@router.get("/kbs/{kb_id}/files")
async def list_kb_files(
    kb_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """List all files in a knowledge base"""
    try:
        # Verify KB access
        kb_check = supabase.table("knowledge_bases").select("org_id").eq("id", kb_id).single().execute()
        if not kb_check.data or kb_check.data["org_id"] != current_user.org_id:
            raise HTTPException(status_code=403, detail="Access denied")

        result = supabase.table("files").select("*").eq("kb_id", kb_id).execute()
        return {"files": result.data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to list files: {str(e)}"
        )