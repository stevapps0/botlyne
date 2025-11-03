from typing import List, Dict, Any
from .load import search_similar

def retrieve_similar(query: str, kb_id: str = None, limit: int = 5, table_name: str = "documents") -> List[Dict[str, Any]]:
    """
    Retrieve similar documents using vector similarity search.

    Args:
        query: The search query string
        kb_id: Knowledge base ID to search within (optional)
        limit: Maximum number of results to return
        table_name: Database table name

    Returns:
        List of similar documents with content, metadata, and similarity scores
    """
    try:
        # Use the search_similar function from load.py
        results = search_similar(query, kb_id, limit, table_name)

        # Format results to match expected structure
        formatted_results = []
        for result in results:
            formatted_results.append({
                "content": result.get("content", ""),
                "metadata": result.get("metadata", {}),
                "similarity": result.get("similarity", 0.0),
                "id": result.get("id"),
                "kb_id": kb_id
            })

        return formatted_results

    except Exception as e:
        print(f"Error retrieving similar documents: {e}")
        return []