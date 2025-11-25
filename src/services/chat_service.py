"""Chat service for webapp chat integrations."""
import logging
from typing import Optional, List, Dict, Any, AsyncGenerator
from datetime import datetime
import uuid

from src.core.database import supabase
from src.schemas.chat import (
    ChatSession, ChatMessage, ChatRequest, ChatResponse,
    ChatSessionSummary, StreamingChatResponse
)
from src.api.v1.query import process_query_request, QueryRequest

logger = logging.getLogger(__name__)


class ChatService:
    """Service for managing webapp chat sessions and messages."""

    @staticmethod
    async def create_session(
        org_id: str,
        kb_id: Optional[str] = None,
        integration_id: Optional[str] = None
    ) -> ChatSession:
        """Create a new chat session."""
        session = ChatSession(
            org_id=org_id,
            kb_id=kb_id,
            integration_id=integration_id
        )

        # Store in database (using conversations table for compatibility)
        result = supabase.table("conversations").insert({
            "user_id": f"chat_session_{session.id}",  # Unique identifier for chat sessions
            "kb_id": kb_id,
            "ticket_number": f"CHAT-{str(uuid.uuid4())[:8].upper()}",
            "status": "ongoing",
            "channel": "webchat"
        }).execute()

        session.id = result.data[0]["id"]
        logger.info(f"Created chat session: {session.id} for org: {org_id}")
        return session

    @staticmethod
    async def get_session(session_id: str, org_id: str) -> Optional[ChatSession]:
        """Retrieve an existing chat session."""
        try:
            result = supabase.table("conversations").select("*").eq("id", session_id).single().execute()
            if not result.data:
                return None

            conv = result.data
            metadata = conv.get("metadata", {})

            # Verify ownership
            if metadata.get("org_id") != org_id:
                logger.warning(f"Session access denied: {session_id} for org: {org_id}")
                return None

            # Load messages
            messages_result = supabase.table("messages").select("*").eq("conv_id", session_id).order("timestamp").execute()
            messages = []
            for msg in messages_result.data:
                messages.append(ChatMessage(
                    id=msg["id"],
                    role=msg["sender"],
                    content=msg["content"],
                    timestamp=msg["timestamp"]
                ))

            session = ChatSession(
                id=session_id,
                org_id=metadata.get("org_id"),
                kb_id=conv.get("kb_id"),
                integration_id=metadata.get("integration_id"),
                messages=messages,
                created_at=conv["started_at"],
                updated_at=conv.get("updated_at", conv["started_at"]),
                is_active=conv["status"] == "ongoing"
            )

            return session

        except Exception as e:
            logger.error(f"Failed to get session {session_id}: {e}")
            return None

    @staticmethod
    async def process_message(
        request: ChatRequest,
        org_id: str,
        kb_id: Optional[str] = None
    ) -> ChatResponse:
        """Process a chat message and return response."""
        start_time = datetime.utcnow()

        # Get or create session
        session_id = request.session_id
        if not session_id:
            session = await ChatService.create_session(org_id, kb_id)
            session_id = session.id
        else:
            session = await ChatService.get_session(session_id, org_id)
            if not session:
                raise ValueError(f"Session {session_id} not found or access denied")

        # Convert to QueryRequest format
        query_request = QueryRequest(
            message=request.message,
            user_id=f"chat_user_{session_id}",  # Consistent user ID for session
            kb_id=kb_id or session.kb_id,
            conversation_id=session_id
        )

        # Process using existing query logic
        query_response = await process_query_request(query_request, org_id, kb_id or session.kb_id)

        # Create response message
        response_message = ChatMessage(
            role="assistant",
            content=query_response.ai_response
        )

        # Update session with new messages
        await ChatService._add_messages_to_session(session_id, [
            ChatMessage(role="user", content=request.message),
            response_message
        ])

        response_time = (datetime.utcnow() - start_time).total_seconds()

        return ChatResponse(
            session_id=session_id,
            message=response_message,
            sources=query_response.sources,
            response_time=response_time,
            handoff_triggered=query_response.handoff_triggered
        )

    @staticmethod
    async def stream_message(
        request: ChatRequest,
        org_id: str,
        kb_id: Optional[str] = None
    ) -> AsyncGenerator[StreamingChatResponse, None]:
        """Process a chat message with streaming response."""
        # For now, implement simple streaming by yielding chunks
        # In a real implementation, this would integrate with streaming AI responses

        response = await ChatService.process_message(request, org_id, kb_id)

        # Simulate streaming by splitting response into word chunks
        content = response.message.content
        words = content.split()
        chunk_size = 10  # Words per chunk

        for i in range(0, len(words), chunk_size):
            chunk_words = words[i:i + chunk_size]
            chunk = ' '.join(chunk_words)
            yield StreamingChatResponse(
                chunk=chunk,
                finished=False
            )

        # Final chunk with metadata
        yield StreamingChatResponse(
            chunk="",
            finished=True,
            sources=response.sources,
            response_time=response.response_time
        )

    @staticmethod
    async def end_session(session_id: str, org_id: str) -> bool:
        """End a chat session."""
        try:
            session = await ChatService.get_session(session_id, org_id)
            if not session:
                return False

            # Update conversation status
            supabase.table("conversations").update({
                "status": "resolved",
                "resolved_at": "now"
            }).eq("id", session_id).execute()

            logger.info(f"Ended chat session: {session_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to end session {session_id}: {e}")
            return False

    @staticmethod
    async def list_sessions(org_id: str, limit: int = 50) -> List[ChatSessionSummary]:
        """List chat sessions for an organization."""
        try:
            result = supabase.table("conversations").select("*").eq("status", "ongoing").order("started_at", desc=True).limit(limit).execute()

            sessions = []
            for conv in result.data:
                metadata = conv.get("metadata", {})
                if metadata.get("session_type") == "webchat" and metadata.get("org_id") == org_id:
                    # Count messages
                    messages_result = supabase.table("messages").select("id").eq("conv_id", conv["id"]).execute()
                    message_count = len(messages_result.data)

                    sessions.append(ChatSessionSummary(
                        id=conv["id"],
                        org_id=metadata.get("org_id"),
                        kb_id=conv.get("kb_id"),
                        message_count=message_count,
                        created_at=conv["started_at"],
                        updated_at=conv.get("updated_at", conv["started_at"]),
                        is_active=True
                    ))

            return sessions

        except Exception as e:
            logger.error(f"Failed to list sessions for org {org_id}: {e}")
            return []

    @staticmethod
    async def _add_messages_to_session(session_id: str, messages: List[ChatMessage]) -> None:
        """Add messages to a session."""
        try:
            message_data = []
            for msg in messages:
                message_data.append({
                    "conv_id": session_id,
                    "sender": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat()
                })

            if message_data:
                supabase.table("messages").insert(message_data).execute()

            # Update session timestamp
            supabase.table("conversations").update({
                "updated_at": "now"
            }).eq("id", session_id).execute()

        except Exception as e:
            logger.error(f"Failed to add messages to session {session_id}: {e}")
            raise


# Global chat service instance
chat_service = ChatService()