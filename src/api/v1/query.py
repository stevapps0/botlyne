from fastapi import APIRouter, HTTPException, status, Depends, Header
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Tuple, Any
import time
import logging
import hashlib
from functools import lru_cache
import asyncio
import secrets
import threading

# Import existing modules
# Import new services
from src.services.retrieval import retrieval_service
from src.services.ai_service import AIService
from src.services.email_service import email_service
from src.core.auth import get_current_user
from src.core.auth_utils import TokenData

# Initialize logging
logger = logging.getLogger(__name__)

from src.core.database import supabase
from src.core.config import settings

# Thread-safe in-memory cache for vector search results
import threading
from typing import Dict, Tuple, Any

vector_search_cache: Dict[str, Tuple[Any, float]] = {}
cache_lock = threading.RLock()  # Reentrant lock for thread safety

def get_cache_key(query: str, kb_id: str) -> str:
    """Generate cache key for query + kb combination"""
    return hashlib.md5(f"{query}:{kb_id}".encode()).hexdigest()

def get_cached_result(cache_key: str) -> Any:
    """Get cached result if still valid (thread-safe)"""
    with cache_lock:
        if cache_key in vector_search_cache:
            cached_data, timestamp = vector_search_cache[cache_key]
            if time.time() - timestamp < settings.CACHE_TTL_SECONDS:
                logger.info(f"Cache hit for query: {cache_key}")
                return cached_data
            else:
                # Expired, remove
                del vector_search_cache[cache_key]
        return None

def set_cached_result(cache_key: str, data: Any) -> None:
    """Cache result with timestamp (thread-safe)"""
    with cache_lock:
        vector_search_cache[cache_key] = (data, time.time())
        logger.info(f"Cached result for query: {cache_key}")

        # Periodic cleanup of expired entries (keep cache size manageable)
        current_time = time.time()
        expired_keys = [
            k for k, (_, ts) in vector_search_cache.items()
            if current_time - ts >= settings.CACHE_TTL_SECONDS
        ]
        for k in expired_keys:
            del vector_search_cache[k]
        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

router = APIRouter()

# Pydantic models
class QueryRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=settings.MAX_MESSAGE_LENGTH, description="User query message")
    user_id: Optional[str] = Field(None, min_length=1, max_length=settings.MAX_USER_ID_LENGTH, pattern=r'^[a-zA-Z0-9_-]+$', description="User identifier")
    kb_id: Optional[str] = Field(None, min_length=1, max_length=settings.MAX_KB_ID_LENGTH, pattern=r'^[a-zA-Z0-9_-]+$', description="Knowledge base ID")
    conversation_id: Optional[str] = Field(None, min_length=1, max_length=settings.MAX_CONVERSATION_ID_LENGTH, pattern=r'^[a-zA-Z0-9_-]+$', description="Conversation ID")

    model_config = ConfigDict(str_strip_whitespace=True)

class QueryResponse(BaseModel):
    conversation_id: str
    user_id: str
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

def detect_handoff_intent(response: str, query: str, tools_used: List[str] = None) -> bool:
    """Simple heuristic to detect if human handoff is needed"""
    # More specific handoff keywords - avoid false positives from normal responses
    handoff_keywords = [
        "human assistance", "speak to human", "talk to person", "real person",
        "live support", "supervisor", "manager", "escalate this", "transfer me",
        "can't assist", "unable to help", "don't have that information",
        "beyond my capabilities", "need human help"
    ]

    # Check query for explicit escalation requests
    query_lower = query.lower()
    query_escalation = any(keyword in query_lower for keyword in [
        "human", "person", "supervisor", "manager", "escalate", "transfer"
    ])

    # Check response for clear inability to help (but not normal agent references)
    response_lower = response.lower()
    response_limitation = any(phrase in response_lower for phrase in [
        "can't help", "cannot assist", "unable to help", "don't know",
        "beyond my capabilities", "need human help"
    ])

    # Only trigger if query explicitly requests escalation OR response clearly indicates limitation
    # Remove the "no tools used" check as it's causing false positives
    return query_escalation or response_limitation


def should_search_knowledge_base(message: str, org_context: dict) -> bool:
    """Determine if knowledge base search is needed for this query"""
    # Skip KB search for simple conversational queries
    skip_keywords = [
        "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
        "how are you", "what's up", "thanks", "thank you", "bye", "goodbye",
        "yes", "no", "okay", "ok", "sure", "maybe", "please", "help"
    ]

    message_lower = message.lower().strip()

    # Skip if message is very short (likely conversational)
    if len(message_lower.split()) <= 3:
        for keyword in skip_keywords:
            if keyword in message_lower:
                return False

    # Skip if it's a question about the AI itself
    ai_questions = ["who are you", "what are you", "what can you do", "how do you work"]
    for question in ai_questions:
        if question in message_lower:
            return False

    # Check if query is relevant to the organization/industry
    # Only search KB if the query seems related to the organization's domain
    org_indicators = []
    if org_context.get('name'):
        # Add organization name words to indicators
        org_indicators.extend(org_context['name'].lower().split())
    if org_context.get('description'):
        # Add industry/domain keywords from description
        org_indicators.extend(org_context['description'].lower().split()[:10])  # First 10 words

    # Common business/tech keywords that suggest KB search is needed
    business_keywords = [
        "app", "application", "software", "service", "product", "feature",
        "pricing", "cost", "billing", "payment", "subscription", "account",
        "login", "password", "support", "help", "issue", "problem", "error",
        "integration", "api", "documentation", "guide", "tutorial"
    ]

    # Check if message contains organization or business-relevant keywords
    has_org_relevance = any(indicator in message_lower for indicator in org_indicators)
    has_business_relevance = any(keyword in message_lower for keyword in business_keywords)

    # Only search KB if query seems relevant to organization or contains business keywords
    should_search = has_org_relevance or has_business_relevance

    logger.info(f"📊 KB SEARCH DECISION - Org relevance: {has_org_relevance}, Business relevance: {has_business_relevance}, Final decision: {should_search}")
    return should_search


async def search_knowledge_base(query: str, kb_id: str) -> Tuple[str, List[dict], List[dict]]:
    """Search knowledge base and return context, sources, and relevant docs"""
    context = ""
    sources = []
    relevant_docs = []

    logger.info(f"🔍 KB SEARCH START - KB: {kb_id}, Query: '{query}'")
    kb_search_start = time.time()
    cache_key = get_cache_key(query, kb_id)
    similar_docs = get_cached_result(cache_key)

    if similar_docs is None:
        logger.info("💾 CACHE MISS - Performing vector search")
        similar_docs = retrieval_service.search_similar(query, kb_id=kb_id, limit=5, table_name="documents")
        set_cached_result(cache_key, similar_docs)
        logger.info(f"✅ VECTOR SEARCH COMPLETED - Found {len(similar_docs)} documents")
    else:
        logger.info(f"⚡ CACHE HIT - Using cached results: {len(similar_docs)} documents")

    kb_search_time = time.time() - kb_search_start
    logger.info(f"⏱️ KB SEARCH TOTAL TIME - {kb_search_time:.3f}s")

    # Filter and optimize context
    relevant_docs = [doc for doc in similar_docs if doc.get("similarity", 0) > settings.SIMILARITY_THRESHOLD]
    logger.info(f"🎯 RELEVANCE FILTERING - Before: {len(similar_docs)}, After: {len(relevant_docs)}")

    # Format context
    total_context_length = 0
    max_context_length = settings.MAX_CONTEXT_LENGTH
    file_ids_to_fetch = []

    for i, doc in enumerate(relevant_docs):
        similarity = doc.get("similarity", 0)
        content = doc.get("content", "")
        metadata = doc.get("metadata", {})

        potential_length = total_context_length + len(content)
        if potential_length > max_context_length:
            content = content[:max_context_length - total_context_length]

        context += f"\n[Source] (Similarity: {similarity:.2%})\n{content}\n"
        total_context_length += len(content)

        file_id = metadata.get("file_id") if metadata else None
        if file_id:
            file_ids_to_fetch.append(file_id)

        sources.append({
            "file_id": file_id,
            "title": str(metadata.get("source", "Unknown") if metadata else "Unknown"),
            "filename": str(metadata.get("source", "Unknown") if metadata else "Unknown"),
            "relevance_score": float(round(similarity, 2)),
            "excerpt": str(content[:150] + "..." if len(content) > 150 else content)
        })

        if len(sources) >= settings.MAX_SOURCES_COUNT:
            break

    # Batch fetch file information
    file_info_map = {}
    if file_ids_to_fetch:
        try:
            file_result = supabase.table("files").select("id", "url", "filename").in_("id", file_ids_to_fetch).execute()
            if file_result.data:
                for file_data in file_result.data:
                    file_info_map[file_data["id"]] = {
                        "url": file_data.get("url"),
                        "filename": file_data.get("filename", "document")
                    }
        except Exception as e:
            logger.warning(f"Failed to batch fetch file info: {e}")

    # Update sources with file information
    for source in sources:
        if source.get("file_id") and source["file_id"] in file_info_map:
            file_info = file_info_map[source["file_id"]]
            source["title"] = str(file_info["filename"])
            source["filename"] = str(file_info["filename"])
            if file_info["url"]:
                source["url"] = str(file_info["url"])
            else:
                source["url"] = f"{settings.API_BASE_URL}/api/v1/files/{source['file_id']}/view"
        else:
            source["url"] = None

        source["title"] = str(source["title"])
        source["filename"] = str(source["filename"])
        source["url"] = str(source["url"]) if source["url"] else None
        source["relevance_score"] = float(source["relevance_score"])
        source["excerpt"] = str(source["excerpt"])
        source.pop("file_id", None)

    if not context.strip():
        context = "No relevant information found in the knowledge base."

    return context, sources, relevant_docs


async def generate_ai_response(
    enhanced_query: str,
    user_id: str,
    kb_id: str,
    relevant_docs: List[dict],
    conversation_id: str,
    conversation_history: List[dict],
    org_context: dict
) -> Tuple[str, List[str], Optional[Any]]:
    """Generate AI response and return response text, tools used, and ai_result object"""
    logger.info(f"🤖 AI PROCESSING START - Context length: {len(enhanced_query)}")
    ai_start = time.time()
    ai_result = None
    try:
        ai_result = await AIService.query_with_context(
            prompt=enhanced_query,
            user_id=user_id,
            relevant_docs=relevant_docs,
            session_id=conversation_id,
            timezone="UTC",
            kb_id=kb_id,
            history=conversation_history,
        )
        ai_response = ai_result.output
        tools_used = getattr(ai_result, 'tools_used', []) or []
        ai_time = time.time() - ai_start
        logger.info(f"⏱️ AI PROCESSING TIME - {ai_time:.3f}s")
    except Exception as ai_error:
        ai_time = time.time() - ai_start
        logger.error(f"❌ AI SERVICE FAILED - Error: {str(ai_error)}")
        ai_response = f"I'm sorry, I'm currently experiencing technical difficulties. As a support agent for {org_context['name']}, please try again in a moment or contact our support team if the issue persists."
        tools_used = []

    return ai_response, tools_used, ai_result


async def get_org_context(org_id: str) -> dict:
    """Get organization details for context"""
    try:
        org_result = supabase.table("organizations").select("*").eq("id", org_id).single().execute()
        if org_result.data:
            return {
                "name": org_result.data.get("name", "our organization"),
                "description": org_result.data.get("description", ""),
                "team_size": org_result.data.get("team_size")
            }
    except Exception as e:
        logger.warning(f"Failed to get org context: {e}")

    return {"name": "our organization", "description": "", "team_size": None}


async def process_query_request(data: QueryRequest, org_id: str, kb_id: str = None) -> QueryResponse:
    """Process a query request - extracted for reuse in webhooks"""
    start_time = time.time()

    # Log request start
    logger.info(f"🔍 QUERY START - User: {data.user_id}, Message: '{data.message[:50]}...', KB: {kb_id or data.kb_id or 'auto'}, Conv: {data.conversation_id or 'new'}")

    try:
        # KB selection: use provided kb_id or request kb_id
        effective_kb_id = kb_id or data.kb_id
        if not effective_kb_id:
            logger.error(f"❌ KB SELECTION FAILED - No KB available")
            raise HTTPException(status_code=400, detail="No knowledge base specified")

        logger.info(f"📚 KB SELECTED - ID: {effective_kb_id}")

        # Verify KB access (skip for webhooks since org is verified at integration level)
        if org_id:
            kb_check = supabase.table("knowledge_bases").select("org_id").eq("id", effective_kb_id).single().execute()
            if not kb_check.data or kb_check.data["org_id"] != org_id:
                logger.warning(f"🚫 KB ACCESS DENIED - KB: {effective_kb_id}, Org: {org_id}")
                raise HTTPException(status_code=403, detail="Access denied to specified knowledge base")

        logger.info(f"✅ KB ACCESS VERIFIED - KB: {effective_kb_id} belongs to org: {org_id}")

        # Use provided user_id directly
        effective_user_id = data.user_id
        logger.info(f"👤 USER IDENTIFIED - ID: {effective_user_id}")

        # Get organization context for personalized support
        logger.info(f"🏢 FETCHING ORG CONTEXT - Org ID: {org_id}")
        org_context = await get_org_context(org_id)
        logger.info(f"✅ ORG CONTEXT LOADED - Name: {org_context['name']}")

        # Get or create conversation
        conv_start = time.time()
        conversation_id = data.conversation_id
        if not conversation_id:
            logger.info(f"💬 CONVERSATION LOOKUP - User: {effective_user_id}, KB: {effective_kb_id}")
            # Try to find existing active conversation for this user/KB combination
            existing_conv = supabase.table("conversations").select("id", "ticket_number").eq("user_id", effective_user_id).eq("kb_id", effective_kb_id).eq("status", "ongoing").order("started_at", desc=True).limit(1).execute()

            if existing_conv.data and len(existing_conv.data) > 0:
                # Reuse existing conversation
                conversation_id = existing_conv.data[0]["id"]
                logger.info(f"🔄 CONVERSATION REUSED - ID: {conversation_id}")
            else:
                # Generate unique ticket number
                ticket_number = ''.join(secrets.choice('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ') for _ in range(settings.MAX_TICKET_LENGTH))
                logger.info(f"🆕 CREATING NEW CONVERSATION - Ticket: {ticket_number}")
                conv_result = supabase.table("conversations").insert({
                    "user_id": effective_user_id,
                    "kb_id": effective_kb_id,
                    "ticket_number": ticket_number
                }).execute()
                conversation_id = conv_result.data[0]["id"]
                logger.info(f"✅ CONVERSATION CREATED - ID: {conversation_id}")
        else:
            logger.info(f"🔍 VERIFYING CONVERSATION - ID: {conversation_id}")
            # Verify conversation ownership
            conv_check = supabase.table("conversations").select("user_id").eq("id", conversation_id).single().execute()
            if not conv_check.data or conv_check.data["user_id"] != effective_user_id:
                logger.warning(f"🚫 CONVERSATION ACCESS DENIED - Conv: {conversation_id}, User: {effective_user_id}")
                raise HTTPException(status_code=403, detail="Access denied")

        # Get conversation history
        conversation_history = []
        if conversation_id:
            try:
                messages_result = supabase.table("messages").select("*").eq("conv_id", conversation_id).order("timestamp", desc=True).limit(10).execute()
                recent_messages = messages_result.data[::-1]

                for msg in recent_messages[-6:]:
                    conversation_history.append({
                        "role": msg["sender"],
                        "content": msg["content"]
                    })
            except Exception as e:
                logger.warning(f"Failed to load conversation history: {e}")

        # Conditionally search knowledge base initially
        logger.info(f"🤔 ANALYZING QUERY TYPE - Message: '{data.message}'")
        should_search_kb = should_search_knowledge_base(data.message, org_context)
        logger.info(f"📊 KB SEARCH DECISION - Search: {should_search_kb}")

        context = ""
        sources = []
        relevant_docs = []

        if should_search_kb:
            context, sources, relevant_docs = await search_knowledge_base(data.message, effective_kb_id)
        else:
            context = f"You are a customer support agent for {org_context['name']}. The user sent a conversational message that doesn't require knowledge base lookup."

        # Build enhanced query
        org_info = f"Organization: {org_context['name']}"
        if org_context.get('description'):
            org_info += f" - {org_context['description']}"

        enhanced_query = f"""{org_info}

You are a customer support agent for {org_context['name']}.

{"Knowledge Base Context:" + context if should_search_kb else context}

User Message: {data.message}

Respond professionally and helpfully as a support agent for {org_context['name']}."""

        # Generate initial AI response
        ai_response, tools_used, ai_result = await generate_ai_response(
            enhanced_query, effective_user_id, effective_kb_id, relevant_docs,
            conversation_id, conversation_history, org_context
        )

        # Check for initial handoff
        handoff_triggered = detect_handoff_intent(ai_response, data.message, tools_used)

        # If handoff detected and KB wasn't searched initially, search now and retry
        if handoff_triggered and not should_search_kb:
            logger.info("🔄 HANDOFF DETECTED - Searching KB before escalating")
            context, sources, relevant_docs = await search_knowledge_base(data.message, effective_kb_id)

            # Rebuild query with KB context
            enhanced_query_with_kb = f"""{org_info}

You are a customer support agent for {org_context['name']}.

Knowledge Base Context:{context}

User Message: {data.message}

Respond professionally and helpfully as a support agent for {org_context['name']}."""

            # Generate new response with KB context
            ai_response, tools_used, ai_result = await generate_ai_response(
                enhanced_query_with_kb, effective_user_id, effective_kb_id, relevant_docs,
                conversation_id, conversation_history, org_context
            )

            # Check for handoff again
            handoff_triggered = detect_handoff_intent(ai_response, data.message, tools_used)
            should_search_kb = True  # Update for metrics

        response_time = time.time() - start_time

        # Store messages
        supabase.table("messages").insert([
            {
                "conv_id": conversation_id,
                "sender": "user",
                "content": data.message
            },
            {
                "conv_id": conversation_id,
                "sender": "ai",
                "content": ai_response
            }
        ]).execute()

        # Store metrics
        analytics = {
            "message_length": len(data.message),
            "kb_searched": should_search_kb,
            "sources_found": len(sources),
            "context_length": len(context),
            "response_quality": len(ai_response) / max(len(data.message), 1),
            "avg_similarity": sum(s["relevance_score"] for s in sources) / len(sources) if sources else 0,
            "tools_used": tools_used,
            "reasoning": getattr(ai_result, 'reasoning', None) if ai_result else None
        }

        supabase.table("metrics").upsert({
            "conv_id": conversation_id,
            "response_time": response_time,
            "ai_responses": 1,
            "handoff_triggered": handoff_triggered,
            "analytics": analytics
        }, on_conflict="conv_id").execute()

        # Update conversation status if handoff
        if handoff_triggered:
            supabase.table("conversations").update({
                "status": "escalated"
            }).eq("id", conversation_id).execute()

        # Get ticket number
        conv_data = supabase.table("conversations").select("ticket_number").eq("id", conversation_id).single().execute()
        ticket_number = conv_data.data.get("ticket_number") if conv_data.data else None

        logger.info(f"🎉 QUERY COMPLETED SUCCESSFULLY - Conv: {conversation_id}, Time: {response_time:.2f}s")
        return QueryResponse(
            conversation_id=conversation_id,
            user_id=effective_user_id,
            user_message=data.message,
            ai_response=ai_response,
            sources=sources,
            response_time=round(response_time, 2),
            handoff_triggered=handoff_triggered,
            ticket_number=ticket_number
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Query failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while processing your query. Please try again."
        )


@router.post("/query", response_model=QueryResponse)
async def query_knowledge_base(
    data: QueryRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """Query the knowledge base with AI agent"""
    # Set user_id from auth if not provided
    if not data.user_id:
        data.user_id = current_user.user_id

    # KB selection: request kb_id takes priority, then API key kb_id
    kb_id = data.kb_id or current_user.kb_id
    if not kb_id:
        raise HTTPException(status_code=400, detail="No knowledge base specified. Provide kb_id in request or ensure API key is associated with a knowledge base")

    # Verify KB access
    kb_check = supabase.table("knowledge_bases").select("org_id").eq("id", kb_id).single().execute()
    if not kb_check.data or kb_check.data["org_id"] != current_user.org_id:
        raise HTTPException(status_code=403, detail="Access denied to specified knowledge base")

    # Use the extracted function
    return await process_query_request(data, current_user.org_id, kb_id)

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


@router.get("/files/{file_id}/view")
async def view_file(
    file_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """Get file information for viewing source documents"""
    try:
        # Get file information
        file_result = supabase.table("files").select("*").eq("id", file_id).single().execute()
        if not file_result.data:
            raise HTTPException(status_code=404, detail="File not found")

        file_data = file_result.data

        # Verify file belongs to user's organization
        if file_data["uploaded_by"] != current_user.user_id:
            # Check if file belongs to same org via KB
            kb_result = supabase.table("knowledge_bases").select("org_id").eq("id", file_data["kb_id"]).single().execute()
            if not kb_result.data or kb_result.data["org_id"] != current_user.org_id:
                raise HTTPException(status_code=403, detail="Access denied")

        # Return standardized file information
        download_url = file_data["url"] if file_data["url"] else f"{settings.API_BASE_URL}/api/v1/files/{file_id}/download"

        return {
            "title": file_data["filename"],
            "url": download_url,
            "filename": file_data["filename"],
            "file_type": file_data["file_type"],
            "size_bytes": file_data["size_bytes"],
            "uploaded_at": file_data["uploaded_at"]
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get file information: {str(e)}"
        )