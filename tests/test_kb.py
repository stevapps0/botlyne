"""Test knowledge base endpoints."""
import pytest
from unittest.mock import MagicMock


def test_create_knowledge_base(client, mock_supabase, sample_org, auth_headers):
    """Test knowledge base creation."""
    # Mock org verification
    mock_org_result = MagicMock()
    mock_org_result.data = sample_org
    mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_org_result

    # Mock KB creation
    mock_kb_result = MagicMock()
    mock_kb_result.data = [{
        "id": "550e8400-e29b-41d4-a716-446655440002",
        "org_id": sample_org["id"],
        "name": "Test KB",
        "created_at": "2024-01-01T00:00:00Z"
    }]
    mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_kb_result

    response = client.post(f"/api/v1/orgs/{sample_org['id']}/kbs",
                          json={"name": "Test KB"},
                          headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test KB"
    assert data["org_id"] == sample_org["id"]


def test_list_knowledge_bases(client, mock_supabase, sample_org, sample_kb, auth_headers):
    """Test listing knowledge bases."""
    # Mock org verification
    mock_org_result = MagicMock()
    mock_org_result.data = sample_org
    mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_org_result

    # Mock KB list
    mock_kb_result = MagicMock()
    mock_kb_result.data = [sample_kb]
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_kb_result

    response = client.get(f"/api/v1/orgs/{sample_org['id']}/kbs", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == sample_kb["name"]


def test_get_knowledge_base(client, mock_supabase, sample_kb, auth_headers):
    """Test getting specific knowledge base."""
    # Mock KB query
    mock_result = MagicMock()
    mock_result.data = sample_kb
    mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_result

    response = client.get(f"/api/v1/kbs/{sample_kb['id']}", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == sample_kb["id"]
    assert data["name"] == sample_kb["name"]


def test_delete_knowledge_base(client, mock_supabase, sample_kb, auth_headers):
    """Test knowledge base deletion."""
    # Mock KB query
    mock_result = MagicMock()
    mock_result.data = sample_kb
    mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_result

    # Mock delete
    mock_delete_result = MagicMock()
    mock_delete_result.data = None
    mock_supabase.table.return_value.delete.return_value.eq.return_value.execute.return_value = mock_delete_result

    response = client.delete(f"/api/v1/kbs/{sample_kb['id']}", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert "message" in data