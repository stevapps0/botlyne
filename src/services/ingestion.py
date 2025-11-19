import logging
from typing import List, Dict, Any, Optional
from sentence_transformers import SentenceTransformer
from src.core.database import supabase

logger = logging.getLogger(__name__)

class IngestionService:
    def __init__(self):
        # Initialize sentence transformer model
        # Using all-MiniLM-L6-v2 as per original implementation
        try:
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
        except Exception as e:
            logger.error(f"Failed to load SentenceTransformer model: {e}")
            self.model = None

        # Configuration
        self.CHUNK_SIZE = 1500
        self.CHUNK_OVERLAP = 200

    def chunk_text(self, text: str) -> List[str]:
        """Split text into overlapping chunks."""
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.CHUNK_SIZE
            chunks.append(text[start:end])
            start = end - self.CHUNK_OVERLAP
        return chunks

    def get_embedding(self, text: str) -> Optional[List[float]]:
        """Get embedding using sentence-transformers."""
        if not self.model:
            logger.error("Model not initialized")
            return None
            
        try:
            embedding = self.model.encode(text)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Error getting embedding: {e}")
            return None

    def vectorize_and_chunk(self, text: str, metadata: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Transform text into chunks with embeddings."""
        logger.info(f"Processing text of length: {len(text)}")

        # Chunk the text
        chunks = self.chunk_text(text)
        logger.info(f"Created {len(chunks)} chunks")

        vectorized_data = []
        for i, chunk in enumerate(chunks):
            # Get embedding
            embedding = self.get_embedding(chunk)
            if embedding is None:
                continue

            # Create data structure
            chunk_metadata = metadata.copy() if metadata else {}
            chunk_metadata["chunk_index"] = i
            chunk_metadata["chunk_size"] = len(chunk)

            data = {
                "content": chunk,
                "embedding": embedding,
                "metadata": chunk_metadata
            }

            vectorized_data.append(data)

        logger.info(f"Successfully vectorized {len(vectorized_data)}/{len(chunks)} chunks")
        return vectorized_data

    def load_to_supabase(self, vectorized_data: List[Dict[str, Any]], kb_id: str, file_id: Optional[str] = None, table_name: str = "documents") -> int:
        """Load vectorized data into Supabase."""
        if not vectorized_data:
            logger.warning("No data to load")
            return 0

        # Add kb_id and file_id to each document
        for data in vectorized_data:
            data["kb_id"] = kb_id
            if file_id:
                data["file_id"] = file_id

        try:
            result = supabase.table(table_name).insert(vectorized_data).execute()
            logger.info(f"Successfully loaded {len(vectorized_data)} documents to Supabase")
            return len(vectorized_data)
        except Exception as e:
            logger.error(f"Error loading data to Supabase: {e}")
            return 0

# Singleton instance
ingestion_service = IngestionService()
