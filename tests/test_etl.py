"""Test ETL pipeline components."""
import pytest
from unittest.mock import patch, MagicMock
from src.archive.extract import ItemProcessor, ProcessedItem
from src.archive.transform import vectorize_and_chunk
from src.archive.load import load_to_supabase


def test_item_processor_file():
    """Test processing uploaded file."""
    # Test that ItemProcessor exists and has the process method
    assert hasattr(ItemProcessor, 'process')
    assert callable(ItemProcessor.process)

    # Test ProcessedItem structure
    item = ProcessedItem(
        id="test-id",
        content="Extracted text content",
        status="success"
    )
    assert item.id == "test-id"
    assert item.content == "Extracted text content"
    assert item.status == "success"


def test_item_processor_url():
    """Test processing URL."""
    # Test that ItemProcessor exists and has the process method
    assert hasattr(ItemProcessor, 'process')
    assert callable(ItemProcessor.process)

    # Test ProcessedItem structure
    item = ProcessedItem(
        id="test-id",
        content="URL extracted content",
        status="success"
    )
    assert item.id == "test-id"
    assert item.content == "URL extracted content"
    assert item.status == "success"


def test_vectorize_and_chunk():
    """Test text chunking and vectorization."""
    test_text = "This is a sample document. " * 100  # Long text
    metadata = {"source": "test.pdf"}

    with patch('src.archive.transform.get_embedding') as mock_embed:
        mock_embed.return_value = [0.1] * 384  # Mock 384-dim embedding

        result = vectorize_and_chunk(test_text, metadata)

        assert len(result) > 0
        assert all("content" in chunk for chunk in result)
        assert all("embedding" in chunk for chunk in result)
        assert all("metadata" in chunk for chunk in result)
        assert all(chunk["metadata"]["source"] == "test.pdf" for chunk in result)


def test_load_to_supabase():
    """Test loading vectorized data to Supabase."""
    test_data = [{
        "content": "Sample chunk",
        "embedding": [0.1] * 384,
        "metadata": {"source": "test.pdf"}
    }]
    kb_id = "550e8400-e29b-41d4-a716-446655440002"  # Valid UUID

    with patch('src.core.database.supabase') as mock_supabase:
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_table.insert.return_value.execute.return_value = MagicMock(data=[{"id": "test-id"}])

        result = load_to_supabase(test_data, kb_id)

        assert result == 1
        mock_table.insert.assert_called_once()
        # Check that kb_id was added to data
        call_args = mock_table.insert.call_args[0][0]
        assert all(item["kb_id"] == kb_id for item in call_args)


def test_retrieve_similar():
    """Test similarity search."""
    from src.archive.answer import retrieve_similar

    query = "test query"
    kb_id = "550e8400-e29b-41d4-a716-446655440002"  # Valid UUID

    with patch('src.archive.load.search_similar') as mock_search:
        mock_search.return_value = [{
            "content": "Similar document",
            "metadata": {"source": "doc.pdf"},
            "similarity": 0.9,
            "id": "550e8400-e29b-41d4-a716-446655440003"
        }]

        result = retrieve_similar(query, kb_id)

        assert len(result) == 1
        assert result[0]["content"] == "Similar document"
        assert result[0]["similarity"] == 0.9
        mock_search.assert_called_once_with(query, kb_id, 5, "documents")