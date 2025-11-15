from fastapi import APIRouter, HTTPException, status, Depends, Header
from pydantic import BaseModel
from typing import List, Optional
import time
import logging
import hashlib
from functools import lru_cache
import asyncio
import secrets

# Import existing modules
from src.archive.answer import retrieve_similar
from src.archive.agent import agent
from src.core.auth import get_current_user
from src.core.auth_utils import TokenData

# Initialize logging
logger = logging.getLogger(__name__)

from src.core.database import supabase
from src.core.config import settings

# Simple in-memory cache for vector search results
vector_search_cache = {}
CACHE_TTL = 300  # 5 minutes

def get_cache_key(query: str, kb_id: str) -> str:
    """Generate cache key for query + kb combination"""
    return hashlib.md5(f"{query}:{kb_id}".encode()).hexdigest()

def get_cached_result(cache_key: str):
    """Get cached result if still valid"""
    if cache_key in vector_search_cache:
        cached_data, timestamp = vector_search_cache[cache_key]
        if time.time() - timestamp < CACHE_TTL:
            logger.info(f"Cache hit for query: {cache_key}")
            return cached_data
        else:
            # Expired, remove
            del vector_search_cache[cache_key]
    return None

def set_cached_result(cache_key: str, data):
    """Cache result with timestamp"""
    vector_search_cache[cache_key] = (data, time.time())
    logger.info(f"Cached result for query: {cache_key}")

router = APIRouter()

# Pydantic models
class QueryRequest(BaseModel):
    query: str
    kb_id: Optional[str] = None  # Optional, will use API key's associated KB if not provided
    conversation_id: Optional[str] = None  # For continuing conversations
    user_id: str  # Required user ID for conversation attribution

class QueryResponse(BaseModel):
    conversation_id: str
    user_message: str
    ai_response: str
    sources: List[dict]
    response_time: float
    handoff_triggered: bool = False
    ticket_number: Optional[str] = None

class ConversationResponse(BaseModel):
    id: str
    kb_id: str
    messages: List[dict]
    status: str
    started_at: str
    resolved_at: Optional[str] = None
    ticket_number: Optional[str] = None

def detect_handoff_intent(response: str, query: str) -> bool:
    """Simple heuristic to detect if human handoff is needed"""
    handoff_keywords = [
        "human", "support", "agent", "representative",
        "can't help", "don't know", "escalate", "transfer"
    ]
    combined_text = (response + " " + query).lower()
    return any(keyword in combined_text for keyword in handoff_keywords)

async def send_handoff_email(conversation_id: str, query: str, context: str):
    """Send email notification for human handoff"""
    try:
        import smtplib
        from email.mime.text import MIMEText

        # Email configuration from settings
        SMTP_SERVER = settings.SMTP_SERVER
        SMTP_PORT = settings.SMTP_PORT
        SMTP_USER = settings.SMTP_USER
        SMTP_PASS = settings.SMTP_PASS
        SUPPORT_EMAIL = settings.SUPPORT_EMAIL

        if not all([SMTP_USER, SMTP_PASS]):
            logger.warning("SMTP credentials not configured, skipping email")
            return

        msg = MIMEText(f"""
Human handoff requested for conversation {conversation_id}

User Query: {query}

Context: {context[:500]}...

Please review and respond to the user.
        """)

        msg['Subject'] = f"Human Handoff: Conversation {conversation_id}"
        msg['From'] = SMTP_USER
        msg['To'] = SUPPORT_EMAIL

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, SUPPORT_EMAIL, msg.as_string())
        server.quit()

        logger.info(f"Handoff email sent for conversation {conversation_id}")

    except Exception as e:
        logger.error(f"Failed to send handoff email: {e}")

@router.post("/query", response_model=QueryResponse)
async def query_knowledge_base(
    data: QueryRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """Query the knowledge base with AI agent"""
    start_time = time.time()

    try:
        # Use KB from request or API key association
        kb_id = data.kb_id or current_user.kb_id

        if not kb_id:
            raise HTTPException(status_code=400, detail="No knowledge base specified. Either provide kb_id in request or ensure API key is associated with a knowledge base")

        # Verify KB access
        kb_check = supabase.table("knowledge_bases").select("org_id").eq("id", kb_id).single().execute()
        if not kb_check.data or kb_check.data["org_id"] != current_user.org_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Resolve an effective user id for the conversation (API keys are system-level)
        effective_user_id = data.user_id or current_user.user_id
        if not effective_user_id and current_user.api_key_id:
            # Try to attribute to the API key creator
            key_row = supabase.table("api_keys").select("created_by").eq("id", current_user.api_key_id).single().execute()
            if key_row.data and key_row.data.get("created_by"):
                effective_user_id = key_row.data.get("created_by")

        # Fallback: any user in the org
        if not effective_user_id and current_user.org_id:
            org_user = supabase.table("users").select("id").eq("org_id", current_user.org_id).limit(1).execute()
            if org_user.data and len(org_user.data) > 0:
                effective_user_id = org_user.data[0]["id"]

        if not effective_user_id:
            raise HTTPException(status_code=403, detail="No user available for conversation attribution")

        # Get or create conversation
        conversation_id = data.conversation_id
        if not conversation_id:
            # Generate unique ticket number (6-character alphanumeric)
            ticket_number = ''.join(secrets.choice('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ') for _ in range(6))
            conv_result = supabase.table("conversations").insert({
                "user_id": effective_user_id,
                "kb_id": kb_id,
                "ticket_number": ticket_number
            }).execute()
            conversation_id = conv_result.data[0]["id"]
        else:
            # Verify conversation ownership
            conv_check = supabase.table("conversations").select("user_id").eq("id", conversation_id).single().execute()
            if not conv_check.data or conv_check.data["user_id"] != effective_user_id:
                raise HTTPException(status_code=403, detail="Access denied")

        # Retrieve similar documents with caching (enhancement 2)
        logger.info(f"Querying KB {kb_id} for: '{data.query}'")
        cache_key = get_cache_key(data.query, kb_id)
        similar_docs = get_cached_result(cache_key)

        if similar_docs is None:
            logger.info("Cache miss - performing vector search")
            similar_docs = retrieve_similar(data.query, kb_id=kb_id, limit=5, table_name="documents")
            set_cached_result(cache_key, similar_docs)
        else:
            logger.info("Using cached vector search results")

        logger.info(f"Found {len(similar_docs)} similar documents")

        # Filter and optimize context (enhancement 1)
        relevant_docs = [doc for doc in similar_docs if doc.get("similarity", 0) > 0.3]  # Minimum relevance threshold
        logger.info(f"After relevance filtering: {len(relevant_docs)} documents")

        # Format context for agent with length management
        context = ""
        sources = []
        total_context_length = 0
        max_context_length = 8000  # ~2000 tokens safety limit

        for doc in relevant_docs:
            similarity = doc.get("similarity", 0)
            content = doc.get("content", "")
            metadata = doc.get("metadata", {})

            # Check if adding this document would exceed context limit
            potential_length = total_context_length + len(content)
            if potential_length > max_context_length:
                truncated_content = content[:max_context_length - total_context_length]
                content = truncated_content
                logger.info(f"Truncated document to fit context limit: {len(truncated_content)} chars")

            logger.info(f"Document similarity: {similarity:.3f}, content length: {len(content)}")
            context += f"\n[Source] (Similarity: {similarity:.2%})\n{content}\n"
            total_context_length += len(content)

            sources.append({
                "content": content[:200] + "..." if len(content) > 200 else content,
                "similarity": similarity,
                "metadata": metadata
            })

            # Stop if we've reached a reasonable number of sources
            if len(sources) >= 3:
                break

        # Generate AI response with conversation history (enhancement 3)
        if not context.strip():
            logger.warning("No context found from knowledge base - empty results")
            context = "No relevant information found in the knowledge base."

        # Get recent conversation history
        conversation_history = []
        if conversation_id:
            try:
                messages_result = supabase.table("messages").select("*").eq("conv_id", conversation_id).order("timestamp", desc=True).limit(10).execute()
                recent_messages = messages_result.data[::-1]  # Reverse to chronological order

                for msg in recent_messages[-6:]:  # Last 6 messages for context
                    conversation_history.append({
                        "role": msg["sender"],
                        "content": msg["content"]
                    })
                logger.info(f"Included {len(conversation_history)} messages from conversation history")
            except Exception as e:
                logger.warning(f"Failed to load conversation history: {e}")

        # Include context in the user query itself since PydanticAI doesn't support runtime system prompt changes
        enhanced_query = f"""Based on the following knowledge base context, please answer the user's question.

Knowledge Base Context:
{context}

User Question: {data.query}

If the context doesn't contain relevant information to answer the question, please say so clearly."""

        # Generate AI response with error resilience (enhancement 4)
        logger.info(f"Sending enhanced query to AI agent with context length: {len(context)}")

        try:
            result = await agent.run(
                enhanced_query,
                message_history=conversation_history,  # Include conversation history
                deps=None
            )
            ai_response = result.output
            logger.info(f"AI response received, length: {len(ai_response)}")
        except Exception as ai_error:
            logger.error(f"AI service failed: {ai_error}")
            # Fallback response
            ai_response = "I'm sorry, I'm currently experiencing technical difficulties. Please try again in a moment, or contact support if the issue persists."
            if context and context.strip():
                ai_response += " Based on the available information, you might find relevant details in the knowledge base."

        response_time = time.time() - start_time

        # Check for handoff
        handoff_triggered = detect_handoff_intent(ai_response, data.query)

        # Store messages
        supabase.table("messages").insert([
            {
                "conv_id": conversation_id,
                "sender": "user",
                "content": data.query
            },
            {
                "conv_id": conversation_id,
                "sender": "ai",
                "content": ai_response
            }
        ]).execute()

        # Store enhanced metrics (enhancement 5)
        analytics = {
            "query_length": len(data.query),
            "sources_found": len(sources),
            "context_length": len(context),
            "response_quality": len(ai_response) / max(len(data.query), 1),  # Response-to-query ratio
            "avg_similarity": sum(s["similarity"] for s in sources) / len(sources) if sources else 0
        }

        supabase.table("metrics").upsert({
            "conv_id": conversation_id,
            "response_time": response_time,
            "ai_responses": 1,
            "handoff_triggered": handoff_triggered,
            "analytics": analytics  # Store analytics data
        }, on_conflict="conv_id").execute()

        logger.info(f"Query analytics: {analytics}")

        # Update conversation status if handoff
        if handoff_triggered:
            supabase.table("conversations").update({
                "status": "escalated"
            }).eq("id", conversation_id).execute()

            # Send handoff email
            await send_handoff_email(conversation_id, data.query, context)

        # Get ticket number for response
        conv_data = supabase.table("conversations").select("ticket_number").eq("id", conversation_id).single().execute()
        ticket_number = conv_data.data.get("ticket_number") if conv_data.data else None

        return QueryResponse(
            conversation_id=conversation_id,
            user_message=data.query,
            ai_response=ai_response,
            sources=sources,
            response_time=round(response_time, 2),
            handoff_triggered=handoff_triggered,
            ticket_number=ticket_number
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Query processing failed"
        )

@router.get("/conversations", response_model=List[ConversationResponse])
async def list_conversations(
    current_user: TokenData = Depends(get_current_user)
):
    """List user's conversations"""
    try:
        result = supabase.table("conversations").select("""
            id,
            kb_id,
            status,
            started_at,
            resolved_at,
            ticket_number
        """).eq("user_id", current_user.user_id).order("started_at", desc=True).execute()

        conversations = []
        for conv in result.data:
            # Get messages
            messages_result = supabase.table("messages").select("*").eq("conv_id", conv["id"]).order("timestamp").execute()
            conv["messages"] = messages_result.data
            conversations.append(ConversationResponse(**conv))

        return conversations

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to list conversations: {str(e)}"
        )

@router.post("/conversations/{conv_id}/resolve")
async def resolve_conversation(
    conv_id: str,
    satisfaction_score: Optional[int] = None,
    current_user: TokenData = Depends(get_current_user)
):
    """Mark conversation as resolved and optionally rate satisfaction"""
    try:
        # Verify conversation ownership
        conv_check = supabase.table("conversations").select("user_id").eq("id", conv_id).single().execute()
        if not conv_check.data or conv_check.data["user_id"] != current_user.user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Update conversation
        update_data = {
            "status": "resolved_human",
            "resolved_at": "now"
        }
        supabase.table("conversations").update(update_data).eq("id", conv_id).execute()

        # Update metrics if satisfaction provided
        if satisfaction_score:
            supabase.table("metrics").update({
                "satisfaction_score": satisfaction_score
            }).eq("conv_id", conv_id).execute()

        return {"message": "Conversation resolved"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to resolve conversation: {str(e)}"
        )