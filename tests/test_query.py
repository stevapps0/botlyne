"""Test query endpoints with JWT and API key authentication."""
import pytest
from unittest.mock import MagicMock, patch
from main import app
from src.core.auth import get_current_user
from src.core.auth_utils import TokenData


def test_query_kb_with_jwt(client, sample_kb, sample_user, jwt_token):
    """Test querying knowledge base with JWT authentication."""
    auth_headers = {"Authorization": f"Bearer {jwt_token}"}

    # Override dependency
    app.dependency_overrides[get_current_user] = lambda: TokenData(
        user_id=sample_user["id"], 
        org_id=sample_user["org_id"], 
        kb_id=sample_kb["id"]
    )

    try:
        # Patch supabase in query module
        with patch('src.api.v1.query.supabase') as mock_supabase:
            # Setup mock for KB verification chain
            mock_kb_check = MagicMock()
            mock_kb_check.data = {"org_id": sample_user["org_id"]}
            
            # Setup mock for conversation lookup
            mock_conv_result = MagicMock()
            mock_conv_result.data = []  # No existing conversation
            
            # Setup mock for conversation creation
            mock_new_conv = MagicMock()
            mock_new_conv.data = [{"id": "conv-123", "ticket_number": "ABC123"}]
            
            # Setup mock for final conversation fetch (for ticket number)
            mock_final_conv = MagicMock()
            mock_final_conv.data = {"ticket_number": "ABC123"}
            
            # Configure table().select().eq().single().execute() chain
            # This will be called multiple times, so use side_effect
            mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.side_effect = [
                mock_kb_check,  # First call: KB verification
                mock_final_conv,  # Last call: ticket number fetch
            ]
            
            # Configure table().select().eq().eq().eq().order().limit().execute() for conversation lookup
            mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_conv_result
            
            # Configure table().insert().execute() for conversation creation
            mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_new_conv
            
            # Configure table().select().eq().order().execute() for message retrieval (empty history)
            mock_msg_result = MagicMock()
            mock_msg_result.data = []
            mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_msg_result
            
            # Mock upsert for metrics
            mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock()
            
            # Mock update for conversation status
            mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

            # Mock similarity search
            with patch('src.services.retrieval.retrieval_service.search_similar') as mock_retrieve:
                mock_retrieve.return_value = [{
                    "content": "Sample document content",
                    "metadata": {"source": "test.pdf"},
                    "similarity": 0.85,
                    "id": "doc-1"
                }]

                # Mock AI response
                with patch('src.services.ai.agent.run') as mock_agent_run:
                    mock_result = MagicMock()
                    mock_result.output = "This is the AI response."
                    mock_agent_run.return_value = mock_result

                    response = client.post("/api/v1/query",
                                          json={
                                              "query": "What is machine learning?",
                                              "kb_id": sample_kb["id"],
                                              "user_id": sample_user["id"]
                                          },
                                          headers=auth_headers)

                    assert response.status_code == 200
                    data = response.json()
                    assert "ai_response" in data
                    assert data["ai_response"] == "This is the AI response."
    finally:
        app.dependency_overrides = {}


def test_query_kb_with_api_key(client, sample_kb, api_key_token):
    """Test querying knowledge base with API key authentication."""
    auth_headers = {"Authorization": f"Bearer {api_key_token}"}

    # Override dependency
    app.dependency_overrides[get_current_user] = lambda: TokenData(
        user_id="550e8400-e29b-41d4-a716-446655440000",
        org_id="550e8400-e29b-41d4-a716-446655440001",
        kb_id=None,
        api_key_id="sk-api-key-id"
    )

    try:
        with patch('src.api.v1.query.supabase') as mock_supabase:
            # Setup mocks similar to JWT test
            mock_kb_check = MagicMock()
            mock_kb_check.data = {"org_id": "550e8400-e29b-41d4-a716-446655440001"}
            
            # Mock for API key lookup (for uploader resolution)
            mock_api_key = MagicMock()
            mock_api_key.data = {"created_by": "550e8400-e29b-41d4-a716-446655440000"}
            
            mock_conv_result = MagicMock()
            mock_conv_result.data = []
            
            mock_new_conv = MagicMock()
            mock_new_conv.data = [{"id": "conv-456", "ticket_number": "DEF456"}]
            
            mock_final_conv = MagicMock()
            mock_final_conv.data = {"ticket_number": "DEF456"}
            
            # side_effect for multiple calls
            mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.side_effect = [
                mock_kb_check,
                mock_api_key,
                mock_final_conv,
            ]
            
            mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_conv_result
            mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_new_conv
            
            mock_msg_result = MagicMock()
            mock_msg_result.data = []
            mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_msg_result
            
            mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock()

            with patch('src.services.retrieval.retrieval_service.search_similar') as mock_retrieve:
                mock_retrieve.return_value = [{
                    "content": "API key content",
                    "metadata": {"source": "doc.pdf"},
                    "similarity": 0.82
                }]

                with patch('src.services.ai.agent.run') as mock_agent_run:
                    mock_result = MagicMock()
                    mock_result.output = "API key response."
                    mock_agent_run.return_value = mock_result

                    response = client.post("/api/v1/query",
                                          json={
                                              "query": "Test query",
                                              "kb_id": sample_kb["id"],
                                              "user_id": "550e8400-e29b-41d4-a716-446655440000"
                                          },
                                          headers=auth_headers)

                    assert response.status_code == 200
    finally:
        app.dependency_overrides = {}


def test_query_requires_auth(client):
    """Test that query endpoints require authentication."""
    # Ensure no overrides
    app.dependency_overrides = {}
    response = client.post("/api/v1/query",
                          json={"query": "Test", "kb_id": "test-id", "user_id": "test-user"})
    assert response.status_code == 403


def test_query_requires_kb_id(client, jwt_token):
    """Test that query requires kb_id."""
    auth_headers = {"Authorization": f"Bearer {jwt_token}"}

    app.dependency_overrides[get_current_user] = lambda: TokenData(
        user_id="550e8400-e29b-41d4-a716-446655440000", 
        org_id="550e8400-e29b-41d4-a716-446655440001"
    )

    try:
        response = client.post("/api/v1/query",
                              json={"query": "Test", "user_id": "550e8400-e29b-41d4-a716-446655440000"},
                              headers=auth_headers)

        assert response.status_code in [400, 422]
    finally:
        app.dependency_overrides = {}


def test_query_requires_query_text(client, sample_kb, jwt_token):
    """Test that query requires query text."""
    auth_headers = {"Authorization": f"Bearer {jwt_token}"}

    app.dependency_overrides[get_current_user] = lambda: TokenData(
        user_id="550e8400-e29b-41d4-a716-446655440000", 
        org_id="550e8400-e29b-41d4-a716-446655440001"
    )

    try:
        response = client.post("/api/v1/query",
                              json={"kb_id": sample_kb["id"], "user_id": "550e8400-e29b-41d4-a716-446655440000"},
                              headers=auth_headers)

        assert response.status_code in [400, 422]
    finally:
        app.dependency_overrides = {}
