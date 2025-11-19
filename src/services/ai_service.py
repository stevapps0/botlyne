"""High-level AI service layer for agent queries."""

from typing import Optional
import logging
import time
import hashlib
from uuid import UUID
from functools import lru_cache

from src.services.ai import run_agent
from src.services.ai_models import AgentResponse
from src.services.email_service import email_service
from src.crud import ConversationCRUD, MessageCRUD, MetricsCRUD
from src.core.database import supabase
from src.core.config import settings

logger = logging.getLogger(__name__)

# Simple in-memory cache for agent responses (max 100 entries)
@lru_cache(maxsize=100)
def _get_cached_response(cache_key: str) -> Optional[AgentResponse]:
    """Get cached response if available."""
    # This is a placeholder - in production, use Redis or similar
    return None

def _set_cached_response(cache_key: str, response: AgentResponse) -> None:
    """Cache response (placeholder implementation)."""
    # In production, implement with Redis/memcached
    pass

def _generate_cache_key(prompt: str, kb_context: Optional[str] = None) -> str:
    """Generate cache key from prompt and context."""
    content = f"{prompt}|{kb_context or ''}"
    return hashlib.md5(content.encode()).hexdigest()


class AIService:
    """Service layer for AI agent interactions."""
    
    @staticmethod
    async def query(
        prompt: str,
        user_id: str,
        session_id: Optional[str] = None,
        timezone: str = "UTC",
        kb_id: Optional[str] = None,
        kb_context: Optional[str] = None,
        history: Optional[list] = None,
    ) -> AgentResponse:
        """
        Execute AI agent query with error handling, logging, and database storage.

        Args:
            prompt: User query/prompt
            user_id: User identifier
            session_id: Optional conversation session ID
            timezone: User timezone for time-aware operations
            kb_id: Knowledge base ID for RAG context
            kb_context: Retrieved knowledge base context
            history: Conversation message history

        Returns:
            Typed AgentResponse with output, reasoning, and tools used

        Raises:
            Exception: If agent execution fails after retries
        """
        conv_id = None
        start_time = time.time()

        try:
            logger.info(f"Executing agent query for user {user_id}, session {session_id}")

            # Create or get conversation
            if session_id:
                try:
                    conv_id = UUID(session_id)
                    # Verify conversation exists
                    conv = await ConversationCRUD.get_conversation(conv_id)
                    if not conv:
                        conv_id = None
                except ValueError:
                    conv_id = None

            if not conv_id and kb_id:
                # Create new conversation
                conv_id = await ConversationCRUD.create_conversation(user_id, kb_id)

            # Store user message if we have a conversation
            if conv_id:
                await MessageCRUD.create_message(conv_id, "user", prompt)

            # Execute agent query
            response = await run_agent(
                prompt=prompt,
                user_id=user_id,
                session_id=str(conv_id) if conv_id else None,
                timezone=timezone,
                kb_id=kb_id,
                kb_context=kb_context,
                message_history=history,
            )

            # Store AI response if we have a conversation
            if conv_id:
                await MessageCRUD.create_message(conv_id, "ai", response.output)

                # Handle escalation if needed
                if response.should_escalate:
                    await ConversationCRUD.update_escalation_status(
                        conv_id=conv_id,
                        escalation_status="escalating",
                        escalated_by="ai"
                    )

                    # Update metrics to reflect handoff
                    await MetricsCRUD.update_metrics(
                        conv_id=conv_id,
                        handoff_triggered=True
                    )

                # Record metrics
                response_time = time.time() - start_time
                await MetricsCRUD.create_metrics(
                    conv_id=conv_id,
                    response_time=response_time,
                    ai_responses=1,
                    handoff_triggered=response.should_escalate
                )

            logger.info(
                f"Agent query completed. Tools used: {response.tools_used}, "
                f"Confidence: {response.confidence}"
            )
            return response

        except Exception as e:
            logger.error(f"Agent query failed for user {user_id}: {str(e)}", exc_info=True)
            raise
    
    @staticmethod
    async def query_with_context(
        prompt: str,
        user_id: str,
        relevant_docs: Optional[list[dict]] = None,
        session_id: Optional[str] = None,
        timezone: str = "UTC",
        kb_id: Optional[str] = None,
        history: Optional[list] = None,
    ) -> AgentResponse:
        """
        Execute agent query with RAG context from knowledge base.

        Automatically builds context string from relevant documents and stores interaction.

        Args:
            prompt: User query
            user_id: User identifier
            relevant_docs: List of relevant documents with 'content' field
            session_id: Optional conversation session ID
            timezone: User timezone
            kb_id: Knowledge base ID
            history: Conversation history

        Returns:
            Typed AgentResponse
        """
        # Build context from documents with length management
        context_parts = []
        total_length = 0
        max_context_length = settings.MAX_CONTEXT_LENGTH

        if relevant_docs:
            for i, doc in enumerate(relevant_docs, 1):
                content = doc.get("content", "")
                source = doc.get("source", f"Document {i}")

                # Truncate individual documents if too long
                if len(content) > 1000:
                    content = content[:1000] + "..."

                part = f"[{source}]\n{content}"
                if total_length + len(part) > max_context_length:
                    break  # Stop adding more documents

                context_parts.append(part)
                total_length += len(part)

        context = "\n\n".join(context_parts) if context_parts else ""

        # Build enriched prompt
        if context:
            enriched_prompt = f"Based on this context:\n{context}\n\nUser question: {prompt}"
        else:
            enriched_prompt = prompt

        return await AIService.query(
            prompt=enriched_prompt,
            user_id=user_id,
            session_id=session_id,
            timezone=timezone,
            kb_id=kb_id,
            kb_context=context,
            history=history,
        )

    @staticmethod
    async def collect_customer_email(
        conv_id: str,
        customer_email: str,
        user_id: str
    ) -> dict:
        """
        Collect customer email and complete escalation process.

        Args:
            conv_id: Conversation ID
            customer_email: Customer's email address
            user_id: User ID for validation

        Returns:
            dict: Status and confirmation message
        """
        try:
            # Validate email format (basic check)
            import re
            if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', customer_email):
                return {
                    "success": False,
                    "message": "Please provide a valid email address."
                }

            # Update conversation with email and mark as escalated
            success = await ConversationCRUD.update_escalation_status(
                conv_id=UUID(conv_id),
                escalation_status="escalated",
                customer_email=customer_email,
                escalated_by="ai"
            )

            if success:
                # Send notification to support team (placeholder for now)
                await AIService._notify_support_team(conv_id, customer_email)

                return {
                    "success": True,
                    "message": f"Thank you. Our support team will reach out to you at {customer_email} within 2 hours."
                }
            else:
                return {
                    "success": False,
                    "message": "Sorry, there was an issue processing your email. Please try again."
                }

        except Exception as e:
            logger.error(f"Error collecting email for conversation {conv_id}: {e}")
            return {
                "success": False,
                "message": "Sorry, there was an error. Please try again or contact support directly."
            }

    @staticmethod
    async def _notify_support_team(conv_id: str, customer_email: str) -> None:
        """
        Notify support team about escalated conversation with customer email.
        """
        try:
            logger.info(f"📧 Sending escalation notification for conversation {conv_id} with customer email: {customer_email}")

            # Get conversation details for the email
            conv_result = supabase.table("conversations").select("*").eq("id", conv_id).single().execute()
            if not conv_result.data:
                logger.error(f"Conversation {conv_id} not found for escalation email")
                return

            conversation = conv_result.data

            # Get recent messages for context
            messages_result = supabase.table("messages").select("*").eq("conv_id", conv_id).order("timestamp", desc=True).limit(10).execute()
            recent_messages = messages_result.data[::-1] if messages_result.data else []  # Reverse to chronological

            # Build context from recent conversation
            context_parts = []
            for msg in recent_messages[-6:]:  # Last 6 messages
                sender = "Customer" if msg["sender"] == "user" else "AI Assistant"
                context_parts.append(f"{sender}: {msg['content'][:200]}...")

            conversation_context = "\n".join(context_parts)

            # Create detailed email body
            email_body = f"""
Handoff Notification - Customer Email Collected

Conversation ID: {conv_id}
Ticket Number: {conversation.get('ticket_number', 'N/A')}
Customer Email: {customer_email}
Status: Escalated

Recent Conversation:
{conversation_context}

Please reach out to the customer at {customer_email} to resolve this issue.
"""

            # Send the notification email
            success = await email_service.send_handoff_notification(
                conv_id,
                f"Escalated conversation - Customer email: {customer_email}",
                email_body
            )

            if success:
                logger.info(f"✅ Escalation email sent successfully for conversation {conv_id}")
            else:
                logger.error(f"❌ Failed to send escalation email for conversation {conv_id}")

        except Exception as e:
            logger.error(f"Error notifying support team for conversation {conv_id}: {e}")
