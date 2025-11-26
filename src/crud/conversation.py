"""CRUD operations for conversations."""

from typing import Optional, List
from uuid import UUID
import logging
from datetime import datetime

from src.core.database import supabase
from src.services.ai_models import AgentResponse

logger = logging.getLogger(__name__)


class ConversationCRUD:
    """CRUD operations for conversations table."""

    @staticmethod
    async def create_conversation(
        user_id: str,
        kb_id: str,
        status: str = "ongoing"
    ) -> Optional[UUID]:
        """Create a new conversation."""
        try:
            result = supabase.table("conversations").insert({
                "user_id": user_id,
                "kb_id": kb_id,
                "status": status,
                "started_at": datetime.utcnow().isoformat()
            }).execute()

            if result.data:
                return UUID(result.data[0]["id"])
            return None
        except Exception as e:
            logger.error(f"Error creating conversation: {e}")
            return None

    @staticmethod
    async def get_conversation(conv_id: UUID) -> Optional[dict]:
        """Get conversation by ID."""
        try:
            result = supabase.table("conversations").select("*").eq("id", str(conv_id)).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting conversation {conv_id}: {e}")
            return None

    @staticmethod
    async def update_conversation_status(conv_id: UUID, status: str) -> bool:
        """Update conversation status."""
        try:
            update_data = {
                "status": status,
                "resolved_at": datetime.utcnow().isoformat() if status.startswith("resolved") else None
            }
            supabase.table("conversations").update(update_data).eq("id", str(conv_id)).execute()
            return True
        except Exception as e:
            logger.error(f"Error updating conversation {conv_id}: {e}")
            return False

    @staticmethod
    async def update_escalation_status(
        conv_id: UUID,
        escalation_status: str,
        contact: Optional[str] = None,
        escalated_by: str = "ai",
        escalation_reason: Optional[str] = None
    ) -> bool:
        """Update conversation escalation information."""
        try:
            update_data = {
                "escalation_status": escalation_status,
                "escalated_at": datetime.utcnow().isoformat(),
                "escalated_by": escalated_by
            }
            if contact:
                update_data["contact"] = contact

            supabase.table("conversations").update(update_data).eq("id", str(conv_id)).execute()
            return True
        except Exception as e:
            logger.error(f"Error updating escalation status for conversation {conv_id}: {e}")
            return False

    @staticmethod
    async def get_user_conversations(user_id: str, limit: int = 50) -> List[dict]:
        """Get recent conversations for a user."""
        try:
            result = supabase.table("conversations").select("*").eq("user_id", user_id).order("started_at", desc=True).limit(limit).execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Error getting conversations for user {user_id}: {e}")
            return []


class MessageCRUD:
    """CRUD operations for messages table."""

    @staticmethod
    async def create_message(
        conv_id: UUID,
        sender: str,
        content: str
    ) -> Optional[UUID]:
        """Create a new message."""
        try:
            result = supabase.table("messages").insert({
                "conv_id": str(conv_id),
                "sender": sender,
                "content": content,
                "timestamp": datetime.utcnow().isoformat()
            }).execute()

            if result.data:
                return UUID(result.data[0]["id"])
            return None
        except Exception as e:
            logger.error(f"Error creating message: {e}")
            return None

    @staticmethod
    async def get_conversation_messages(conv_id: UUID) -> List[dict]:
        """Get all messages for a conversation."""
        try:
            result = supabase.table("messages").select("*").eq("conv_id", str(conv_id)).order("timestamp").execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Error getting messages for conversation {conv_id}: {e}")
            return []


class MetricsCRUD:
    """CRUD operations for metrics table."""

    @staticmethod
    async def create_metrics(
        conv_id: UUID,
        response_time: Optional[float] = None,
        resolution_time: Optional[float] = None,
        satisfaction_score: Optional[int] = None,
        ai_responses: int = 0,
        handoff_triggered: bool = False
    ) -> Optional[UUID]:
        """Create or update metrics entry for a conversation."""
        try:
            result = supabase.table("metrics").upsert({
                "conv_id": str(conv_id),
                "response_time": response_time,
                "resolution_time": resolution_time,
                "satisfaction_score": satisfaction_score,
                "ai_responses": ai_responses,
                "handoff_triggered": handoff_triggered,
                "created_at": datetime.utcnow().isoformat()
            }, on_conflict="conv_id").execute()

            if result.data:
                return UUID(result.data[0]["id"])
            return None
        except Exception as e:
            logger.error(f"Error upserting metrics: {e}")
            return None

    @staticmethod
    async def update_metrics(
        conv_id: UUID,
        response_time: Optional[float] = None,
        resolution_time: Optional[float] = None,
        satisfaction_score: Optional[int] = None,
        ai_responses: Optional[int] = None,
        handoff_triggered: Optional[bool] = None
    ) -> bool:
        """Update metrics for a conversation."""
        try:
            update_data = {}
            if response_time is not None:
                update_data["response_time"] = response_time
            if resolution_time is not None:
                update_data["resolution_time"] = resolution_time
            if satisfaction_score is not None:
                update_data["satisfaction_score"] = satisfaction_score
            if ai_responses is not None:
                update_data["ai_responses"] = ai_responses
            if handoff_triggered is not None:
                update_data["handoff_triggered"] = handoff_triggered

            if update_data:
                supabase.table("metrics").update(update_data).eq("conv_id", str(conv_id)).execute()
            return True
        except Exception as e:
            logger.error(f"Error updating metrics for conversation {conv_id}: {e}")
            return False