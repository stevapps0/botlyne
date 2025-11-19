"""Test AI service layer with typed agent responses."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.services.ai_service import AIService
from src.services.ai_models import AgentResponse, AgentDeps


@pytest.mark.asyncio
async def test_ai_service_query():
    """Test AIService.query with typed response."""
    with patch('src.services.ai_service.run_agent') as mock_run:
        # Mock agent response
        mock_response = AgentResponse(
            output="Test response",
            reasoning="Reasoning here",
            tools_used=["calculate", "get_current_time"],
            confidence=0.95
        )
        mock_run.return_value = mock_response
        mock_run = AsyncMock(return_value=mock_response)
        
        with patch('src.services.ai_service.run_agent', mock_run):
            result = await AIService.query(
                prompt="What is 2+2?",
                user_id="test_user",
                session_id="session_123",
                timezone="UTC",
            )
        
        assert result.output == "Test response"
        assert result.reasoning == "Reasoning here"
        assert "calculate" in result.tools_used
        assert result.confidence == 0.95


@pytest.mark.asyncio
async def test_ai_service_query_with_context():
    """Test AIService.query_with_context with document context."""
    with patch('src.services.ai_service.run_agent') as mock_run:
        mock_response = AgentResponse(
            output="Based on the context, the answer is...",
            reasoning="Used KB context",
            tools_used=["access_knowledge_base"],
            confidence=0.88
        )
        mock_run = AsyncMock(return_value=mock_response)
        
        with patch('src.services.ai_service.run_agent', mock_run):
            docs = [
                {
                    "content": "Machine learning is a subset of AI",
                    "source": "wiki.pdf",
                    "similarity": 0.92
                },
                {
                    "content": "ML algorithms learn from data",
                    "source": "tutorial.md",
                    "similarity": 0.85
                }
            ]
            
            result = await AIService.query_with_context(
                prompt="What is machine learning?",
                user_id="test_user",
                relevant_docs=docs,
                kb_id="kb_123",
            )
        
        assert result.output == "Based on the context, the answer is..."
        assert "KB context" in result.reasoning
        assert "access_knowledge_base" in result.tools_used


@pytest.mark.asyncio
async def test_ai_service_error_handling():
    """Test AIService error handling and logging."""
    with patch('src.services.ai_service.run_agent') as mock_run:
        mock_run = AsyncMock(side_effect=Exception("API Error"))
        
        with patch('src.services.ai_service.run_agent', mock_run):
            with pytest.raises(Exception):
                await AIService.query(
                    prompt="Test",
                    user_id="test_user"
                )


@pytest.mark.asyncio
async def test_agent_deps_creation():
    """Test AgentDeps model validation."""
    deps = AgentDeps(
        user_id="user_123",
        session_id="session_456",
        timezone="US/Eastern",
        kb_id="kb_789",
        kb_context="Sample context"
    )
    
    assert deps.user_id == "user_123"
    assert deps.session_id == "session_456"
    assert deps.timezone == "US/Eastern"
    assert deps.kb_id == "kb_789"
    assert deps.kb_context == "Sample context"


def test_agent_response_validation():
    """Test AgentResponse model validation."""
    response = AgentResponse(
        output="Test output",
        reasoning="Test reasoning",
        tools_used=["tool1", "tool2"],
        confidence=0.85
    )
    
    assert response.output == "Test output"
    assert response.reasoning == "Test reasoning"
    assert len(response.tools_used) == 2
    assert response.confidence == 0.85
    
    # Test confidence bounds
    with pytest.raises(ValueError):
        AgentResponse(
            output="Test",
            confidence=1.5  # Out of bounds
        )
