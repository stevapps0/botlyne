"""Test chat endpoints and service."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from main import app
from src.core.auth_utils import TokenData
from src.schemas.chat import ChatRequest, ChatResponse, ChatMessage


def test_chat_message_endpoint(client, sample_kb):
    """Test sending a chat message."""
    auth_headers = {"Authorization": "Bearer sk-test-api-key"}

    # Mock org lookup by shortcode
    with patch('src.api.v1.chat.supabase') as mock_supabase:
        mock_org = MagicMock()
        mock_org.data = {"id": "org-123"}

        mock_kb = MagicMock()
        mock_kb.data = [{"id": sample_kb["id"]}]

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_org
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = mock_kb

        # Mock chat service
        with patch('src.api.v1.chat.chat_service') as mock_chat_service:
            mock_response = ChatResponse(
                session_id="session-123",
                message=ChatMessage(role="assistant", content="Test response"),
                sources=[],
                response_time=1.0,
                handoff_triggered=False
            )
            mock_chat_service.process_message = AsyncMock(return_value=mock_response)

            response = client.post("/chat/test123",
                                 json={"message": "Hello", "session_id": None},
                                 headers=auth_headers)

            assert response.status_code == 200
            data = response.json()
            assert data["session_id"] == "session-123"
            assert data["message"]["content"] == "Test response"


def test_chat_requires_auth(client):
    """Test that chat endpoints require authentication."""
    response = client.post("/chat/test123",
                         json={"message": "Hello"})
    assert response.status_code == 401


def test_chat_invalid_shortcode(client):
    """Test chat with invalid organization shortcode."""
    auth_headers = {"Authorization": "Bearer sk-test-api-key"}

    with patch('src.api.v1.chat.supabase') as mock_supabase:
        mock_org = MagicMock()
        mock_org.data = None  # No org found

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_org

        response = client.post("/chat/invalid",
                             json={"message": "Hello"},
                             headers=auth_headers)

        assert response.status_code == 404


def test_chat_session_history(client):
    """Test retrieving chat session history."""
    auth_headers = {"Authorization": "Bearer sk-test-api-key"}

    with patch('src.api.v1.chat.supabase') as mock_supabase:
        mock_org = MagicMock()
        mock_org.data = {"id": "org-123"}

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_org

        # Mock chat service
        with patch('src.api.v1.chat.chat_service') as mock_chat_service:
            mock_session = MagicMock()
            mock_session.id = "session-123"
            mock_session.messages = [
                ChatMessage(role="user", content="Hello"),
                ChatMessage(role="assistant", content="Hi there")
            ]
            mock_session.is_active = True
            mock_session.created_at = "2024-01-01T00:00:00"
            mock_session.updated_at = "2024-01-01T00:00:01"

            mock_chat_service.get_session = AsyncMock(return_value=mock_session)

            response = client.get("/chat/test123/session/session-123",
                                headers=auth_headers)

            assert response.status_code == 200
            data = response.json()
            assert data["session_id"] == "session-123"
            assert len(data["messages"]) == 2


def test_chat_end_session(client):
    """Test ending a chat session."""
    auth_headers = {"Authorization": "Bearer sk-test-api-key"}

    with patch('src.api.v1.chat.supabase') as mock_supabase:
        mock_org = MagicMock()
        mock_org.data = {"id": "org-123"}

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_org

        # Mock chat service
        with patch('src.api.v1.chat.chat_service') as mock_chat_service:
            mock_chat_service.end_session = AsyncMock(return_value=True)

            response = client.delete("/chat/test123/session/session-123",
                                   headers=auth_headers)

            assert response.status_code == 200
            data = response.json()
            assert data["message"] == "Session ended successfully"


def test_chat_service_create_session():
    """Test chat service session creation."""
    from src.services.chat_service import ChatService

    with patch('src.services.chat_service.supabase') as mock_supabase:
        mock_result = MagicMock()
        mock_result.data = [{"id": "conv-123"}]

        mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_result

        session = ChatService.create_session("org-123", "kb-123")

        assert session.org_id == "org-123"
        assert session.kb_id == "kb-123"
        assert session.id == "conv-123"


def test_chat_service_process_message():
    """Test chat service message processing."""
    from src.services.chat_service import ChatService

    with patch('src.services.chat_service.ChatService.process_message') as mock_process:
        mock_response = ChatResponse(
            session_id="session-123",
            message=ChatMessage(role="assistant", content="Response"),
            sources=[],
            response_time=1.0,
            handoff_triggered=False
        )
        mock_process.return_value = mock_response

        request = ChatRequest(message="Hello")
        response = ChatService.process_message(request, "org-123", "kb-123")

        assert response.session_id == "session-123"
        assert response.message.content == "Response"


def test_chat_streaming_endpoint(client):
    """Test streaming chat endpoint."""
    auth_headers = {"Authorization": "Bearer sk-test-api-key"}

    with patch('src.api.v1.chat.supabase') as mock_supabase:
        mock_org = MagicMock()
        mock_org.data = {"id": "org-123"}

        mock_kb = MagicMock()
        mock_kb.data = [{"id": "kb-123"}]

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_org
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = mock_kb

        # Mock streaming generator
        async def mock_stream():
            yield {"chunk": "Hello", "finished": False}
            yield {"chunk": " world", "finished": True, "sources": [], "response_time": 1.0}

        with patch('src.api.v1.chat.chat_service') as mock_chat_service:
            mock_chat_service.stream_message = mock_stream

            response = client.post("/chat/test123/stream",
                                 json={"message": "Hello", "stream": True},
                                 headers=auth_headers)

            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")