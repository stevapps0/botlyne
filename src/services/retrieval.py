import logging
from typing import List, Dict, Any
from src.core.database import supabase
from src.services.ingestion import ingestion_service

logger = logging.getLogger(__name__)

class RetrievalService:
    def search_similar(self, query: str, kb_id: str, limit: int = 5, table_name: str = "documents") -> List[Dict[str, Any]]:
        """
        Search for similar documents using vector similarity.
        
        Args:
            query: The search query string
            kb_id: Knowledge base ID to search within
            limit: Maximum number of results to return
            table_name: Database table name
            
        Returns:
            List of similar documents with content, metadata, and similarity scores
        """
        logger.info(f"Searching for query: '{query}' in KB: {kb_id}")

        # Generate embedding for the query using the ingestion service's model
        query_embedding = ingestion_service.get_embedding(query)
        
        if query_embedding is None:
            logger.error("Failed to get query embedding")
            return []

        try:
            # Call the Supabase RPC function for vector similarity search
            result = supabase.rpc(
                "match_documents",
                {
                    "query_embedding": query_embedding,
                    "kb_id": kb_id,
                    "match_count": limit
                }
            ).execute()
            
            logger.info(f"Found {len(result.data) if result.data else 0} results")
            
            # Format results
            formatted_results = []
            if result.data:
                for doc in result.data:
                    formatted_results.append({
                        "content": doc.get("content", ""),
                        "metadata": doc.get("metadata", {}),
                        "similarity": doc.get("similarity", 0.0),
                        "id": doc.get("id"),
                        "kb_id": kb_id
                    })
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"Error searching knowledge base: {e}")
            return []

# Singleton instance
retrieval_service = RetrievalService()
