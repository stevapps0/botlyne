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

# Initialize logging
logger = logging.getLogger(__name__)

from src.core.database import supabase
from src.core.config import settings

# Pydantic models for dependencies
class TokenData(BaseModel):
    user_id: str | None = None
    org_id: str | None = None
    kb_id: str | None = None  # Add kb_id to token data
    api_key_id: str | None = None  # If request authenticated via API key, include the key id

# Dependency to get current user
async def get_current_user(authorization: str = Header(None, alias="Authorization")):
    """Extract and validate user from JWT token or API key."""
    try:
        logger.info(f"Auth attempt with Authorization header: {authorization[:30]}..." if authorization else "No Authorization header")

        # Check for org API key
        if authorization and authorization.startswith("Bearer "):
            api_key = authorization.replace("Bearer ", "")
            logger.info(f"Extracted API key: {api_key[:15]}...")

            if api_key.startswith("sk-"):
                # Validate API key using database verify_api_key function
                try:
                    logger.info("Validating API key using database function")

                    # Call the database function to verify the key
                    verification_result = supabase.rpc("verify_api_key", {"p_plain_key": api_key}).execute()

                    logger.info(f"Verification result: {verification_result.data}")

                    if verification_result.data and len(verification_result.data) > 0:
                        key_info = verification_result.data[0]
                        logger.info(f"Valid key found: org_id = {key_info.get('org_id')}")

                        # When using API keys there is no user context; return the org and key id
                        return TokenData(
                            user_id=None,
                            org_id=key_info.get("org_id"),
                            kb_id=key_info.get("kb_id"),
                            api_key_id=key_info.get("id")
                        )
                    else:
                        logger.warning("Key not valid or kb_id is null")
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid API key"
                        )
                except HTTPException:
                    raise
                except Exception as e:
                    logger.error(f"Verification error: {e}")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="API key verification failed"
                    )
            else:
                logger.warning(f"Invalid API key format: {api_key[:15]}...")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API key format"
                )

        # This is a simplified version - in real implementation you'd validate the token
        # For now, return a mock user
        logger.warning("No valid Bearer token found, using mock user")
        return TokenData(user_id="mock_user", org_id="mock_org", kb_id=None)
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
                    "content": content
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
            file_record = {
                "kb_id": current_user.kb_id,
                "filename": file_data["filename"],
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