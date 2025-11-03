"""Test query endpoints."""
import pytest
from unittest.mock import MagicMock, patch


def test_query_knowledge_base(client, mock_supabase, sample_kb, sample_user, auth_headers):
    """Test querying knowledge base with AI."""
    # Mock KB verification
    mock_kb_result = MagicMock()
    mock_kb_result.data = sample_kb
    mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_kb_result

    # Mock conversation creation
    mock_conv_result = MagicMock()
    mock_conv_result.data = [{"id": "550e8400-e29b-41d4-a716-446655440003"}]
    mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_conv_result

    # Mock conversation ownership check
    mock_conv_check = MagicMock()
    mock_conv_check.data = {"user_id": sample_user["id"]}
    mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_conv_check

    # Mock similarity search
    with patch('src.archive.answer.retrieve_similar') as mock_retrieve:
        mock_retrieve.return_value = [{
            "content": "Sample document content",
            "metadata": {"source": "test.pdf"},
            "similarity": 0.85,
            "id": "550e8400-e29b-41d4-a716-446655440004"
        }]

        # Mock AI agent
        with patch('src.archive.agent.agent.run') as mock_agent_run:
            mock_result = MagicMock()
            mock_result.output = "This is the AI response based on the knowledge base."
            mock_agent_run.return_value = mock_result

            # Mock message storage
            mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()

            # Mock metrics storage
            mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

            response = client.post("/api/v1/query",
                                  json={
                                      "query": "What is machine learning?",
                                      "kb_id": sample_kb["id"]
                                  },
                                  headers=auth_headers)

            assert response.status_code == 200
            data = response.json()
            assert "conversation_id" in data
            assert "user_message" in data
            assert "ai_response" in data
            assert "sources" in data
            assert "response_time" in data
            assert data["user_message"] == "What is machine learning?"
            assert len(data["sources"]) > 0


def test_list_conversations(client, mock_supabase, sample_user, auth_headers):
    """Test listing user conversations."""
    # Mock conversations query
    mock_conv_result = MagicMock()
    mock_conv_result.data = [{
        "id": "550e8400-e29b-41d4-a716-446655440003",
        "kb_id": "550e8400-e29b-41d4-a716-446655440002",
        "status": "ongoing",
        "started_at": "2024-01-01T00:00:00Z",
        "resolved_at": None
    }]
    mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.desc.return_value.execute.return_value = mock_conv_result

    # Mock messages query
    mock_msg_result = MagicMock()
    mock_msg_result.data = [{
        "id": "550e8400-e29b-41d4-a716-446655440004",
        "conv_id": "550e8400-e29b-41d4-a716-446655440003",
        "sender": "user",
        "content": "Hello",
        "timestamp": "2024-01-01T00:00:00Z"
    }]
    mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = mock_msg_result

    response = client.get("/api/v1/conversations", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "550e8400-e29b-41d4-a716-446655440003"
    assert "messages" in data[0]


def test_resolve_conversation(client, mock_supabase, sample_user, auth_headers):
    """Test resolving a conversation."""
    conv_id = "550e8400-e29b-41d4-a716-446655440003"

    # Mock conversation ownership check
    mock_conv_check = MagicMock()
    mock_conv_check.data = {"user_id": sample_user["id"]}
    mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_conv_check

    # Mock conversation update
    mock_update_result = MagicMock()
    mock_update_result.data = None
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_update_result

    response = client.post(f"/api/v1/conversations/{conv_id}/resolve",
                          json={"satisfaction_score": 5},
                          headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert "message" in data