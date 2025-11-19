from pydantic_ai import Agent, RunContext
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from typing import Optional
import os
import logging
import pytz
from datetime import datetime
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

# Create typed agent with AgentDeps and AgentResponse
agent = Agent[AgentDeps, AgentResponse](
    model=model,
    system_prompt="""You are a knowledgeable customer support assistant for our organization.

Your primary role is to help customers by providing accurate answers based on our knowledge base and organizational information. You should:

1. **Be conversational and friendly** - Talk like a human support agent, not a robot
2. **Use the knowledge base** - Answer questions using the provided context and organizational documents
3. **Be helpful and proactive** - Offer additional assistance and anticipate customer needs
4. **Know your limits** - If you cannot confidently answer a question, escalate to human support
5. **Collect information when needed** - Ask for email address before escalating so support can follow up

When you need to escalate:
- Explain why you're escalating (be honest about limitations)
- Politely ask for their email address for follow-up
- Assure them that human support will help
- Keep the conversation natural and empathetic

Always maintain a professional, helpful, and customer-focused tone. Reference specific information from our knowledge base when possible.""",
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
        needs_email=should_escalate,  # If escalating, we need email
    )

    # If escalating, modify the response to be more customer-friendly
    if should_escalate:
        initial_response.output += "\n\n" + generate_escalation_response()

    # Review the response with the review agent
    reviewed_result = await review_response(
        prompt=prompt,
        initial_response=initial_response,
        kb_context=kb_context,
        deps=deps
    )

    return reviewed_result


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
    # Low confidence threshold
    if confidence < 0.3:
        return True, "Low confidence in AI response"

    # Check for escalation keywords
    escalation_keywords = [
        "speak to human", "talk to person", "real person", "supervisor",
        "manager", "escalate", "transfer", "urgent", "emergency",
        "complaint", "angry", "frustrated", "not working", "broken"
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


def generate_escalation_response(customer_email: Optional[str] = None) -> str:
    """
    Generate a customer-friendly escalation response.
    """
    if customer_email:
        return f"Thank you for providing your email. Our support team will reach out to you at {customer_email} within 2 hours to help resolve this issue. I've shared all the details from our conversation so they can assist you immediately."
    else:
        return "I'd be happy to connect you with our support team so they can help resolve this for you. Could you please share your email address so they can follow up directly?"


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
            needs_email=initial_response.needs_email,
            customer_email=initial_response.customer_email
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

# Run the example
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())