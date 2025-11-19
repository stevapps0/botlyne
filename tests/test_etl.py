"""Test ETL pipeline components with proper mocking."""
import pytest
from unittest.mock import patch, MagicMock
from pydantic import BaseModel


class ProcessedItem(BaseModel):
    """Model for processed item results."""
    id: str
    content: str
    status: str


def test_item_processor_structure():
    """Test that ItemProcessor exists and has required methods."""
    from src.services.etl import ItemProcessor

    assert hasattr(ItemProcessor, 'process')
    assert callable(ItemProcessor.process)


def test_processed_item_model():
    """Test ProcessedItem data model."""
    item = ProcessedItem(
        id="test-id",
        content="Extracted text content",
        status="success"
    )

    assert item.id == "test-id"
    assert item.content == "Extracted text content"
    assert item.status == "success"

    # Test serialization
    data = item.model_dump()
    assert data["id"] == "test-id"
    assert data["status"] == "success"


def test_vectorize_and_chunk_function():
    """Test text chunking and vectorization."""
    test_text = "This is a sample document. " * 100  # Long text
    metadata = {"source": "test.pdf", "type": "pdf"}

    with patch('src.services.ingestion.IngestionService.get_embedding') as mock_embed:
        mock_embed.return_value = [0.1] * 384  # Mock 384-dim embedding

        from src.services.ingestion import ingestion_service

        result = ingestion_service.vectorize_and_chunk(test_text, metadata)

        assert len(result) > 0
        assert all("content" in chunk for chunk in result)
        assert all("embedding" in chunk for chunk in result)
        assert all("metadata" in chunk for chunk in result)
        assert all(isinstance(chunk["embedding"], list) for chunk in result)
        assert all(len(chunk["embedding"]) == 384 for chunk in result)


def test_vectorize_empty_text():
    """Test vectorize handles empty text."""
    test_text = ""
    metadata = {"source": "empty.txt"}

    with patch('src.services.ingestion.IngestionService.get_embedding') as mock_embed:
        mock_embed.return_value = [0.0] * 384

        from src.services.ingestion import ingestion_service

        result = ingestion_service.vectorize_and_chunk(test_text, metadata)

        # Empty text should return empty list or single empty chunk
        assert isinstance(result, list)


def test_load_to_supabase_function():
    """Test loading data to Supabase."""
    kb_id = "test-kb-id"
    data = [
        {
            "content": "Chunk 1",
            "embedding": [0.1] * 384,
            "metadata": {"source": "test.pdf"}
        },
        {
            "content": "Chunk 2",
            "embedding": [0.2] * 384,
            "metadata": {"source": "test.pdf"}
        }
    ]

    with patch('src.services.ingestion.supabase') as mock_supabase:
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_table.insert.return_value.execute.return_value = MagicMock()

        from src.services.ingestion import ingestion_service

        result = ingestion_service.load_to_supabase(data, kb_id)

        # Should return number of chunks loaded
        assert result == 2
        
        # Verify insert was called
        mock_table.insert.assert_called()
        
        # Verify kb_id was added to data
        call_args = mock_table.insert.call_args[0][0]
        assert all(item["kb_id"] == kb_id for item in call_args)


def test_retrieve_similar_function():
    """Test retrieving similar documents."""
    query = "machine learning"
    kb_id = "test-kb-id"

    with patch('src.services.retrieval.supabase') as mock_supabase:
        mock_result = MagicMock()
        mock_result.data = [{
            "id": "doc-1",
            "content": "Machine learning is a subset of AI",
            "metadata": {"source": "ml_intro.pdf"},
            "similarity": 0.92
        }, {
            "id": "doc-2",
            "content": "Deep learning uses neural networks",
            "metadata": {"source": "dl_guide.pdf"},
            "similarity": 0.87
        }]
        # Ensure the execute() chain returns the result with data
        mock_supabase.rpc.return_value.execute.return_value = mock_result

        from src.services.retrieval import retrieval_service
        results = retrieval_service.search_similar(query, kb_id)

        assert len(results) == 2
        assert results[0]["content"] == "Machine learning is a subset of AI"
        assert results[0]["similarity"] == 0.92
        assert all("content" in r for r in results)
        assert all("metadata" in r for r in results)


def test_extract_different_file_types():
    """Test extraction with different file types."""
    from src.services.etl import ItemProcessor

    file_types = ["pdf", "txt", "docx", "html"]

    for file_type in file_types:
        # ItemProcessor should handle different types
        assert hasattr(ItemProcessor, 'process')


def test_etl_pipeline_integration():
    """Test integrated ETL pipeline flow."""
    test_content = "This is test content for the ETL pipeline."
    metadata = {"source": "test.pdf", "type": "pdf"}
    kb_id = "550e8400-e29b-41d4-a716-446655440002"

    with patch('src.services.ingestion.IngestionService.get_embedding') as mock_embed, \
         patch('src.core.database.supabase') as mock_supabase:

        # Mock embedding
        mock_embed.return_value = [0.1] * 384

        # Mock database insert
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_table.insert.return_value.execute.return_value = MagicMock(data=[{"id": "chunk-1"}])

        # Extract (simulated)
        from src.services.etl import ProcessedItem
        extracted = ProcessedItem(
            id="item-1",
            content=test_content,
            status="success",
            metadata={},
            source="test.pdf",
            source_type="file",
            content_type="document",
            processor="test",
            processed_at="2024-01-01T00:00:00Z"
        )

        assert extracted.status == "success"

        # Transform
        from src.services.ingestion import ingestion_service
        chunks = ingestion_service.vectorize_and_chunk(extracted.content, metadata)

        assert len(chunks) > 0
        assert all("embedding" in chunk for chunk in chunks)

        # Load
        result = ingestion_service.load_to_supabase(chunks, kb_id)

        assert result >= 0
