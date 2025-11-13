from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File, BackgroundTasks, Header
from pydantic import BaseModel
from typing import List, Optional
import os
import uuid
import logging
from datetime import datetime

# Import existing modules
from src.archive.extract import ItemProcessor, Config as ExtractConfig
from src.archive.transform import vectorize_and_chunk
from src.archive.load import load_to_supabase
from src.core.auth_utils import TokenData, validate_bearer_token

# Initialize logging
logger = logging.getLogger(__name__)

from src.core.database import supabase, supabase_storage
from src.core.config import settings

# Dependency to get current user
async def get_current_user(authorization: str = Header(None, alias="Authorization")) -> TokenData:
    """Extract and validate user from JWT token or API key."""
    try:
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required"
            )
        
        token = authorization.replace("Bearer ", "")
        return await validate_bearer_token(token)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed"
        )

router = APIRouter()

# Standard API Response Model
class APIResponse(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None
    error: Optional[str] = None

# Pydantic models
class UploadRequest(BaseModel):
    kb_id: str
    urls: Optional[List[str]] = None

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

class GetUploadStatusRequest(BaseModel):
    batch_id: str

class ListKBFilesRequest(BaseModel):
    kb_id: str

# In-memory status tracking (use Redis/DB for production)
processing_status = {}

async def process_batch_async(batch_id: str, kb_id: str, files_data: List[dict], urls: List[str]):
    """Background task to process uploaded files and URLs"""
    try:
        status_obj = ProcessingStatus(
            batch_id=batch_id,
            status="processing",
            progress=0,
            total_items=len(files_data) + len(urls)
        )
        # Add kb_id to status object for filtering
        status_obj.batch_id = kb_id
        processing_status[batch_id] = status_obj

        total_processed = 0

        # Process files
        for file_data in files_data:
            try:
                # Extract content
                processed = await ItemProcessor.process((file_data["filename"], file_data["content"]), str(uuid.uuid4()))
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

@router.post("/upload", response_model=APIResponse)
async def upload_knowledge(
    background_tasks: BackgroundTasks,
    files: Optional[List[UploadFile]] = File(None),
    urls: Optional[str] = None,  # JSON string for URLs
    current_user: TokenData = Depends(get_current_user)
):
    """Upload files and URLs to knowledge base"""
    try:
        # Note: KB association is now handled at the API key level
        # The kb_id will be retrieved from the API key authentication

        # Parse URLs if provided
        urls_list = []
        if urls:
            try:
                import json
                urls_list = json.loads(urls)
            except:
                # Handle comma-separated URLs
                urls_list = [url.strip() for url in urls.split(',') if url.strip()]

        batch_id = str(uuid.uuid4())
        files_data = []

        # Process uploaded files
        if files:
            for file in files:
                if file.size and file.size > settings.MAX_FILE_SIZE:
                    raise HTTPException(status_code=400, detail=f"File {file.filename} exceeds max size")

                content = await file.read()
                files_data.append({
                    "filename": file.filename,
                    "content": content,
                    "file": file
                })

        if not files_data and not urls_list:
            raise HTTPException(status_code=400, detail="No files or URLs provided")

        # Start background processing
        logger.info(f"Upload attempt: current_user.kb_id = {current_user.kb_id}, user = {current_user}")
        if not current_user.kb_id:
            logger.warning(f"Upload rejected: API key not associated with KB. User: {current_user}")
            raise HTTPException(status_code=400, detail="API key must be associated with a knowledge base")
        background_tasks.add_task(process_batch_async, batch_id, current_user.kb_id, files_data, urls_list)

        # Resolve a valid uploader user id to satisfy DB FK on files.uploaded_by
        uploader_id = None
        try:
            # If authenticated via API key, prefer the api_keys.created_by as the uploader
            if current_user.api_key_id:
                key_row = supabase.table("api_keys").select("created_by").eq("id", current_user.api_key_id).single().execute()
                if key_row.data and key_row.data.get("created_by"):
                    uploader_id = key_row.data.get("created_by")

            # If we still don't have an uploader, check if a user_id was provided (user-scoped token)
            if not uploader_id and current_user.user_id:
                user_check = supabase.table("users").select("id").eq("id", current_user.user_id).single().execute()
                if user_check.data:
                    uploader_id = current_user.user_id

            # Fallback: pick any user in the same org (admin/owner) to attribute the upload to
            if not uploader_id and current_user.org_id:
                org_user = supabase.table("users").select("id").eq("org_id", current_user.org_id).limit(1).execute()
                if org_user.data and len(org_user.data) > 0:
                    uploader_id = org_user.data[0]["id"]

            if not uploader_id:
                # No suitable user found — require a user-scoped token / association
                raise HTTPException(status_code=400, detail="API key is not associated with a valid user in this organization. Please associate a user or use a user token.")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to resolve uploader user: {e}")
            raise HTTPException(status_code=500, detail="Failed to resolve uploader user")

        # Record files in database using resolved uploader_id
        for file_data in files_data:
            # Upload file to Supabase Storage
            file_path = f"{current_user.kb_id}/{str(uuid.uuid4())}_{file_data['filename']}"
            try:
                supabase_storage.from_("files").upload(
                    path=file_path,
                    file=file_data["content"],
                    file_options={"content-type": file_data["file"].content_type or "application/octet-stream"}
                )
                logger.info(f"Uploaded file {file_data['filename']} to storage at {file_path}")
            except Exception as e:
                logger.error(f"Failed to upload {file_data['filename']} to storage: {e}")
                # Continue processing even if storage upload fails

            file_record = {
                "kb_id": current_user.kb_id,
                "filename": file_data["filename"],
                "file_path": file_path if 'file_path' in locals() else None,
                "file_type": file_data["filename"].split(".")[-1] if "." in file_data["filename"] else "unknown",
                "size_bytes": len(file_data["content"]),
                "uploaded_by": uploader_id
            }
            supabase.table("files").insert(file_record).execute()

        for url in urls_list:
            file_record = {
                "kb_id": current_user.kb_id,
                "filename": url,
                "url": url,
                "file_type": "url",
                "uploaded_by": uploader_id
            }
            supabase.table("files").insert(file_record).execute()

        return APIResponse(
            success=True,
            message="Upload initiated. Processing in background.",
            data={
                "files_processed": len(files_data),
                "urls_processed": len(urls_list)
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        return APIResponse(
            success=False,
            message="Upload failed",
            error=str(e)
        )

@router.get("/upload/status", response_model=APIResponse)
async def get_upload_status(current_user: TokenData = Depends(get_current_user)):
    """Get processing status for the user's knowledge base"""
    try:
        # Get the most recent processing status for this user's KB
        kb_statuses = {k: v for k, v in processing_status.items() if hasattr(v, 'kb_id') and v.kb_id == current_user.kb_id}

        if not kb_statuses:
            return APIResponse(
                success=True,
                message="No active uploads found",
                data={"status": "idle", "message": "No uploads in progress"}
            )

        # Return the most recent status
        latest_batch_id = max(kb_statuses.keys())
        status_data = kb_statuses[latest_batch_id]

        return APIResponse(
            success=True,
            message="Status retrieved successfully",
            data={"status": status_data.dict()}
        )
    except Exception as e:
        return APIResponse(
            success=False,
            message="Failed to get upload status",
            error=str(e)
        )

@router.get("/files", response_model=APIResponse)
async def list_kb_files(current_user: TokenData = Depends(get_current_user)):
    """List all files in the user's knowledge base"""
    try:
        if not current_user.kb_id:
            raise HTTPException(status_code=400, detail="API key must be associated with a knowledge base")

        result = supabase.table("files").select("*").eq("kb_id", current_user.kb_id).execute()
        return APIResponse(
            success=True,
            message="Files retrieved successfully",
            data={"files": result.data}
        )

    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(
            success=False,
            message="Failed to list files",
            error=str(e)
        )

@router.get("/files/{file_id}/download")
async def download_file(file_id: str, current_user: TokenData = Depends(get_current_user)):
    """Download a file from storage"""
    try:
        if not current_user.kb_id:
            raise HTTPException(status_code=400, detail="API key must be associated with a knowledge base")

        # Get file record
        file_result = supabase.table("files").select("*").eq("id", file_id).eq("kb_id", current_user.kb_id).single().execute()
        if not file_result.data:
            raise HTTPException(status_code=404, detail="File not found")

        file_data = file_result.data
        if not file_data.get("file_path"):
            raise HTTPException(status_code=404, detail="File not available for download")

        # Download from storage
        response = supabase_storage.from_("files").download(file_data["file_path"])

        from fastapi.responses import StreamingResponse
        import io

        return StreamingResponse(
            io.BytesIO(response),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={file_data['filename']}"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download file {file_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to download file")