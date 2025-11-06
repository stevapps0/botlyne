# Knowledge Base AI API

A multi-tenant API that enables organizations to create knowledge bases from uploaded files and URLs, and query them using AI-powered retrieval-augmented generation (RAG).

## Features

### Phase 1 (MVP) ✅
- **Multi-Tenant Architecture**: Organizations can create accounts and manage users
- **Authentication**: Supabase auth with email/password and OAuth (Google/GitHub)
- **API Key Management**: Secure API keys with knowledge base associations
- **Knowledge Base Management**: Create and manage knowledge bases per organization
- **ETL Pipeline**: Upload files (PDF, DOCX, etc.) and URLs, automatic extraction and vectorization
- **AI Querying**: Natural language queries with context-aware RAG using Google Gemini AI
- **Vector Similarity Search**: PostgreSQL pgvector for efficient document retrieval
- **Human Handoff**: Automatic escalation to support via email when AI can't resolve
- **Conversation History**: Track user interactions and AI responses
- **Performance Metrics**: Basic tracking of response times and handoff events

## Tech Stack

- **Backend**: FastAPI (Python)
- **Database**: Supabase PostgreSQL with vector extensions
- **Storage**: Supabase Storage for files
- **AI**: Pydantic AI with Google Gemini (context-aware RAG)
- **Processing**: Docling for document extraction, OpenLyne for web scraping
- **Embeddings**: Sentence Transformers (all-MiniLM-L6-v2)

## Quick Start

### Prerequisites
- Python 3.9+
- Supabase account
- Google AI API key
- OpenLyne API key (optional, for web scraping)

### Installation

1. **Clone and setup**:
   ```bash
   git clone <repository>
   cd knowledge-base-api
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies**:
   ```bash
   pip install fastapi uvicorn supabase sentence-transformers docling httpx pydantic-ai
   ```

3. **Environment setup**:
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

4. **Database setup**:
   - Create a Supabase project
   - Run the SQL in `schema.sql` in your Supabase SQL editor
   - Enable storage bucket for file uploads

5. **Run the API**:
   ```bash
   python main.py
   ```

The API will be available at `http://localhost:8000` with docs at `http://localhost:8000/docs`.

## API Endpoints

### Authentication (mounted at `/auth`)
- `POST /auth/signup` - User registration with email/password
- `POST /auth/signin` - User login with email/password
- `POST /auth/oauth/signin` - OAuth signin (Google/GitHub)
- `POST /auth/oauth/callback` - OAuth callback handler
- `POST /auth/refresh` - Refresh access token
- `POST /auth/signout` - Sign out user
- `GET /auth/user` - Get current user info
- `GET /me` - Get current user profile with org/role

### Organization Management (mounted at `/auth`)
- `POST /orgs` - Create new organization
- `GET /orgs/{org_id}` - Get organization details
- `GET /orgs/{org_id}/users` - List all users in organization
- `POST /orgs/{org_id}/users` - Add user to organization
- `DELETE /orgs/{org_id}/users/{user_id}` - Remove user from organization

### Knowledge Bases (at `/api/v1`)
- `POST /api/v1/orgs/{org_id}/kbs` - Create knowledge base
- `GET /api/v1/orgs/{org_id}/kbs` - List knowledge bases
- `GET /api/v1/kbs/{kb_id}` - Get knowledge base details
- `PUT /api/v1/kbs/{kb_id}` - Update knowledge base name
- `DELETE /api/v1/kbs/{kb_id}` - Delete knowledge base (admin only)

### Upload & Processing (at `/api/v1`)
- `POST /api/v1/upload` - Upload files and URLs for processing (uses API key KB association)
- `GET /api/v1/upload/status` - Check upload processing status
- `GET /api/v1/files` - List all files in knowledge base

### Querying & Conversations (at `/api/v1`)
- `POST /api/v1/query` - Query knowledge base with AI agent
- `GET /api/v1/conversations` - List user's conversation history
- `POST /api/v1/conversations/{conv_id}/resolve` - Mark conversation as resolved

### Analytics & Metrics (at `/api/v1`)
- `GET /api/v1/orgs/{org_id}/metrics` - Get organization analytics (admin only)

## API Usage Examples

### Authentication

#### Sign Up
```bash
curl -X POST "http://localhost:8000/auth/signup" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@company.com",
    "password": "securepassword123"
  }'
```

#### Sign In
```bash
curl -X POST "http://localhost:8000/auth/signin" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@company.com",
    "password": "securepassword123"
  }'
```

#### OAuth Sign In (Google)
```bash
curl -X POST "http://localhost:8000/auth/oauth/signin" \
  -H "Content-Type: application/json" \
  -d '{"provider": "google"}'
```

#### Get Current User
```bash
curl -X GET "http://localhost:8000/me" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Organization Management

#### Create Organization
```bash
curl -X POST "http://localhost:8000/orgs" \
  -H "Content-Type: application/json" \
  -d '{"name": "My Company"}'
```

#### Get Organization Details
```bash
curl -X GET "http://localhost:8000/orgs/123e4567-e89b-12d3-a456-426614174000" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### Add User to Organization
```bash
curl -X POST "http://localhost:8000/orgs/123e4567-e89b-12d3-a456-426614174000/users" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "newuser@company.com",
    "role": "member"
  }'
```

#### List Organization Users
```bash
curl -X GET "http://localhost:8000/orgs/123e4567-e89b-12d3-a456-426614174000/users" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Knowledge Base Management

#### Create Knowledge Base
```bash
curl -X POST "http://localhost:8000/api/v1/orgs/123e4567-e89b-12d3-a456-426614174000/kbs" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Product Documentation"}'
```

#### List Knowledge Bases
```bash
curl -X GET "http://localhost:8000/api/v1/orgs/123e4567-e89b-12d3-a456-426614174000/kbs" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### Get Knowledge Base Details
```bash
curl -X GET "http://localhost:8000/api/v1/kbs/456e7890-e89b-12d3-a456-426614174001" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### Update Knowledge Base
```bash
curl -X PUT "http://localhost:8000/api/v1/kbs/456e7890-e89b-12d3-a456-426614174001" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Updated Documentation"}'
```

#### Delete Knowledge Base
```bash
curl -X DELETE "http://localhost:8000/api/v1/kbs/456e7890-e89b-12d3-a456-426614174001" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Upload & Processing

#### Upload Files
```bash
curl -X POST "http://localhost:8000/api/v1/upload" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "files=@document.pdf" \
  -F "files=@manual.docx"
```

#### Upload URLs
```bash
curl -X POST "http://localhost:8000/api/v1/upload" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "urls": [
      "https://docs.example.com/getting-started",
      "https://docs.example.com/api-reference"
    ]
  }'
```

#### Check Upload Status
```bash
curl -X GET "http://localhost:8000/api/v1/upload/status" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

#### List Knowledge Base Files
```bash
curl -X GET "http://localhost:8000/api/v1/files" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Querying & Conversations

#### Query Knowledge Base
```bash
curl -X POST "http://localhost:8000/api/v1/query" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How do I reset my password?",
    "kb_id": "456e7890-e89b-12d3-a456-426614174001",  // optional - uses API key association if omitted
    "conversation_id": "conv_123"  // optional, for continuing conversations
  }'
```

**Note**: `kb_id` is now optional. If not provided, the API will automatically use the knowledge base associated with your API key.

#### List Conversations
```bash
curl -X GET "http://localhost:8000/api/v1/conversations" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### Resolve Conversation
```bash
curl -X POST "http://localhost:8000/api/v1/conversations/conv_123/resolve" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "satisfaction_score": 5
  }'
```

### Analytics & Metrics

#### Get Organization Metrics (Admin Only)
```bash
curl -X GET "http://localhost:8000/api/v1/orgs/123e4567-e89b-12d3-a456-426614174000/metrics" \
  -H "Authorization: Bearer YOUR_ADMIN_ACCESS_TOKEN"
```

### Health Check
```bash
curl -X GET "http://localhost:8000/health"
```

### API Documentation
```bash
curl -X GET "http://localhost:8000/docs"  # Interactive Swagger UI
curl -X GET "http://localhost:8000/openapi.json"  # OpenAPI spec
```

## Project Structure

```
├── main.py                 # FastAPI app entry point
├── src/
│   ├── api/               # API route handlers
│   │   ├── auth.py        # Authentication endpoints
│   │   ├── kb.py          # Knowledge base endpoints
│   │   ├── upload.py      # Upload/processing endpoints
│   │   └── query.py       # Query endpoints
│   ├── core/              # Core functionality
│   │   ├── config.py      # Settings and configuration
│   │   └── database.py    # Database connection
│   ├── models/            # Pydantic models
│   └── services/          # Business logic (ETL, AI, etc.)
├── archive/               # Original sample code
├── schema.sql             # Database schema
├── PRD.md                 # Product requirements
├── .env.example           # Environment variables template
└── README.md              # This file
```

## Development

### Running Tests
```bash
# Install test dependencies
pip install pytest httpx

# Run tests
pytest
```

### Code Quality
```bash
# Install dev dependencies
pip install black isort flake8 mypy

# Format code
black src/
isort src/

# Lint
flake8 src/
mypy src/
```

## Deployment

### Docker
```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Railway/Vercel
- Set environment variables in your deployment platform
- Deploy `main.py` as the entry point
- Ensure Supabase allows external connections

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Roadmap

### Phase 2
- Advanced metrics dashboard
- WhatsApp integration for handoff
- Conversation memory and context
- Multi-language support

### Phase 3
- Advanced RAG techniques
- Custom model fine-tuning
- Real-time collaboration
- API rate limiting and caching