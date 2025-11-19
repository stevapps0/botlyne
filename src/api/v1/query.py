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
    message: str  # Changed from 'query' to 'message'
    user_id: str  # Required for customer tracking
    kb_id: Optional[str] = None  # Optional: override API key's associated KB
    conversation_id: Optional[str] = None  # For continuing conversations

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
    handoff_keywords = [
        "human", "support", "agent", "representative",
        "can't help", "don't know", "escalate", "transfer"
    ]
    combined_text = (response + " " + query).lower()
    keyword_match = any(keyword in combined_text for keyword in handoff_keywords)

    # Also check if no tools were used (indicates agent uncertainty)
    no_tools_used = tools_used is not None and len(tools_used) == 0

    return keyword_match or no_tools_used


def should_search_knowledge_base(message: str) -> bool:
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

    # Default to searching KB for substantive queries
    return True


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


@router.post("/query", response_model=QueryResponse)
async def query_knowledge_base(
    data: QueryRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """Query the knowledge base with AI agent"""
    start_time = time.time()

    # Log request start
    logger.info(f"🔍 QUERY START - User: {data.user_id}, Message: '{data.message[:50]}...', KB: {data.kb_id or 'auto'}, Conv: {data.conversation_id or 'new'}")
    logger.info(f"🔐 AUTH - API Key: {current_user.api_key_id}, Org: {current_user.org_id}, KB: {current_user.kb_id}")

    try:
        # KB selection: request kb_id takes priority, then API key kb_id
        kb_id = data.kb_id or current_user.kb_id
        if not kb_id:
            logger.error(f"❌ KB SELECTION FAILED - No KB available. Request KB: {data.kb_id}, API Key KB: {current_user.kb_id}")
            raise HTTPException(status_code=400, detail="No knowledge base specified. Provide kb_id in request or ensure API key is associated with a knowledge base")

        logger.info(f"📚 KB SELECTED - ID: {kb_id}, Source: {'request' if data.kb_id else 'api_key'}")

        # Verify KB access
        kb_check = supabase.table("knowledge_bases").select("org_id").eq("id", kb_id).single().execute()
        if not kb_check.data or kb_check.data["org_id"] != current_user.org_id:
            logger.warning(f"🚫 KB ACCESS DENIED - KB: {kb_id}, User Org: {current_user.org_id}, KB Org: {kb_check.data.get('org_id') if kb_check.data else 'None'}")
            raise HTTPException(status_code=403, detail="Access denied to specified knowledge base")

        logger.info(f"✅ KB ACCESS VERIFIED - KB: {kb_id} belongs to org: {current_user.org_id}")

        # Use provided user_id directly (no resolution needed for random customers)
        effective_user_id = data.user_id
        logger.info(f"👤 USER IDENTIFIED - ID: {effective_user_id}")

        # Get organization context for personalized support
        logger.info(f"🏢 FETCHING ORG CONTEXT - Org ID: {current_user.org_id}")
        org_context = await get_org_context(current_user.org_id)
        logger.info(f"✅ ORG CONTEXT LOADED - Name: {org_context['name']}, Team Size: {org_context['team_size']}")

        # Get or create conversation
        conversation_id = data.conversation_id
        if not conversation_id:
            logger.info(f"💬 CONVERSATION LOOKUP - User: {effective_user_id}, KB: {kb_id}")
            # Try to find existing active conversation for this user/KB combination
            existing_conv = supabase.table("conversations").select("id", "ticket_number").eq("user_id", effective_user_id).eq("kb_id", kb_id).eq("status", "ongoing").order("started_at", desc=True).limit(1).execute()

            if existing_conv.data and len(existing_conv.data) > 0:
                # Reuse existing conversation
                conversation_id = existing_conv.data[0]["id"]
                logger.info(f"🔄 CONVERSATION REUSED - ID: {conversation_id}, Ticket: {existing_conv.data[0]['ticket_number']}")
            else:
                # Generate unique ticket number (6-character alphanumeric)
                ticket_number = ''.join(secrets.choice('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ') for _ in range(6))
                logger.info(f"🆕 CREATING NEW CONVERSATION - Ticket: {ticket_number}")
                conv_result = supabase.table("conversations").insert({
                    "user_id": effective_user_id,
                    "kb_id": kb_id,
                    "ticket_number": ticket_number
                }).execute()
                conversation_id = conv_result.data[0]["id"]
                logger.info(f"✅ CONVERSATION CREATED - ID: {conversation_id}, Ticket: {ticket_number}")
        else:
            logger.info(f"🔍 VERIFYING CONVERSATION - ID: {conversation_id}")
            # Verify conversation ownership
            conv_check = supabase.table("conversations").select("user_id").eq("id", conversation_id).single().execute()
            if not conv_check.data or conv_check.data["user_id"] != effective_user_id:
                logger.warning(f"🚫 CONVERSATION ACCESS DENIED - Conv: {conversation_id}, Owner: {conv_check.data.get('user_id') if conv_check.data else 'None'}, User: {effective_user_id}")
                raise HTTPException(status_code=403, detail="Access denied")
            logger.info(f"✅ CONVERSATION VERIFIED - ID: {conversation_id}")

        # Conditionally search knowledge base only when relevant
        logger.info(f"🤔 ANALYZING QUERY TYPE - Message: '{data.message}'")
        should_search_kb = should_search_knowledge_base(data.message)
        logger.info(f"📊 KB SEARCH DECISION - Search: {should_search_kb}, Reason: {'Substantive query' if should_search_kb else 'Conversational'}")

        context = ""
        sources = []

        if should_search_kb:
            logger.info(f"🔍 KB SEARCH START - KB: {kb_id}, Query: '{data.message}'")
            cache_key = get_cache_key(data.message, kb_id)
            similar_docs = get_cached_result(cache_key)

            if similar_docs is None:
                logger.info("💾 CACHE MISS - Performing vector search")
                similar_docs = retrieval_service.search_similar(data.message, kb_id=kb_id, limit=5, table_name="documents")
                set_cached_result(cache_key, similar_docs)
                logger.info(f"✅ VECTOR SEARCH COMPLETED - Found {len(similar_docs)} documents")
            else:
                logger.info(f"⚡ CACHE HIT - Using cached results: {len(similar_docs)} documents")

            # Filter and optimize context (enhancement 1)
            relevant_docs = [doc for doc in similar_docs if doc.get("similarity", 0) > 0.3]  # Minimum relevance threshold
            logger.info(f"🎯 RELEVANCE FILTERING - Before: {len(similar_docs)}, After: {len(relevant_docs)} (threshold: 0.3)")

            # Format context for agent with length management
            total_context_length = 0
            max_context_length = 8000  # ~2000 tokens safety limit

            for i, doc in enumerate(relevant_docs):
                similarity = doc.get("similarity", 0)
                content = doc.get("content", "")
                metadata = doc.get("metadata", {})

                # Check if adding this document would exceed context limit
                potential_length = total_context_length + len(content)
                if potential_length > max_context_length:
                    truncated_content = content[:max_context_length - total_context_length]
                    content = truncated_content
                    logger.warning(f"✂️ CONTENT TRUNCATED - Doc {i+1}, Original: {len(content)}, Truncated to: {len(truncated_content)}")

                logger.debug(f"📄 DOC {i+1} - Similarity: {similarity:.3f}, Length: {len(content)}")
                context += f"\n[Source] (Similarity: {similarity:.2%})\n{content}\n"
                total_context_length += len(content)

                # Get file information for standardized source format
                source_url = None
                source_title = None
                if metadata and metadata.get("file_id"):
                    try:
                        file_result = supabase.table("files").select("url, filename").eq("id", metadata["file_id"]).single().execute()
                        if file_result.data:
                            file_url = file_result.data.get("url")
                            filename = file_result.data.get("filename", "document")
                            if file_url:
                                source_url = file_url
                            else:
                                # Use API endpoint for file access
                                source_url = f"{settings.API_BASE_URL}/api/v1/files/{metadata['file_id']}/view"
                            source_title = filename
                    except Exception as e:
                        logger.warning(f"Failed to get file info for source: {e}")

                # Use filename as title if available, otherwise use source name
                title = source_title or (metadata.get("source", "Unknown") if metadata else "Unknown")

                sources.append({
                    "title": title,
                    "url": source_url,
                    "filename": metadata.get("source", "Unknown") if metadata else "Unknown",
                    "relevance_score": round(similarity, 2),
                    "excerpt": content[:150] + "..." if len(content) > 150 else content
                })

                # Stop if we've reached a reasonable number of sources
                if len(sources) >= 3:
                    logger.info(f"🎯 MAX SOURCES REACHED - Stopping at {len(sources)} sources")
                    break

            if not context.strip():
                logger.warning("⚠️ NO CONTEXT FOUND - KB search returned no relevant documents")
                context = "No relevant information found in the knowledge base."
            else:
                logger.info(f"📚 CONTEXT BUILT - Total length: {len(context)} chars, Sources: {len(sources)}")
        else:
            logger.info(f"💬 CONVERSATIONAL MODE - Skipping KB search for: '{data.message}'")
            context = f"You are a customer support agent for {org_context['name']}. The user sent a conversational message that doesn't require knowledge base lookup."

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

        # Include org context and KB context in the enhanced query
        org_info = f"Organization: {org_context['name']}"
        if org_context.get('description'):
            org_info += f" - {org_context['description']}"

        enhanced_query = f"""{org_info}

You are a customer support agent for {org_context['name']}.

{"Knowledge Base Context:" + context if should_search_kb else context}

User Message: {data.message}

Respond professionally and helpfully as a support agent for {org_context['name']}."""

        # Generate AI response with error resilience (enhancement 4)
        logger.info(f"🤖 AI PROCESSING START - Context length: {len(context)}, History: {len(conversation_history)} messages")
        logger.debug(f"📝 ENHANCED QUERY PREVIEW - {enhanced_query[:200]}...")

        ai_result = None
        try:
            logger.info("🚀 CALLING AI SERVICE - Primary agent processing")
            ai_result = await AIService.query_with_context(
                prompt=enhanced_query,
                user_id=effective_user_id,
                relevant_docs=relevant_docs if should_search_kb else [],
                session_id=conversation_id,
                timezone="UTC",  # TODO: Get from user profile
                kb_id=kb_id,
                history=conversation_history,
            )
            ai_response = ai_result.output
            tools_used = getattr(ai_result, 'tools_used', []) or []
            logger.info(f"✅ AI RESPONSE RECEIVED - Length: {len(ai_response)} chars, Tools used: {len(tools_used)}")
            logger.debug(f"💬 AI RESPONSE PREVIEW - {ai_response[:100]}...")
        except Exception as ai_error:
            logger.error(f"❌ AI SERVICE FAILED - Error: {str(ai_error)}")
            # Fallback response
            ai_response = f"I'm sorry, I'm currently experiencing technical difficulties. As a support agent for {org_context['name']}, please try again in a moment or contact our support team if the issue persists."
            tools_used = []
            logger.info("🔄 FALLBACK RESPONSE USED - AI service unavailable")

        response_time = time.time() - start_time
        logger.info(f"⏱️ RESPONSE TIME CALCULATED - {response_time:.2f} seconds")

        # Check for handoff with enhanced logic
        logger.info("🔍 ANALYZING RESPONSE FOR ESCALATION")
        handoff_triggered = detect_handoff_intent(ai_response, data.message, tools_used)
        logger.info(f"📊 ESCALATION DECISION - Handoff triggered: {handoff_triggered}")

        # Store messages
        logger.info("💾 STORING MESSAGES - User + AI messages")
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
        logger.info("✅ MESSAGES STORED - 2 messages saved to database")

        # Store enhanced metrics (enhancement 5)
        analytics = {
            "message_length": len(data.message),
            "kb_searched": should_search_kb,
            "sources_found": len(sources),
            "context_length": len(context),
            "response_quality": len(ai_response) / max(len(data.message), 1),  # Response-to-message ratio
            "avg_similarity": sum(s["similarity"] for s in sources) / len(sources) if sources else 0,
            "tools_used": tools_used,
            "reasoning": getattr(ai_result, 'reasoning', None) if ai_result else None
        }

        logger.info("📈 STORING METRICS - Performance and analytics data")
        supabase.table("metrics").upsert({
            "conv_id": conversation_id,
            "response_time": response_time,
            "ai_responses": 1,
            "handoff_triggered": handoff_triggered,
            "analytics": analytics  # Store analytics data
        }, on_conflict="conv_id").execute()
        logger.info(f"✅ METRICS STORED - Analytics: {analytics}")

        # Update conversation status if handoff
        if handoff_triggered:
            logger.info("🚨 ESCALATION TRIGGERED - Updating conversation status")
            supabase.table("conversations").update({
                "status": "escalated"
            }).eq("id", conversation_id).execute()

            # Send handoff email (non-blocking - failures don't interrupt response)
            logger.info("📧 SENDING ESCALATION NOTIFICATION")
            await email_service.send_handoff_notification(
                conversation_id,
                data.message,
                context
            )
            logger.info("✅ ESCALATION EMAIL SENT")

        # Get ticket number for response
        logger.info("🎫 FETCHING TICKET NUMBER")
        conv_data = supabase.table("conversations").select("ticket_number").eq("id", conversation_id).single().execute()
        ticket_number = conv_data.data.get("ticket_number") if conv_data.data else None
        logger.info(f"✅ TICKET NUMBER RETRIEVED - {ticket_number}")

        logger.info(f"🎉 QUERY COMPLETED SUCCESSFULLY - Conv: {conversation_id}, User: {effective_user_id}, Time: {response_time:.2f}s")
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