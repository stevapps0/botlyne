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
    user_id: str
    org_id: str | None = None
    kb_id: str | None = None  # Add kb_id to token data

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
                # Validate API key using database verification function
                try:
                    derived_shortcode = api_key[-6:]
                    logger.info(f"Testing key with shortcode: {derived_shortcode}")

                    # Use direct table query instead of RPC for reliability
                    # For now, skip shortcode lookup and use direct hash comparison
                    # This is a temporary fix until proper shortcode generation is implemented
                    logger.info("Using direct hash lookup instead of shortcode")
                    # Get all active keys and check hashes (inefficient but works for testing)
                    all_keys = supabase.table("api_keys").select("*").eq("is_active", True).execute()
                    found_key = None
                    for key_record in all_keys.data:
                        import hashlib
                        computed_hash = hashlib.sha256(api_key.encode()).hexdigest()
                        if computed_hash == key_record["key_hash"]:
                            found_key = key_record
                            break

                    if found_key:
                        logger.info(f"Found key record: id={found_key['id']}, kb_id={found_key.get('kb_id')}")

                        # Check expiration
                        expires_at = found_key.get("expires_at")
                        if expires_at:
                            try:
                                expiry_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                                if expiry_dt < datetime.utcnow():
                                    logger.warning("API key expired")
                                    result = type('MockResult', (), {'data': [{'is_valid': False}]})()
                                else:
                                    logger.info("API key valid and not expired")
                                    result = type('MockResult', (), {'data': [{
                                        'is_valid': True,
                                        'api_key_id': found_key['id'],
                                        'org_id': found_key['org_id'],
                                        'kb_id': found_key['kb_id'],
                                        'permissions': found_key['permissions']
                                    }]})()
                            except Exception as e:
                                logger.error(f"Error parsing expiration date: {e}")
                                result = type('MockResult', (), {'data': [{'is_valid': False}]})()
                        else:
                            logger.info("API key valid (no expiration)")
                            result = type('MockResult', (), {'data': [{
                                'is_valid': True,
                                'api_key_id': found_key['id'],
                                'org_id': found_key['org_id'],
                                'kb_id': found_key['kb_id'],
                                'permissions': found_key['permissions']
                            }]})()
                    else:
                        logger.warning("No API key found with matching hash")
                        result = type('MockResult', (), {'data': [{'is_valid': False}]})()

                    logger.info(f"Key query result: {len(key_query.data) if key_query.data else 0} records found")

                    if key_query.data:
                        key_record = key_query.data[0]
                        logger.info(f"Found key record: id={key_record['id']}, kb_id={key_record.get('kb_id')}")

                        import hashlib
                        hashed_key = hashlib.sha256(api_key.encode()).hexdigest()
                        stored_hash = key_record["key_hash"]

                        logger.info(f"Hash comparison: computed={hashed_key[:16]}..., stored={stored_hash[:16]}...")

                        if key_record["key_hash"] == hashed_key:
                            # Check expiration
                            expires_at = key_record.get("expires_at")
                            if expires_at:
                                try:
                                    expiry_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                                    if expiry_dt < datetime.utcnow():
                                        logger.warning("API key expired")
                                        result = type('MockResult', (), {'data': [{'is_valid': False}]})()
                                    else:
                                        logger.info("API key valid and not expired")
                                        result = type('MockResult', (), {'data': [{
                                            'is_valid': True,
                                            'api_key_id': key_record['id'],
                                            'org_id': key_record['org_id'],
                                            'kb_id': key_record['kb_id'],
                                            'permissions': key_record['permissions']
                                        }]})()
                                except Exception as e:
                                    logger.error(f"Error parsing expiration date: {e}")
                                    result = type('MockResult', (), {'data': [{'is_valid': False}]})()
                            else:
                                logger.info("API key valid (no expiration)")
                                result = type('MockResult', (), {'data': [{
                                    'is_valid': True,
                                    'api_key_id': key_record['id'],
                                    'org_id': key_record['org_id'],
                                    'kb_id': key_record['kb_id'],
                                    'permissions': key_record['permissions']
                                }]})()
                        else:
                            logger.warning("Hash mismatch - invalid API key")
                            result = type('MockResult', (), {'data': [{'is_valid': False}]})()
                    else:
                        logger.warning(f"No active API key found with shortcode: {derived_shortcode}")
                        result = type('MockResult', (), {'data': [{'is_valid': False}]})()

                    logger.info(f"Verification result: {result.data}")

                    if result and result.data and len(result.data) > 0 and result.data[0]["is_valid"]:
                        key_info = result.data[0]
                        logger.info(f"Valid key found: kb_id = {key_info.get('kb_id')}, org_id = {key_info.get('org_id')}")

                        # Update last_used_at
                        supabase.rpc("update_key_last_used", {"key_id": key_info["api_key_id"]}).execute()

                        return TokenData(
                            user_id="api_key_user",
                            org_id=key_info.get("org_id"),
                            kb_id=key_info.get("kb_id")
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
        status_obj.kb_id = kb_id
        processing_status[batch_id] = status_obj

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

        # Record files in database
        for file_data in files_data:
            file_record = {
                "kb_id": current_user.kb_id,
                "filename": file_data["filename"],
                "file_type": file_data["filename"].split(".")[-1] if "." in file_data["filename"] else "unknown",
                "size_bytes": len(file_data["content"]),
                "uploaded_by": current_user.user_id
            }
            supabase.table("files").insert(file_record).execute()

        for url in urls_list:
            file_record = {
                "kb_id": current_user.kb_id,
                "filename": url,
                "url": url,
                "file_type": "url",
                "uploaded_by": current_user.user_id
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