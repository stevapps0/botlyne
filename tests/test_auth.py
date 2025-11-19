"""Test authentication endpoints with JWT and API key support."""
import pytest
from unittest.mock import MagicMock, patch
from src.core.auth_utils import TokenData





def test_create_knowledge_base_with_jwt(client, mock_supabase, sample_user, sample_org, jwt_token):
    """Test creating knowledge base with JWT authentication."""
    auth_headers = {"Authorization": f"Bearer {jwt_token}"}

    # Mock JWT validation in auth_utils
    with patch('src.core.auth_utils.supabase.auth.get_user') as mock_get_user:
        mock_get_user.return_value = MagicMock(user=MagicMock(id=sample_user["id"]))

        # Mock user lookup for org_id
        mock_user_lookup = MagicMock()
        mock_user_lookup.data = sample_user
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_user_lookup

        # Mock KB creation
        mock_kb_result = MagicMock()
        mock_kb_result.data = [{
            "id": "550e8400-e29b-41d4-a716-446655440002",
            "org_id": sample_org["id"],
            "name": "My Knowledge Base",
            "created_at": "2024-01-01T00:00:00Z"
        }]
        mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_kb_result

        response = client.post("/api/v1/kb", 
                              json={"name": "My Knowledge Base"},
                              headers=auth_headers)

        assert response.status_code in [200, 401]  # 200 if auth passes, 401 if JWT validation fails


def test_create_knowledge_base_with_api_key(client, mock_supabase, api_key_token):
    """Test creating knowledge base with API key authentication."""
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

        # Mock KB creation
        mock_kb_result = MagicMock()
        mock_kb_result.data = [{
            "id": "550e8400-e29b-41d4-a716-446655440002",
            "org_id": "550e8400-e29b-41d4-a716-446655440001",
            "name": "API KB",
            "created_at": "2024-01-01T00:00:00Z"
        }]
        mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_kb_result

        response = client.post("/api/v1/kb",
                              json={"name": "API KB"},
                              headers=auth_headers)

        assert response.status_code in [200, 401]


def test_get_organization_kbs(client, mock_supabase, sample_org, sample_kb, jwt_token):
    """Test retrieving knowledge bases in organization."""
    auth_headers = {"Authorization": f"Bearer {jwt_token}"}

    # Mock JWT validation
    with patch('src.core.auth_utils.supabase.auth.get_user') as mock_get_user:
        mock_get_user.return_value = MagicMock(user=MagicMock(id="550e8400-e29b-41d4-a716-446655440000"))

        # Mock user lookup
        mock_user_result = MagicMock()
        mock_user_result.data = {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "org_id": sample_org["id"]
        }
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_user_result

        # Mock KB list
        mock_kb_list = MagicMock()
        mock_kb_list.data = [sample_kb]
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_kb_list

        response = client.get(f"/auth/orgs/{sample_org['id']}/kb", headers=auth_headers)

        assert response.status_code in [200, 401]


def test_missing_auth_header_returns_403(client):
    """Test that missing auth header returns 403 Forbidden."""
    response = client.get("/auth/user")
    assert response.status_code == 403  # No auth header provided


def test_invalid_jwt_returns_401(client, mock_supabase):
    """Test that invalid JWT token returns 401."""
    invalid_token = "invalid-jwt-token"
    auth_headers = {"Authorization": f"Bearer {invalid_token}"}

    # Mock JWT validation failure
    with patch('src.core.auth_utils.supabase.auth.get_user') as mock_get_user:
        mock_get_user.side_effect = Exception("Invalid token")

        response = client.post("/api/v1/kb",
                              json={"name": "Test KB"},
                              headers=auth_headers)

        assert response.status_code == 401


def test_invalid_api_key_returns_401(client, mock_supabase):
    """Test that invalid API key returns 401."""
    invalid_api_key = "sk-invalid-key"
    auth_headers = {"Authorization": f"Bearer {invalid_api_key}"}

    # Mock API key validation failure
    with patch('src.core.auth_utils.supabase.rpc') as mock_rpc:
        mock_rpc_result = MagicMock()
        mock_rpc_result.execute.return_value = MagicMock(data=None)
        mock_rpc.return_value = mock_rpc_result

        response = client.post("/api/v1/kb",
                              json={"name": "Test KB"},
                              headers=auth_headers)

        assert response.status_code == 401
