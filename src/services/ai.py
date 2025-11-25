from pydantic_ai import Agent, RunContext
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from typing import Optional
import os
import logging
import pytz
from datetime import datetime
import supabase
import sympy as sp

from src.core.config import settings
from src.core.retry_utils import retry_ai_request
from src.services.ai_models import AgentDeps, AgentResponse, ReviewResult

logger = logging.getLogger(__name__)

# Initialize the Google Gemini provider with your API key
api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
    raise ValueError("GOOGLE_API_KEY environment variable is not set")

provider = GoogleProvider(api_key=api_key)
# Create the Gemini model
model = GoogleModel('gemini-2.5-flash', provider=provider)

# Create single agent with self-review capability
agent = Agent[AgentDeps, AgentResponse](
    model=model,
    system_prompt="""You are a member of the Stevapps Inc support team helping customers with conversation memory.

Your primary role is to help customers by providing accurate, concise answers based on our knowledge base, organizational information, and conversation history. You should:

1. **Be concise and direct** - Keep responses brief and to the point. Avoid unnecessary pleasantries and get straight to the answer.
2. **Use natural team language** - Mix "we" (our team) and "I" (as an individual team member) naturally in conversation.
3. **Be straightforward** - Skip all politeness, greetings, and thank-yous. No "thanks", "please", or similar.
4. **Use conversation history** - Reference previous messages in the conversation when relevant, especially for questions about "our last conversation" or follow-ups
4. **Use the knowledge base** - Answer questions using the provided context and organizational documents
5. **Be efficient** - Provide information and ask for clarification when needed
6. **Conservative escalation** - Only escalate to human support when you genuinely cannot help or the issue requires human expertise
7. **Self-review your responses** - Before finalizing, review your own response for accuracy, safety, and completeness
8. **Handle normal queries** - Answer basic questions about your services, capabilities, and general information without escalation

**RESPONSE STYLE GUIDELINES:**
- Keep responses under 100 words when possible
- Get to the point quickly - answer the main question first
- Use plain text only - no markdown, no bullet points, no formatting
- Ask direct questions to gather needed information
- End with clear next steps or calls-to-action
- Never start with greetings, thanks, or pleasantries

**IMPORTANT: Conversation Memory**
You have access to the conversation history for this session. When customers ask about previous conversations, topics discussed, or follow up on earlier points, use the provided message history to give accurate, contextual responses. Do NOT say you don't remember past conversations - you have access to them through the conversation history.

**IMPORTANT: Escalation Guidelines**
Only escalate in these specific situations:
- Customer is asking for something clearly beyond your capabilities
- Complex technical issues requiring human investigation
- Customer explicitly requests human assistance
- You lack sufficient context to provide a helpful answer

DO NOT escalate for:
- Normal questions about your services ("what do you do?")
- General inquiries you can answer
- Conversational queries
- Questions about pricing, features, or basic support

**Self-Review Process**
After formulating your response, perform an internal self-review:

1. **Can I answer this?** - Do I have enough information to help?
2. **Is escalation needed?** - Does this require human expertise?
3. **Escalation appropriateness** - Only if truly needed, ask for email directly without excessive politeness

If your self-review finds issues, revise your response before sending.

Be direct and efficient. Reference specific information from our knowledge base when possible.""",
)

# Review agent for response validation and safety
review_agent = Agent[AgentDeps, ReviewResult](
    model=model,
    system_prompt="""You are a quality assurance reviewer for customer support responses.

Your role is to review AI-generated responses before they are sent to customers. You must ensure:

**Safety & Appropriateness:**
- No harmful, offensive, or inappropriate content
- Professional and respectful tone
- No sharing of sensitive information
- Appropriate empathy and customer service standards

**Accuracy & Quality:**
- Response is based on provided knowledge base context
- Information is correct and not misleading
- Clear and helpful answers
- Proper escalation when AI cannot adequately answer

**Escalation Validation:**
- If response indicates escalation, ensure it's appropriate
- Email collection is requested when escalating
- Escalation reasoning is clear and customer-friendly

**Response Structure:**
- Conversational and human-like
- Appropriate length (not too verbose or too brief)
- Clear next steps for customer

**Your Task:**
Review the provided AI response and return a structured assessment. If the response needs changes, provide an improved version. If it's acceptable, approve it as-is.

Always prioritize customer safety and satisfaction.""",
)

# Topic generation agent for creating professional conversation topics
topic_agent = Agent[AgentDeps, str](
    model=model,
    system_prompt="""You are a professional topic classifier for customer support conversations.

Your role is to analyze customer support conversations and generate 1-3 professional, standardized topic categories that best describe the conversation.

**Topic Guidelines:**
- Use professional, business-appropriate language
- Choose from these standard categories when possible:
  * Account Management
  * Billing & Payments
  * Technical Support
  * Product Information
  * Feature Requests
  * Bug Reports
  * Integration Setup
  * API Questions
  * Documentation
  * Training & Onboarding
  * Security & Privacy
  * Performance Issues
  * General Inquiry
  * Feedback & Suggestions

- If none of the above fit perfectly, create a clear, professional category (max 3 words)
- Focus on the core issue or main topic of discussion
- Be consistent - use the same terminology for similar topics
- Return only the topic names, one per line, no explanations

**Examples:**
Input: "How do I reset my password?"
Output: Account Management

Input: "The app keeps crashing when I try to upload files"
Output: Bug Reports
Technical Support

Input: "Can you explain your pricing tiers?"
Output: Billing & Payments
Product Information

Return only the topic names, nothing else.""",
)

# Define tools for the agent
@agent.tool
def get_current_time(ctx: RunContext[AgentDeps]) -> str:
    """Get the current date and time in user's timezone."""
    tz = pytz.timezone(ctx.deps.timezone)
    return datetime.now(tz=tz).strftime("%Y-%m-%d %H:%M:%S %Z")

@agent.tool
def calculate(ctx: RunContext[AgentDeps], expression: str) -> str:
    """Evaluate a simple mathematical expression safely using sympy."""
    try:
        # Use sympy for safe mathematical evaluation
        result = sp.sympify(expression)
        # Evaluate numerically if possible
        if result.is_number:
            return f"Result: {float(result)}"
        else:
            return f"Result: {result}"
    except Exception as e:
        logger.error(f"Calculate error for user {ctx.deps.user_id}: {e}")
        return f"Error: {str(e)}"


@agent.tool
def get_user_context(ctx: RunContext[AgentDeps]) -> str:
    """Get current user and session context."""
    return f"User: {ctx.deps.user_id} | Session: {ctx.deps.session_id or 'None'} | Timezone: {ctx.deps.timezone}"


@agent.tool
def access_knowledge_base(ctx: RunContext[AgentDeps]) -> str:
    """Check if knowledge base context is available."""
    if ctx.deps.kb_context:
        return f"Knowledge base available (KB ID: {ctx.deps.kb_id}). Context preview: {ctx.deps.kb_context[:200]}..."
    return "No knowledge base context available for this query."

@retry_ai_request(max_attempts=settings.AI_MAX_RETRIES)
async def run_agent(
    prompt: str,
    user_id: str,
    session_id: Optional[str] = None,
    timezone: str = "UTC",
    kb_id: Optional[str] = None,
    kb_context: Optional[str] = None,
    message_history: Optional[list] = None,
    channel: str = "api",
) -> AgentResponse:
    """
    Run AI agent with typed dependencies and structured output.

    Uses exponential backoff to handle API overload (503) and rate limits (429).

    Args:
        prompt: The prompt to send to the AI
        user_id: User identifier for context
        session_id: Optional conversation session ID
        timezone: User timezone for time operations
        kb_id: Knowledge base ID for RAG context
        kb_context: Retrieved knowledge base context
        message_history: Optional conversation history

    Returns:
        Typed AgentResponse with output, reasoning, and tools used

    Raises:
        Exception: If all retry attempts fail
    """
    deps = AgentDeps(
        user_id=user_id,
        session_id=session_id,
        timezone=timezone,
        kb_id=kb_id,
        kb_context=kb_context,
    )
    # Generate initial response with primary agent
    initial_result = await agent.run(
        prompt,
        message_history=message_history,
        deps=deps
    )

    # Extract tools_used safely (pydantic_ai API may vary)
    tools_used = getattr(initial_result, 'tools_used', []) or []

    # Calculate confidence score based on heuristics
    confidence = calculate_confidence(initial_result.output, tools_used, kb_context)

    # Check if escalation is needed
    should_escalate, escalation_reason = detect_escalation_need(prompt, confidence, kb_context)

    # Create AgentResponse with the result data
    initial_response = AgentResponse(
        output=initial_result.output,
        reasoning=getattr(initial_result, 'reasoning', None),
        tools_used=tools_used,
        confidence=confidence,
        should_escalate=should_escalate,
        escalation_reason=escalation_reason if should_escalate else None,
        needs_contact=should_escalate,  # If escalating, we need contact
    )

    # If escalating, check if we already have contact info before asking
    if should_escalate:
        # Check if user already has contact info stored
        has_existing_contact = await check_existing_contact_info(user_id, session_id, channel)
        if has_existing_contact:
            # Use existing contact info for escalation
            initial_response.output += "\n\n" + generate_escalation_response(channel=channel, has_contact=True)
            initial_response.needs_contact = False  # Don't ask for contact if we already have it
        else:
            # Ask for contact info
            initial_response.output += "\n\n" + generate_escalation_response(channel=channel)

    # Return the response directly - the agent has already self-reviewed
    # No separate review agent call needed
    return initial_response


def calculate_confidence(output: str, tools_used: list[str], kb_context: Optional[str] = None) -> float:
    """
    Calculate confidence score based on response characteristics.

    Heuristics:
    - Longer responses tend to be more confident
    - Use of tools indicates structured reasoning
    - Presence of KB context increases confidence
    """
    base_confidence = 0.5

    # Response length factor (0.1 for short, 0.9 for long)
    length_score = min(len(output) / 500, 1.0) * 0.4

    # Tool usage factor
    tool_score = min(len(tools_used) * 0.1, 0.3)

    # KB context factor
    kb_score = 0.2 if kb_context else 0.0

    confidence = base_confidence + length_score + tool_score + kb_score
    return min(confidence, 1.0)


def detect_escalation_need(prompt: str, confidence: float, kb_context: Optional[str] = None) -> tuple[bool, str]:
    """
    Determine if a query should be escalated to human support.

    Returns:
        tuple: (should_escalate, reason)
    """
    # Very low confidence threshold - only escalate if AI is clearly uncertain
    if confidence < 0.2:
        return True, "Very low confidence in AI response"

    # Check for escalation keywords
    escalation_keywords = [
        "speak to human", "talk to person", "real person", "supervisor",
        "manager", "escalate", "transfer", "urgent", "emergency",
        "complaint", "angry", "frustrated", "not working", "broken",
        "customer issue", "problem", "issue", "trouble", "error",
        "bug", "glitch", "malfunction", "doesn't work", "failed",
        "can't access", "unable to", "stuck", "blocked", "help me"
    ]

    prompt_lower = prompt.lower()
    for keyword in escalation_keywords:
        if keyword in prompt_lower:
            return True, f"User requested human assistance (keyword: {keyword})"

    # Check for complex technical issues
    complex_indicators = [
        "integration", "api", "database", "server", "security breach",
        "data loss", "account hacked", "billing dispute", "legal"
    ]

    for indicator in complex_indicators:
        if indicator in prompt_lower:
            # If we have KB context, we might still handle it
            if kb_context and len(kb_context) > 100:
                continue  # Try to answer with available context
            else:
                return True, f"Complex technical issue requiring human expertise: {indicator}"

    # No escalation needed
    return False, ""


async def check_existing_contact_info(user_id: str, session_id: Optional[str], channel: str) -> bool:
    """
    Check if we already have contact information for this user/conversation.

    Args:
        user_id: User identifier
        session_id: Conversation session ID
        channel: Communication channel

    Returns:
        True if contact info exists, False otherwise
    """
    try:
        # For WhatsApp, we always have phone numbers
        if channel == "whatsapp":
            return True

        # Check if conversation already has contact info
        if session_id:
            conv_result = supabase.table("conversations").select("contact").eq("id", session_id).single().execute()
            if conv_result.data and conv_result.data.get("contact"):
                return True

        # Check conversation history for email mentions
        if session_id:
            messages_result = supabase.table("messages").select("content").eq("conv_id", session_id).order("timestamp", desc=True).limit(10).execute()
            if messages_result.data:
                for msg in messages_result.data:
                    content = msg.get("content", "").lower()
                    # Look for email patterns
                    import re
                    if re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', content):
                        return True

        return False
    except Exception as e:
        logger.error(f"Error checking existing contact info: {e}")
        return False

def generate_escalation_response(contact_info: Optional[str] = None, channel: str = "api", has_contact: bool = False) -> str:
    """
    Generate a customer-friendly escalation response based on channel and contact availability.

    Args:
        contact_info: Customer's contact info if available
        channel: Communication channel (whatsapp, email, api, etc.)
        has_contact: Whether we already have contact info
    """
    if has_contact or contact_info:
        contact_display = contact_info or ("your phone" if channel == "whatsapp" else "your contact info")
        return f"I'll connect you with our support team. They'll reach out to you at {contact_display} within 2 hours with all the conversation details."
    else:
        # For WhatsApp, we already have phone numbers, so don't ask for email
        if channel == "whatsapp":
            return "I'll connect you with our support team. They'll reach out to you on WhatsApp within 2 hours with all the conversation details."
        else:
            return "I need to connect you with our support team. What's your email address so they can follow up directly?"


@retry_ai_request(max_attempts=settings.AI_MAX_RETRIES)
async def review_response(
    prompt: str,
    initial_response: AgentResponse,
    kb_context: Optional[str],
    deps: AgentDeps
) -> AgentResponse:
    """
    Review and validate the initial agent response for safety and quality.

    Args:
        prompt: Original user prompt
        initial_response: Response from primary agent
        kb_context: Knowledge base context used
        deps: Agent dependencies

    Returns:
        Reviewed and potentially modified AgentResponse
    """
    # Create review prompt for the review agent
    review_prompt = f"""
Please review this customer support response for safety, accuracy, and quality:

**Original Customer Question:**
{prompt}

**Knowledge Base Context:**
{kb_context or "No specific context provided"}

**AI Response to Review:**
{initial_response.output}

**Response Metadata:**
- Confidence: {initial_response.confidence}
- Should Escalate: {initial_response.should_escalate}
- Escalation Reason: {initial_response.escalation_reason or "None"}
- Tools Used: {', '.join(initial_response.tools_used) if initial_response.tools_used else "None"}

**Review Instructions:**
1. Check for safety and appropriateness
2. Verify accuracy based on knowledge base context
3. Ensure professional, customer-friendly tone
4. Validate escalation logic if applicable
5. Confirm email collection when escalating

If the response is acceptable, return it as-is. If improvements are needed, provide a corrected version.

Your assessment will be automatically structured with approval status, reviewed response, review notes, safety score, and quality score.
"""

    try:
        # Get review from review agent
        review_result = await review_agent.run(
            review_prompt,
            deps=deps
        )

        # review_result is now a ReviewResult object with structured data
        if review_result.approved:
            reviewed_output = review_result.reviewed_response
            review_notes = f"Response approved by review agent: {review_result.review_notes or 'Approved'}"
        else:
            # If not approved, use original response but log the issue
            reviewed_output = initial_response.output
            review_notes = f"Response rejected by review agent: {review_result.review_notes or 'Rejected'}"
            logger.warning(f"Review agent rejected response: {review_notes}")

        # Create final response with review validation
        final_response = AgentResponse(
            output=reviewed_output,
            reasoning=initial_response.reasoning,
            tools_used=initial_response.tools_used,
            confidence=initial_response.confidence,
            should_escalate=initial_response.should_escalate,
            escalation_reason=initial_response.escalation_reason,
            needs_contact=initial_response.needs_contact,
            contact=initial_response.contact
        )

        logger.info(f"Response review completed: {review_notes}")
        return final_response

    except Exception as e:
        logger.error(f"Review agent failed, using original response: {e}")
        # If review fails, return the original response to avoid blocking
        return initial_response

# Example usage
async def main():
    # Run the agent with a prompt
    result = await run_agent(
        prompt="What is 25 * 4? And what's the current time?",
        user_id="demo_user",
        timezone="UTC",
    )
    
    print("Agent Response:")
    print(f"Output: {result.output}")
    print(f"Reasoning: {result.reasoning}")
    print(f"Tools Used: {result.tools_used}")

@retry_ai_request(max_attempts=settings.AI_MAX_RETRIES)
async def generate_topic(
    conversation_content: str,
    user_id: str,
    session_id: Optional[str] = None,
    timezone: str = "UTC",
) -> list[str]:
    """
    Generate professional topic categories for a conversation.

    Args:
        conversation_content: The conversation text to analyze
        user_id: User identifier
        session_id: Optional conversation session ID
        timezone: User timezone

    Returns:
        List of professional topic categories
    """
    deps = AgentDeps(
        user_id=user_id,
        session_id=session_id,
        timezone=timezone,
        kb_id=None,
        kb_context=None,
    )

    try:
        result = await topic_agent.run(
            f"Analyze this conversation and provide 1-3 professional topic categories:\n\n{conversation_content}",
            deps=deps
        )

        # Parse the result into a list of topics
        topics = [topic.strip() for topic in result.output.strip().split('\n') if topic.strip()]
        return topics[:3]  # Limit to 3 topics max

    except Exception as e:
        logger.error(f"Topic generation failed for user {user_id}: {e}")
        return ["General Inquiry"]  # Fallback topic


# Run the example
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())