from fastapi import APIRouter, HTTPException, status, Depends
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

# Pydantic models for dependencies
class TokenData(BaseModel):
    user_id: str
    org_id: str | None = None

# Dependency to get current user
async def get_current_user(token: str = Depends(lambda: None)):
    """Extract and validate user from JWT token."""
    try:
        # This is a simplified version - in real implementation you'd validate the token
        # For now, return a mock user
        return TokenData(user_id="mock_user", org_id="mock_org")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed"
        )

router = APIRouter()

# Pydantic models
class QueryRequest(BaseModel):
    query: str
    kb_id: str
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
        # Verify KB access
        kb_check = supabase.table("knowledge_bases").select("org_id").eq("id", data.kb_id).single().execute()
        if not kb_check.data or kb_check.data["org_id"] != current_user.org_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Get or create conversation
        conversation_id = data.conversation_id
        if not conversation_id:
            conv_result = supabase.table("conversations").insert({
                "user_id": current_user.user_id,
                "kb_id": data.kb_id
            }).execute()
            conversation_id = conv_result.data[0]["id"]
        else:
            # Verify conversation ownership
            conv_check = supabase.table("conversations").select("user_id").eq("id", conversation_id).single().execute()
            if not conv_check.data or conv_check.data["user_id"] != current_user.user_id:
                raise HTTPException(status_code=403, detail="Access denied")

        # Retrieve similar documents
        similar_docs = retrieve_similar(data.query, limit=5, table_name="documents")

        # Format context for agent
        context = ""
        sources = []
        for doc in similar_docs:
            similarity = doc.get("similarity", 0)
            content = doc.get("content", "")
            metadata = doc.get("metadata", {})

            context += f"\n[Source] (Similarity: {similarity:.2%})\n{content}\n"
            sources.append({
                "content": content[:200] + "..." if len(content) > 200 else content,
                "similarity": similarity,
                "metadata": metadata
            })

        # Generate AI response
        system_prompt = f"""You are a helpful AI assistant answering questions based on the provided knowledge base context.

Context from knowledge base:
{context}

Answer the user's question using the context above. If the context doesn't contain relevant information, say so clearly.
Be concise but helpful."""

        # Use Pydantic AI agent
        result = await agent.run(
            data.query,
            message_history=[],  # Could implement conversation history
            deps=None
        )

        ai_response = result.output
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