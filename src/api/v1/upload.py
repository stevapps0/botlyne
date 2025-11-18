from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File, BackgroundTasks, Header, Form
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

from src.core.database import supabase
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

async def process_file_background(file_id: str, kb_id: str):
    """Background task to process a single file from storage"""
    logger.info(f"STARTING background processing for file {file_id}, kb {kb_id}")
    try:
        # Update status to processing
        logger.info(f"Updating status to processing for file {file_id}")
        supabase.table("files").update({"status": "processing"}).eq("id", file_id).execute()

        # Get file metadata
        logger.info(f"Fetching metadata for file {file_id}")
        file_result = supabase.table("files").select("*").eq("id", file_id).single().execute()
        if not file_result.data:
            logger.error(f"File {file_id} not found in database")
            return

        file_data = file_result.data
        download_url = file_data["url"]
        logger.info(f"File metadata: {file_data}")
        logger.info(f"Download URL: {download_url}")

        # Process file via signed URL
        logger.info(f"Starting Docling processing for signed URL: {download_url}")
        processed = await ItemProcessor.process(download_url, str(uuid.uuid4()))
        logger.info(f"Docling processing result: status={processed.status}, content_length={len(processed.content) if processed.content else 0}")

        if processed.status == "success":
            logger.info(f"Chunking content for file {file_id}")
            # Transform and load
            vectorized_data = vectorize_and_chunk(processed.content, {"source": file_data["filename"]})
            # Add chunk sizes to metadata for monitoring
            for chunk in vectorized_data:
                chunk["metadata"]["chunk_size"] = len(chunk["content"])
            logger.info(f"Created {len(vectorized_data)} chunks, loading to DB")
            chunks_created = load_to_supabase(vectorized_data, kb_id, file_id)
            if chunks_created > 0:
                logger.info(f"Successfully loaded {chunks_created} chunks for file {file_id}")
                # Update status to completed only after successful DB insertion
                logger.info(f"Updating status to completed for file {file_id}")
                supabase.table("files").update({"status": "completed"}).eq("id", file_id).execute()
            else:
                logger.error(f"Failed to load chunks to DB for file {file_id}")
                supabase.table("files").update({"status": "failed"}).eq("id", file_id).execute()
        else:
            logger.error(f"Docling processing failed for file {file_id}: {processed.error}")
            supabase.table("files").update({"status": "failed"}).eq("id", file_id).execute()

    except Exception as e:
        logger.error(f"Background processing failed for file {file_id}: {e}")
        logger.error(f"Exception details: {str(e)}")
        supabase.table("files").update({"status": "failed"}).eq("id", file_id).execute()

async def process_url_background(url_id: str, kb_id: str, url: str):
    """Background task to process a single URL"""
    try:
        # Process URL
        processed = await ItemProcessor.process(url, str(uuid.uuid4()))
        if processed.status == "success":
            # Transform and load
            vectorized_data = vectorize_and_chunk(processed.content, {"source": url})
            # Add chunk sizes to metadata for monitoring
            for chunk in vectorized_data:
                chunk["metadata"]["chunk_size"] = len(chunk["content"])
            load_to_supabase(vectorized_data, kb_id, url_id)

        # Update status to completed
        supabase.table("files").update({"status": "completed"}).eq("id", url_id).execute()

    except Exception as e:
        logger.error(f"Background processing failed for URL {url}: {e}")
        supabase.table("files").update({"status": "failed"}).eq("id", url_id).execute()


@router.post("/upload", response_model=APIResponse)
async def upload_knowledge(
    background_tasks: BackgroundTasks,
    kb_id: Optional[str] = Form(None),
    files: Optional[List[UploadFile]] = File(None),
    urls: Optional[str] = Form(None),  # JSON string for URLs
    current_user: TokenData = Depends(get_current_user)
):
    """Upload files and URLs to knowledge base"""
    try:
        # Determine kb_id to use
        kb_id_to_use = kb_id or current_user.kb_id
        if not kb_id_to_use:
            # Auto-create default KB for user's org
            if current_user.org_id:
                kb_result = supabase.table("knowledge_bases").insert({
                    "id": str(uuid.uuid4()),
                    "org_id": current_user.org_id,
                    "name": "Default Knowledge Base",
                    "description": "Auto-created for uploads"
                }).execute()
                kb_id_to_use = kb_result.data[0]["id"]
                logger.info(f"Auto-created KB: {kb_id_to_use} for org {current_user.org_id}")
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No organization found - complete onboarding first")

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

        # Process uploaded files - upload to storage first
        if files:
            for file in files:
                if file.size and file.size > settings.MAX_FILE_SIZE:
                    raise HTTPException(status_code=400, detail=f"File {file.filename} exceeds max size")

                content = await file.read()

                # Upload to Supabase Storage
                file_path = f"{kb_id_to_use}/{str(uuid.uuid4())}_{file.filename.replace(' ', '_')}"
                try:
                    supabase.storage.from_("files").upload(file_path, content)
                    # Use signed URL for secure access
                    signed_url_response = supabase.storage.from_("files").create_signed_url(file_path, 3600)  # 1 hour expiry
                    download_url = signed_url_response if isinstance(signed_url_response, str) else signed_url_response.get("signedURL", signed_url_response)
                except Exception as e:
                    logger.error(f"Failed to upload {file.filename} to storage: {e}")
                    raise HTTPException(status_code=500, detail=f"Storage upload failed for {file.filename}")

                files_data.append({
                    "filename": file.filename,
                    "content": content,
                    "file": file,
                    "file_path": file_path,
                    "download_url": download_url
                })

        if not files_data and not urls_list:
            raise HTTPException(status_code=400, detail="No files or URLs provided")

        # Background processing started for files and URLs
        logger.info(f"Upload attempt: kb_id = {kb_id_to_use}, user = {current_user}, files = {len(files_data)}, urls = {len(urls_list)}")

        # Resolve uploader user id: for JWT use current_user.user_id, for API key use api_keys.created_by
        uploader_id = None
        try:
            if current_user.api_key_id:
                # For API keys, get uploader from api_keys.created_by
                key_row = supabase.table("api_keys").select("created_by").eq("id", current_user.api_key_id).single().execute()
                if key_row.data and key_row.data.get("created_by"):
                    uploader_id = key_row.data.get("created_by")
                else:
                    raise HTTPException(status_code=400, detail="API key not associated with a valid user")
            else:
                # For JWT tokens, use the authenticated user_id directly
                uploader_id = current_user.user_id
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to resolve uploader user: {e}")
            raise HTTPException(status_code=500, detail="Failed to resolve uploader user")

        # Record files in database using resolved uploader_id
        for file_data in files_data:
            # Store file metadata in database (Supabase handles file storage via bucket)
            file_path = f"{kb_id_to_use}/{str(uuid.uuid4())}_{file_data['filename']}"
            try:
                # File is already processed through ETL pipeline
                # Store metadata in database
                logger.info(f"Processing file {file_data['filename']} with path {file_path}")
            except Exception as e:
                logger.error(f"Failed to process {file_data['filename']}: {e}")
                # Continue processing even if individual file fails

            file_record = {
                "kb_id": kb_id_to_use,
                "filename": file_data["filename"],
                "file_path": file_data["file_path"],
                "url": file_data["download_url"],
                "file_type": file_data["filename"].split(".")[-1] if "." in file_data["filename"] else "unknown",
                "size_bytes": len(file_data["content"]),
                "uploaded_by": uploader_id,
                "status": "uploading"
            }
            result = supabase.table("files").insert(file_record).execute()
            file_id = result.data[0]["id"]
            # Start background processing for file
            background_tasks.add_task(process_file_background, file_id, kb_id_to_use)

        for url in urls_list:
            file_record = {
                "kb_id": kb_id_to_use,
                "filename": url,
                "url": url,
                "file_type": "url",
                "uploaded_by": uploader_id,
                "status": "processing"
            }
            result = supabase.table("files").insert(file_record).execute()
            url_id = result.data[0]["id"]
            # Process URL immediately
            background_tasks.add_task(process_url_background, url_id, kb_id_to_use, url)

        return APIResponse(
            success=True,
            message="Upload completed. Files stored and processing started in background.",
            data={
                "files_uploaded": len(files_data),
                "urls_processing": len(urls_list)
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
async def get_upload_status(kb_id: Optional[str] = None, current_user: TokenData = Depends(get_current_user)):
    """Get processing status for files in the knowledge base"""
    try:
        kb_id_to_use = kb_id or current_user.kb_id
        if not kb_id_to_use:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Knowledge base ID is required")

        # Get all files for this KB with their statuses
        result = supabase.table("files").select("id, filename, status, file_type, created_at").eq("kb_id", kb_id_to_use).execute()

        files_status = []
        for file in result.data:
            files_status.append({
                "id": file["id"],
                "filename": file["filename"],
                "status": file["status"],
                "file_type": file["file_type"],
                "uploaded_at": file["created_at"]
            })

        # Calculate summary
        total_files = len(files_status)
        completed = sum(1 for f in files_status if f["status"] == "completed")
        processing = sum(1 for f in files_status if f["status"] == "processing")
        failed = sum(1 for f in files_status if f["status"] == "failed")
        uploading = sum(1 for f in files_status if f["status"] == "uploading")

        return APIResponse(
            success=True,
            message="Status retrieved successfully",
            data={
                "summary": {
                    "total": total_files,
                    "uploading": uploading,
                    "processing": processing,
                    "completed": completed,
                    "failed": failed
                },
                "files": files_status
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(
            success=False,
            message="Failed to get upload status",
            error=str(e)
        )

@router.get("/files", response_model=APIResponse)
async def list_kb_files(kb_id: Optional[str] = None, current_user: TokenData = Depends(get_current_user)):
    """List all files in the knowledge base"""
    try:
        kb_id_to_use = kb_id or current_user.kb_id
        if not kb_id_to_use:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Knowledge base ID is required")

        result = supabase.table("files").select("*").eq("kb_id", kb_id_to_use).execute()
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

@router.delete("/files/{file_id}")
async def delete_file(file_id: str, kb_id: Optional[str] = None, current_user: TokenData = Depends(get_current_user)):
    """Delete a file from knowledge base"""
    try:
        kb_id_to_use = kb_id or current_user.kb_id
        if not kb_id_to_use:
            raise HTTPException(status_code=400, detail="Knowledge base ID is required")

        # Get file record and verify ownership
        file_result = supabase.table("files").select("*").eq("id", file_id).eq("kb_id", kb_id_to_use).single().execute()
        if not file_result.data:
            raise HTTPException(status_code=404, detail="File not found")

        file_data = file_result.data

        # Delete associated documents first (cascade)
        supabase.table("documents").delete().eq("file_id", file_id).execute()

        # Delete file record
        supabase.table("files").delete().eq("id", file_id).execute()

        # TODO: Delete from Supabase Storage if needed
        # supabase.storage.from_("files").remove([file_data["file_path"]])

        return APIResponse(
            success=True,
            message="File deleted successfully",
            data={"file_id": file_id, "filename": file_data.get("filename")}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete file {file_id}: {e}")
        return APIResponse(
            success=False,
            message="Failed to delete file",
            error=str(e)
        )

@router.get("/files/{file_id}/download")
async def download_file(file_id: str, kb_id: Optional[str] = None, current_user: TokenData = Depends(get_current_user)):
    """Download a file from storage"""
    try:
        kb_id_to_use = kb_id or current_user.kb_id
        if not kb_id_to_use:
            raise HTTPException(status_code=400, detail="Knowledge base ID is required")

        # Get file record
        file_result = supabase.table("files").select("*").eq("id", file_id).eq("kb_id", kb_id_to_use).single().execute()
        if not file_result.data:
            raise HTTPException(status_code=404, detail="File not found")

        file_data = file_result.data
        if not file_data.get("file_path"):
            raise HTTPException(status_code=404, detail="File not available for download")

        # File is stored in Supabase Storage bucket
        # Return metadata instead of downloading (in production, implement signed URLs)
        return {
            "file_id": file_id,
            "filename": file_data.get("filename"),
            "size_bytes": file_data.get("size_bytes"),
            "uploaded_at": file_data.get("uploaded_at"),
            "message": "Use Supabase Storage signed URL to download"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get file {file_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get file")
