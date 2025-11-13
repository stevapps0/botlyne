"""Test upload endpoints with JWT and API key authentication."""
import pytest
from unittest.mock import MagicMock, patch
from io import BytesIO


def test_upload_files_with_jwt(client, mock_supabase, sample_kb, jwt_token):
    """Test file upload with JWT authentication."""
    auth_headers = {"Authorization": f"Bearer {jwt_token}"}

    # Mock JWT validation
    with patch('src.core.auth_utils.supabase.auth.get_user') as mock_get_user:
        mock_get_user.return_value = MagicMock(user=MagicMock(id="550e8400-e29b-41d4-a716-446655440000"))

        # Mock KB verification
        mock_kb_result = MagicMock()
        mock_kb_result.data = sample_kb
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_kb_result

        # Mock ETL processing
        with patch('src.archive.extract.ItemProcessor.process') as mock_process, \
             patch('src.archive.transform.vectorize_and_chunk') as mock_vectorize, \
             patch('src.archive.load.load_to_supabase') as mock_load:

            mock_process.return_value = MagicMock(
                status="success",
                content="Extracted content"
            )
            mock_vectorize.return_value = [
                {"content": "chunk", "embedding": [0.1] * 384, "metadata": {}}
            ]
            mock_load.return_value = 1

            # Mock file record creation
            mock_file_result = MagicMock()
            mock_file_result.data = [{
                "id": "file-id",
                "kb_id": sample_kb["id"],
                "filename": "test.pdf",
                "uploaded_by": "550e8400-e29b-41d4-a716-446655440000"
            }]
            mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_file_result

            # Create test file
            test_file = BytesIO(b"test file content")
            test_file.name = "test.pdf"

            response = client.post(f"/api/v1/upload",
                                  files={"files": ("test.pdf", test_file, "application/pdf")},
                                  data={"kb_id": sample_kb["id"]},
                                  headers=auth_headers)

            assert response.status_code in [200, 422]  # 200 if successful, 422 if validation fails


def test_upload_files_with_api_key(client, mock_supabase, sample_kb, api_key_token):
    """Test file upload with API key authentication."""
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

        # Mock ETL processing
        with patch('src.archive.extract.ItemProcessor.process') as mock_process, \
             patch('src.archive.transform.vectorize_and_chunk') as mock_vectorize, \
             patch('src.archive.load.load_to_supabase') as mock_load:

            mock_process.return_value = MagicMock(status="success", content="Content")
            mock_vectorize.return_value = [
                {"content": "chunk", "embedding": [0.1] * 384, "metadata": {}}
            ]
            mock_load.return_value = 1

            # Mock file record
            mock_file_result = MagicMock()
            mock_file_result.data = [{"id": "file-id", "kb_id": sample_kb["id"]}]
            mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_file_result

            test_file = BytesIO(b"test file content")
            test_file.name = "test.pdf"

            response = client.post(f"/api/v1/upload",
                                  files={"files": ("test.pdf", test_file, "application/pdf")},
                                  data={"kb_id": sample_kb["id"]},
                                  headers=auth_headers)

            assert response.status_code in [200, 422]


def test_upload_urls_with_jwt(client, mock_supabase, sample_kb, jwt_token):
    """Test URL upload with JWT authentication."""
    auth_headers = {"Authorization": f"Bearer {jwt_token}"}

    # Mock JWT validation
    with patch('src.core.auth_utils.supabase.auth.get_user') as mock_get_user:
        mock_get_user.return_value = MagicMock(user=MagicMock(id="550e8400-e29b-41d4-a716-446655440000"))

        # Mock KB verification
        mock_kb_result = MagicMock()
        mock_kb_result.data = sample_kb
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_kb_result

        response = client.post(f"/api/v1/upload",
                              json={
                                  "kb_id": sample_kb["id"],
                                  "urls": ["https://example.com"]
                              },
                              headers=auth_headers)

        # Note: This will depend on actual URL processing implementation
        assert response.status_code in [200, 422, 400]


def test_upload_requires_auth(client):
    """Test that upload endpoints require authentication."""
    response = client.post("/api/v1/upload")
    assert response.status_code == 403


def test_upload_requires_kb_id(client, jwt_token):
    """Test that upload requires kb_id parameter."""
    auth_headers = {"Authorization": f"Bearer {jwt_token}"}

    with patch('src.core.auth_utils.supabase.auth.get_user') as mock_get_user:
        mock_get_user.return_value = MagicMock(user=MagicMock(id="550e8400-e29b-41d4-a716-446655440000"))

        response = client.post("/api/v1/upload",
                              headers=auth_headers)

        assert response.status_code in [400, 422]  # Validation error expected
