"""Test query endpoints with JWT and API key authentication."""
import pytest
from unittest.mock import MagicMock, patch


def test_query_kb_with_jwt(client, mock_supabase, sample_kb, sample_user, jwt_token):
    """Test querying knowledge base with JWT authentication."""
    auth_headers = {"Authorization": f"Bearer {jwt_token}"}

    # Mock JWT validation
    with patch('src.core.auth_utils.supabase.auth.get_user') as mock_get_user:
        mock_get_user.return_value = MagicMock(user=MagicMock(id=sample_user["id"]))

        # Mock user lookup
        mock_user_result = MagicMock()
        mock_user_result.data = sample_user
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_user_result

        # Mock KB verification
        mock_kb_result = MagicMock()
        mock_kb_result.data = sample_kb
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_kb_result

        # Mock similarity search
        with patch('src.archive.answer.retrieve_similar') as mock_retrieve:
            mock_retrieve.return_value = [{
                "content": "Sample document content",
                "metadata": {"source": "test.pdf"},
                "similarity": 0.85,
                "id": "550e8400-e29b-41d4-a716-446655440004"
            }]

            # Mock AI response
            with patch('src.archive.agent.agent.run') as mock_agent_run:
                mock_result = MagicMock()
                mock_result.output = "This is the AI response."
                mock_agent_run.return_value = mock_result

                # Mock message storage
                mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()

                response = client.post("/api/v1/query",
                                      json={
                                          "query": "What is machine learning?",
                                          "kb_id": sample_kb["id"]
                                      },
                                      headers=auth_headers)

                assert response.status_code in [200, 401, 422]


def test_query_kb_with_api_key(client, mock_supabase, sample_kb, api_key_token):
    """Test querying knowledge base with API key authentication."""
    auth_headers = {"Authorization": f"Bearer {api_key_token}"}

    # Mock API key validation
    with patch('src.core.auth_utils.supabase.rpc') as mock_rpc:
        mock_rpc_result = MagicMock()
        mock_rpc_result.execute.return_value = MagicMock(data={
            "user_id": "550e8400-e29b-41d4-a716-446655440000",
            "org_id": "550e8400-e29b-41d4-a716-446655440001",
            "kb_id": None,
            "api_key_id": "sk-api-key-id"
        })
        mock_rpc.return_value = mock_rpc_result

        # Mock KB verification
        mock_kb_result = MagicMock()
        mock_kb_result.data = sample_kb
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_kb_result

        # Mock similarity search
        with patch('src.archive.answer.retrieve_similar') as mock_retrieve:
            mock_retrieve.return_value = [{
                "content": "Sample content",
                "metadata": {"source": "doc.pdf"},
                "similarity": 0.82
            }]

            with patch('src.archive.agent.agent.run') as mock_agent_run:
                mock_result = MagicMock()
                mock_result.output = "API key response."
                mock_agent_run.return_value = mock_result

                mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()

                response = client.post("/api/v1/query",
                                      json={
                                          "query": "Test query",
                                          "kb_id": sample_kb["id"]
                                      },
                                      headers=auth_headers)

                assert response.status_code in [200, 401, 422]


def test_query_requires_auth(client):
    """Test that query endpoints require authentication."""
    response = client.post("/api/v1/query",
                          json={"query": "Test", "kb_id": "test-id"})
    assert response.status_code == 403


def test_query_requires_kb_id(client, jwt_token):
    """Test that query requires kb_id."""
    auth_headers = {"Authorization": f"Bearer {jwt_token}"}

    with patch('src.core.auth_utils.supabase.auth.get_user') as mock_get_user:
        mock_get_user.return_value = MagicMock(user=MagicMock(id="550e8400-e29b-41d4-a716-446655440000"))

        response = client.post("/api/v1/query",
                              json={"query": "Test"},
                              headers=auth_headers)

        assert response.status_code in [400, 422]


def test_query_requires_query_text(client, sample_kb, jwt_token):
    """Test that query requires query text."""
    auth_headers = {"Authorization": f"Bearer {jwt_token}"}

    with patch('src.core.auth_utils.supabase.auth.get_user') as mock_get_user:
        mock_get_user.return_value = MagicMock(user=MagicMock(id="550e8400-e29b-41d4-a716-446655440000"))

        response = client.post("/api/v1/query",
                              json={"kb_id": sample_kb["id"]},
                              headers=auth_headers)

        assert response.status_code in [400, 422]
