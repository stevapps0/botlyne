from pydantic_ai import Agent, RunContext
from pydantic_ai.models.google import GoogleModel
from src.services.ai import agent as base_agent

# Re-export the agent from services.ai for backward compatibility
agent = base_agent