"""Chat API endpoints for webapp integrations."""
from fastapi import APIRouter, HTTPException, status, Depends, Header
from fastapi.responses import StreamingResponse
from typing import List, AsyncGenerator
import logging
import json

from src.core.database import supabase
from src.core.auth_utils import validate_bearer_token
from src.services.chat_service import chat_service
from src.schemas.chat import (
    ChatRequest, ChatResponse, ChatSessionSummary,
    StreamingChatResponse
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def get_chat_org(shortcode: str, authorization: str = Header(None, alias="Authorization")) -> str:
    """Validate API key and get organization ID from shortcode."""
    try:
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required"
            )

        token = authorization.replace("Bearer ", "")
        token_data = await validate_bearer_token(token)

        # Get org_id from shortcode
        org_result = supabase.table("organizations").select("id").eq("shortcode", shortcode).single().execute()
        if not org_result.data:
            raise HTTPException(status_code=404, detail="Organization not found")

        org_id = org_result.data["id"]

        # Verify API key belongs to organization
        if token_data.org_id != org_id:
            raise HTTPException(status_code=403, detail="Access denied")

        return org_id

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat authentication failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed"
        )


@router.post("/chat/{shortcode}", response_model=ChatResponse)
async def send_chat_message(
    shortcode: str,
    request: ChatRequest,
    org_id: str = Depends(get_chat_org)
):
    """Send a message to the chat agent."""
    try:
        logger.info(f"Chat message received for org {org_id} (shortcode: {shortcode})")

        # Get KB ID from organization's default or integration
        kb_result = supabase.table("knowledge_bases").select("id").eq("org_id", org_id).limit(1).execute()
        kb_id = kb_result.data[0]["id"] if kb_result.data else None

        if not kb_id:
            raise HTTPException(status_code=400, detail="No knowledge base available for this organization")

        response = await chat_service.process_message(request, org_id, kb_id)
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat message processing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process chat message"
        )


@router.get("/chat/{shortcode}/session/{session_id}")
async def get_chat_session(
    shortcode: str,
    session_id: str,
    org_id: str = Depends(get_chat_org)
):
    """Get chat session history."""
    try:
        session = await chat_service.get_session(session_id, org_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        return {
            "session_id": session.id,
            "messages": [msg.dict() for msg in session.messages],
            "is_active": session.is_active,
            "created_at": session.created_at,
            "updated_at": session.updated_at
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get chat session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve session"
        )


@router.delete("/chat/{shortcode}/session/{session_id}")
async def end_chat_session(
    shortcode: str,
    session_id: str,
    org_id: str = Depends(get_chat_org)
):
    """End a chat session."""
    try:
        success = await chat_service.end_session(session_id, org_id)
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")

        return {"message": "Session ended successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to end chat session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to end session"
        )


@router.get("/chat/{shortcode}/sessions", response_model=List[ChatSessionSummary])
async def list_chat_sessions(
    shortcode: str,
    org_id: str = Depends(get_chat_org)
):
    """List active chat sessions for the organization."""
    try:
        sessions = await chat_service.list_sessions(org_id)
        return sessions

    except Exception as e:
        logger.error(f"Failed to list chat sessions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list sessions"
        )


@router.post("/chat/{shortcode}/stream")
async def stream_chat_message(
    shortcode: str,
    request: ChatRequest,
    org_id: str = Depends(get_chat_org)
):
    """Stream a chat message response in real-time."""
    try:
        logger.info(f"Streaming chat message for org {org_id} (shortcode: {shortcode})")

        # Get KB ID
        kb_result = supabase.table("knowledge_bases").select("id").eq("org_id", org_id).limit(1).execute()
        kb_id = kb_result.data[0]["id"] if kb_result.data else None

        if not kb_id:
            raise HTTPException(status_code=400, detail="No knowledge base available for this organization")

        async def generate_stream():
            async for chunk in chat_service.stream_message(request, org_id, kb_id):
                yield f"data: {json.dumps(chunk.dict())}\n\n"

        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Streaming chat failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to stream chat response"
        )