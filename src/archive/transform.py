from typing import List
from sentence_transformers import SentenceTransformer

# Initialize sentence transformer model
model = SentenceTransformer('all-MiniLM-L6-v2')

# Configuration
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks

def get_embedding(text: str) -> List[float]:
    """Get embedding using sentence-transformers."""
    try:
        embedding = model.encode(text)
        return embedding.tolist()
    except Exception as e:
        print(f"Error getting embedding: {e}")
        return None

def vectorize_and_chunk(text: str, metadata: dict = None) -> List[dict]:
    """Transform text into chunks with embeddings."""
    print(f"Processing text of length: {len(text)}")

    # Chunk the text
    chunks = chunk_text(text)
    print(f"Created {len(chunks)} chunks")

    vectorized_data = []
    for i, chunk in enumerate(chunks):
        print(f"Processing chunk {i+1}/{len(chunks)}...", end=" ")

        # Get embedding
        embedding = get_embedding(chunk)
        if embedding is None:
            print("Failed")
            continue

        # Create data structure
        chunk_metadata = metadata or {}
        chunk_metadata["chunk_index"] = i

        data = {
            "content": chunk,
            "embedding": embedding,
            "metadata": chunk_metadata
        }

        vectorized_data.append(data)
        print("Done")

    print(f"\nSuccessfully vectorized {len(vectorized_data)}/{len(chunks)} chunks")
    return vectorized_data