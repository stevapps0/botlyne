from fastapi import APIRouter, HTTPException, status, Depends, Header
from pydantic import BaseModel
from typing import List, Optional
import time
import logging

# Import existing modules
from src.archive.answer import retrieve_similar
from src.archive.agent import agent

# Initialize logging
logger = logging.getLogger(__name__)

from src.core.database import supabase
from src.core.config import settings

# Pydantic models for dependencies
class TokenData(BaseModel):
    user_id: str | None = None
    org_id: str | None = None
    kb_id: str | None = None
    api_key_id: str | None = None

# Dependency to get current user
async def get_current_user(authorization: str = Header(None, alias="Authorization")):
    """Extract and validate user from JWT token or API key."""
    try:
        logger.info(f"Query auth attempt with Authorization header: {authorization[:30]}..." if authorization else "No Authorization header")

        # Check for org API key
        if authorization and authorization.startswith("Bearer "):
            api_key = authorization.replace("Bearer ", "")
            logger.info(f"Extracted API key: {api_key[:15]}...")

            if api_key.startswith("kb_") or api_key.startswith("sk-"):
                # Validate API key using database verification function
                try:
                    derived_shortcode = api_key[-6:]
                    logger.info(f"Testing key with shortcode: {derived_shortcode}")

                    # Use the verify_api_key database function
                    result = supabase.rpc("verify_api_key", {"p_plain_key": api_key}).execute()

                    logger.info(f"Verification result: {result.data}")

                    if result.data and len(result.data) > 0:
                        key_info = result.data[0]
                        logger.info(f"Valid key found: org_id = {key_info.get('org_id')}")

                        # Update last_used_at (optional - skip if function not available)
                        try:
                            supabase.rpc("update_key_last_used", {"key_id": key_info.get("id")}).execute()
                        except Exception:
                            pass  # Function may not exist in database

                        # Return org/kb info and api_key id; no user context for API keys
                        return TokenData(
                            user_id=None,
                            org_id=key_info.get('org_id'),
                            kb_id=key_info.get('kb_id'),
                            api_key_id=key_info.get('id')
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

# Pydantic models
class QueryRequest(BaseModel):
    query: str
    kb_id: Optional[str] = None  # Optional, will use API key's associated KB if not provided
    conversation_id: Optional[str] = None  # For continuing conversations

class QueryResponse(BaseModel):
    conversation_id: str
    user_message: str
    ai_response: str
    sources: List[dict]
    response_time: float
    handoff_triggered: bool = False

class ConversationResponse(BaseModel):
    id: str
    kb_id: str
    messages: List[dict]
    status: str
    started_at: str
    resolved_at: Optional[str] = None

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
        effective_user_id = current_user.user_id
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
            conv_result = supabase.table("conversations").insert({
                "user_id": effective_user_id,
                "kb_id": kb_id
            }).execute()
            conversation_id = conv_result.data[0]["id"]
        else:
            # Verify conversation ownership
            conv_check = supabase.table("conversations").select("user_id").eq("id", conversation_id).single().execute()
            if not conv_check.data or conv_check.data["user_id"] != effective_user_id:
                raise HTTPException(status_code=403, detail="Access denied")

        # Retrieve similar documents
        logger.info(f"Querying KB {kb_id} for: '{data.query}'")
        similar_docs = retrieve_similar(data.query, kb_id=kb_id, limit=5, table_name="documents")
        logger.info(f"Found {len(similar_docs)} similar documents")

        # Format context for agent
        context = ""
        sources = []
        for doc in similar_docs:
            similarity = doc.get("similarity", 0)
            content = doc.get("content", "")
            metadata = doc.get("metadata", {})

            logger.info(f"Document similarity: {similarity:.3f}, content preview: {content[:100]}...")
            context += f"\n[Source] (Similarity: {similarity:.2%})\n{content}\n"
            sources.append({
                "content": content[:200] + "..." if len(content) > 200 else content,
                "similarity": similarity,
                "metadata": metadata
            })

        # Generate AI response
        if not context.strip():
            logger.warning("No context found from knowledge base - empty results")
            context = "No relevant information found in the knowledge base."

        # Include context in the user query itself since PydanticAI doesn't support runtime system prompt changes
        enhanced_query = f"""Based on the following knowledge base context, please answer the user's question.

Knowledge Base Context:
{context}

User Question: {data.query}

If the context doesn't contain relevant information to answer the question, please say so clearly."""

        logger.info(f"Sending enhanced query to AI agent with context length: {len(context)}")
        result = await agent.run(
            enhanced_query,
            message_history=[],  # Could implement conversation history
            deps=None
        )

        ai_response = result.output
        logger.info(f"AI response received, length: {len(ai_response)}")
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

        # Store metrics
        supabase.table("metrics").insert({
            "conv_id": conversation_id,
            "response_time": response_time,
            "ai_responses": 1,
            "handoff_triggered": handoff_triggered
        }).execute()

        # Update conversation status if handoff
        if handoff_triggered:
            supabase.table("conversations").update({
                "status": "escalated"
            }).eq("id", conversation_id).execute()

            # Send handoff email
            await send_handoff_email(conversation_id, data.query, context)

        return QueryResponse(
            conversation_id=conversation_id,
            user_message=data.query,
            ai_response=ai_response,
            sources=sources,
            response_time=round(response_time, 2),
            handoff_triggered=handoff_triggered
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
            resolved_at
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