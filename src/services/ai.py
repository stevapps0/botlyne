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
from src.services.ai_models import AgentDeps, AgentResponse

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
    system_prompt="""You are a helpful AI assistant powered by Openlyne.
    You provide clear, concise answers and can help with a variety of tasks.
    Be friendly and professional in your responses.
    When using tools, explain what you're doing and provide reasoning for your responses.""",
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
    result = await agent.run(
        prompt,
        message_history=message_history,
        deps=deps
    )

    # Calculate confidence score based on heuristics
    confidence = calculate_confidence(result.output, result.tools_used, kb_context)

    # Update the result with confidence
    result.confidence = confidence

    return result


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