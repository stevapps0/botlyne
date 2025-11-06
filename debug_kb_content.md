# Knowledge Base Content Debug Analysis

## Issue: Query not using uploaded content

The user reports that queries are not using the uploaded content. The response shows:
- `sources: []` (empty sources)
- AI response indicates no knowledge base access
- Response time: 4.26 seconds (indicates processing but no KB retrieval)

## Potential Issues to Debug:

1. **KB Association**: Verify API key is properly associated with KB
2. **Document Retrieval**: Check if `retrieve_similar` function is working
3. **KB Content**: Verify documents exist in the knowledge base
4. **Vector Search**: Check if embeddings are properly stored and searchable
5. **Table Name**: Verify correct table name is being used

## Debug Steps:

1. Check API key KB association
2. Query documents table directly
3. Test `retrieve_similar` function
4. Check vector embeddings
5. Verify KB ID consistency

## Current Query Flow:

1. API key verified → gets `kb_id`
2. `retrieve_similar(data.query, kb_id=kb_id, limit=5, table_name="documents")`
3. Format context from similar docs
4. Generate AI response

## Likely Issues:

- Documents not properly stored in `documents` table
- `retrieve_similar` function not finding matches
- Wrong table name or KB ID
- Vector embeddings not generated/stored

## Debug Queries to Run:

```sql
-- Check documents in KB
SELECT COUNT(*) FROM documents WHERE kb_id = 'd0bf60b4-a3a5-42f8-82bb-66e9b6927a93';

-- Check if embeddings exist
SELECT id, content, embedding FROM documents WHERE kb_id = 'd0bf60b4-a3a5-42f8-82bb-66e9b6927a93' LIMIT 1;

-- Test similarity search
SELECT * FROM match_documents(
  (SELECT embedding FROM documents WHERE kb_id = 'd0bf60b4-a3a5-42f8-82bb-66e9b6927a93' LIMIT 1),
  'd0bf60b4-a3a5-42f8-82bb-66e9b6927a93',
  5
);