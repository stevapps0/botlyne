from pydantic_ai import Agent, RunContext
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from typing import Any, Optional
import os
import logging

from src.core.config import settings
from src.core.retry_utils import retry_ai_request

logger = logging.getLogger(__name__)

# Initialize the Google Gemini provider with your API key
api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
    raise ValueError("GOOGLE_API_KEY environment variable is not set")

provider = GoogleProvider(api_key=api_key)
# Create the Gemini model
model = GoogleModel('gemini-2.5-flash', provider=provider)

# Create the agent with the Gemini model
agent = Agent(
    model=model,
    system_prompt="""You are a helpful AI assistant powered by Google Gemini. 
    You provide clear, concise answers and can help with a variety of tasks.
    Be friendly and professional in your responses.""",
)

# Define tools for the agent
@agent.tool
def get_current_time(ctx: RunContext[None]) -> str:
    """Get the current date and time."""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@agent.tool
def calculate(ctx: RunContext[None], expression: str) -> str:
    """Evaluate a simple mathematical expression."""
    try:
        # Only allow safe math operations
        allowed_names = {
            'abs': abs, 'round': round, 'min': min, 'max': max,
            'sum': sum, 'pow': pow
        }
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return f"Result: {result}"
    except Exception as e:
        return f"Error: {str(e)}"

@retry_ai_request(max_attempts=settings.AI_MAX_RETRIES)
async def run_with_retry(
    prompt: str, 
    message_history: Optional[list] = None, 
    deps: Any = None
):
    """
    Run AI agent with automatic retry on transient failures.
    
    Uses exponential backoff to handle API overload (503) and rate limits (429).
    
    Args:
        prompt: The prompt to send to the AI
        message_history: Optional conversation history
        deps: Optional dependencies for the agent
    
    Returns:
        Agent result with output
    
    Raises:
        Exception: If all retry attempts fail
    """
    result = await agent.run(
        prompt, 
        message_history=message_history, 
        deps=deps
    )
    return result

# Example usage
async def main():
    # Run the agent with a prompt
    result = await agent.run(
        "What is 25 * 4? And what's the current time and zone and country?",
    )
    
    print("Agent Response:")
    print(result.output)

# Run the example
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())