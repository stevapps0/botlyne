"""Test upload endpoints."""
import pytest
from unittest.mock import MagicMock, patch
from io import BytesIO


def test_upload_files_and_urls(client, mock_supabase, sample_kb, auth_headers):
    """Test file and URL upload."""
    # Mock KB verification
    mock_kb_result = MagicMock()
    mock_kb_result.data = sample_kb
    mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_kb_result

    # Mock file processing
    with patch('src.archive.extract.ItemProcessor.process') as mock_process, \
         patch('src.archive.transform.vectorize_and_chunk') as mock_vectorize, \
         patch('src.archive.load.load_to_supabase') as mock_load:

        # Mock processing results
        mock_processed = MagicMock()
        mock_processed.status = "success"
        mock_processed.content = "Sample content"
        mock_process.return_value = mock_processed

        mock_vectorize.return_value = [{"content": "chunk", "embedding": [0.1] * 384, "metadata": {}}]
        mock_load.return_value = 1

        # Mock file record creation
        mock_file_result = MagicMock()
        mock_file_result.data = None
        mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_file_result

        # Create test file
        test_file = BytesIO(b"test file content")
        test_file.name = "test.pdf"

        response = client.post(f"/api/v1/kbs/{sample_kb['id']}/upload",
                              files={"files": ("test.pdf", test_file, "application/pdf")},
                              data={"urls": ["https://example.com"]},
                              headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "batch_id" in data
        assert data["files_processed"] == 1
        assert data["urls_processed"] == 1


def test_get_upload_status(client, mock_supabase, auth_headers):
    """Test getting upload batch status."""
    batch_id = "test-batch-id"
    status_data = {
        "batch_id": batch_id,
        "status": "completed",
        "progress": 100,
        "total_items": 2,
        "completed_at": "2024-01-01T00:00:00Z"
    }

    # Mock status retrieval (using in-memory dict)
    with patch('src.api.v1.upload.processing_status', {batch_id: status_data}):
        response = client.get(f"/api/v1/upload/status/{batch_id}", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["batch_id"] == batch_id
        assert data["status"] == "completed"


def test_list_kb_files(client, mock_supabase, sample_kb, auth_headers):
    """Test listing files in knowledge base."""
    # Mock KB verification
    mock_kb_result = MagicMock()
    mock_kb_result.data = sample_kb
    mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_kb_result

    # Mock files query
    mock_files_result = MagicMock()
    mock_files_result.data = [{
        "id": "file-id",
        "kb_id": sample_kb["id"],
        "filename": "test.pdf",
        "file_type": "pdf",
        "size_bytes": 1024,
        "uploaded_by": "user-id",
        "uploaded_at": "2024-01-01T00:00:00Z"
    }]
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_files_result

    response = client.get(f"/api/v1/kbs/{sample_kb['id']}/files", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert "files" in data
    assert len(data["files"]) == 1
    assert data["files"][0]["filename"] == "test.pdf"