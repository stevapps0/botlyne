import os
from typing import List
from src.core.database import supabase

def load_to_supabase(vectorized_data: List[dict], kb_id: str, table_name: str = "documents") -> int:
    """Load vectorized data into Supabase."""
    if not vectorized_data:
        print("No data to load")
        return 0

    # Add kb_id to each document
    for data in vectorized_data:
        data["kb_id"] = kb_id

    try:
        result = supabase.table(table_name).insert(vectorized_data).execute()
        print(f"Successfully loaded {len(vectorized_data)} documents to Supabase")
        return len(vectorized_data)
    except Exception as e:
        print(f"Error loading data to Supabase: {e}")
        return 0

def search_similar(query: str, kb_id: str, limit: int = 5, table_name: str = "documents") -> List[dict]:
    """Search for similar documents using vector similarity."""
    from .transform import get_embedding

    query_embedding = get_embedding(query)
    if query_embedding is None:
        return []

    try:
        result = supabase.rpc(
            "match_documents",
            {
                "query_embedding": query_embedding,
                "kb_id": kb_id,
                "match_count": limit
            }
        ).execute()
        return result.data
    except Exception as e:
        print(f"Error searching: {e}")
        return []

if __name__ == "__main__":
    from .transform import vectorize_and_chunk

    # Example usage
    sample_text = """
    Your long text here. This will be chunked and vectorized.
    Add your actual data or read from a file.
    """

    metadata = {
        "source": "example",
        "date": "2025-10-30"
    }

    # Transform
    vectorized_data = vectorize_and_chunk(sample_text, metadata)

    # Load to Supabase (requires kb_id)
    # load_to_supabase(vectorized_data, "your_kb_id")

    # Search example
    # results = search_similar("your search query", "your_kb_id")
    # for result in results:
    #     print(result)