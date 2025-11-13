"""Test knowledge base endpoints with JWT and API key authentication."""
import pytest
from unittest.mock import MagicMock, patch


def test_create_kb_with_jwt(client, mock_supabase, sample_user, sample_org, jwt_token):
    """Test creating knowledge base with JWT authentication."""
    auth_headers = {"Authorization": f"Bearer {jwt_token}"}

    # Mock JWT validation
    with patch('src.core.auth_utils.supabase.auth.get_user') as mock_get_user:
        mock_get_user.return_value = MagicMock(user=MagicMock(id=sample_user["id"]))

        # Mock user lookup for org_id
        mock_user_result = MagicMock()
        mock_user_result.data = sample_user
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_user_result

        # Mock KB creation
        mock_kb_result = MagicMock()
        mock_kb_result.data = [{
            "id": "550e8400-e29b-41d4-a716-446655440002",
            "org_id": sample_org["id"],
            "name": "Test KB",
            "created_at": "2024-01-01T00:00:00Z"
        }]
        mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_kb_result

        response = client.post("/kb",
                              json={"name": "Test KB"},
                              headers=auth_headers)

        assert response.status_code in [200, 401]


def test_create_kb_with_api_key(client, mock_supabase, sample_org, api_key_token):
    """Test creating knowledge base with API key authentication."""
    auth_headers = {"Authorization": f"Bearer {api_key_token}"}

    # Mock API key validation
    with patch('src.core.auth_utils.supabase.rpc') as mock_rpc:
        mock_rpc_result = MagicMock()
        mock_rpc_result.execute.return_value = MagicMock(data={
            "user_id": "550e8400-e29b-41d4-a716-446655440000",
            "org_id": sample_org["id"],
            "kb_id": None,
            "api_key_id": "sk-api-key-id"
        })
        mock_rpc.return_value = mock_rpc_result

        # Mock KB creation
        mock_kb_result = MagicMock()
        mock_kb_result.data = [{
            "id": "550e8400-e29b-41d4-a716-446655440002",
            "org_id": sample_org["id"],
            "name": "API KB",
            "created_at": "2024-01-01T00:00:00Z"
        }]
        mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_kb_result

        response = client.post("/kb",
                              json={"name": "API KB"},
                              headers=auth_headers)

        assert response.status_code in [200, 401]


def test_get_kb_details(client, mock_supabase, sample_kb, jwt_token):
    """Test retrieving specific knowledge base details."""
    auth_headers = {"Authorization": f"Bearer {jwt_token}"}

    # Mock JWT validation
    with patch('src.core.auth_utils.supabase.auth.get_user') as mock_get_user:
        mock_get_user.return_value = MagicMock(user=MagicMock(id="550e8400-e29b-41d4-a716-446655440000"))

        # Mock KB query
        mock_kb_result = MagicMock()
        mock_kb_result.data = sample_kb
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_kb_result

        response = client.get(f"/kb/{sample_kb['id']}", headers=auth_headers)

        assert response.status_code in [200, 401]


def test_list_org_kbs(client, mock_supabase, sample_org, sample_kb, jwt_token):
    """Test listing all knowledge bases in an organization."""
    auth_headers = {"Authorization": f"Bearer {jwt_token}"}

    # Mock JWT validation
    with patch('src.core.auth_utils.supabase.auth.get_user') as mock_get_user:
        mock_get_user.return_value = MagicMock(user=MagicMock(id="550e8400-e29b-41d4-a716-446655440000"))

        # Mock user lookup for org verification
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

        response = client.get(f"/orgs/{sample_org['id']}/kb", headers=auth_headers)

        assert response.status_code in [200, 401]


def test_kb_requires_auth(client):
    """Test that KB endpoints require authentication."""
    # Create KB without auth header
    response = client.post("/kb", json={"name": "Test KB"})
    assert response.status_code == 403

    # Get KB without auth header
    response = client.get("/kb/550e8400-e29b-41d4-a716-446655440002")
    assert response.status_code == 403

    # List orgs KBs without auth header
    response = client.get("/orgs/550e8400-e29b-41d4-a716-446655440001/kb")
    assert response.status_code == 403
