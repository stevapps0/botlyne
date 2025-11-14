# Knowledge Base AI API

A multi-tenant API that enables users to create accounts, organizations, and knowledge bases from uploaded files and URLs, then query them using AI-powered retrieval-augmented generation (RAG). Supports both **JWT authentication** (logged-in users) and **API keys** (programmatic access).

## Features

### Authentication ✅

- **Magic Link Authentication**: Passwordless signup/signin via email
- **Supabase Auth**: Email magic links and OAuth (Google/GitHub)
- **JWT Support**: Logged-in users get JWT tokens for seamless API access
- **API Keys**: Programmatic access with sk-/kb_ prefixed keys
- **Multi-Auth**: Endpoints support both JWT and API keys

### User Onboarding ✅

- **OAuth Onboarding**: Passwordless registration with organization setup and KB creation
- **Controlled Setup**: Users provide organization details before account creation
- **Welcome Emails**: Custom SMTP emails with dashboard links
- **Organization Management**: Create and manage organizations
- **Knowledge Bases**: Users can create multiple KBs per org

### Knowledge Base Features ✅

- **Multi-Tenant Architecture**: Organizations manage their own data
- **Knowledge Base Management**: Create, list, and manage KBs
- **ETL Pipeline**: Upload files (PDF, DOCX, etc.) and URLs
- **Document Processing**: Automatic extraction and vectorization
- **AI Querying**: Natural language RAG with context-aware answers
- **Vector Similarity Search**: PostgreSQL pgvector for retrieval
- **Conversation History**: Track interactions and responses
- **Human Handoff**: Escalation when AI can't resolve

## Tech Stack

- **Backend**: FastAPI (Python)
- **Database**: Supabase PostgreSQL with pgvector
- **Storage**: Supabase Storage
- **AI**: Pydantic AI with Google Gemini
- **Processing**: Docling for extraction, OpenLyne for web scraping
- **Embeddings**: Sentence Transformers (all-MiniLM-L6-v2)

## Quick Start

### Prerequisites

- Python 3.9+
- Supabase account
- Google AI API key

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
   pip install -r requirements.txt
   ```

3. **Environment setup**:

   ```bash
   cp .env.example .env
   # Edit .env with your API keys and frontend URL
   # FRONTEND_URL should match your frontend application's URL (e.g., http://localhost:3000 in development)
   ```

4. **Database setup**:

   - Create a Supabase project
   - Run `schema.sql` in Supabase SQL editor
   - Enable storage bucket

5. **Run the API**:

   ```bash
   python main.py
   ```

API available at `http://localhost:8000` with docs at `http://localhost:8000/docs`.

## User Flow

```
1. POST /auth/oauth/signin    → Get OAuth URL for Google/GitHub
2. User authenticates         → Redirect to /auth/callback
3. Check onboarding status    → org_id present/absent
4. If no org_id: redirect to /onboard
5. POST /auth/onboarding → Create org + KB + API key
6. POST /upload               → Upload files/URLs (JWT or API key)
7. POST /query                → Query KB + get answers (JWT or API key)
```

**Onboarding Flow:**
- New users authenticate → response has no `org_id` (incomplete onboarding)
- Frontend checks: `if (!response.org_id)` → redirect to `/onboard`
- User fills organization details
- POST to `/auth/onboarding` → creates org + KB
- Response includes `org_id`, `kb_id` (complete onboarding)

## API Endpoints

### Authentication

- `POST /auth/signup` - Magic link signup (email) → Send magic link
- `GET /auth/callback` - Magic link/OAuth callback → JWT + onboarding status
- `POST /auth/oauth/signin` - OAuth sign in → Get OAuth URL
- `POST /auth/onboarding` - Complete user onboarding → Create org/KB/API key
- `POST /auth/refresh` - Refresh JWT
- `POST /auth/signout` - Sign out
- `GET /me` - Get current user (JWT)
- `GET /onboarding` - Get welcome content and steps

### Knowledge Bases

- `POST /kb` - Create KB (JWT) → KBResponse
- `GET /kb/{kb_id}` - Get KB details
- `GET /orgs/{org_id}/kb` - List org KBs

### Organization Management

- `POST /orgs` - Create organization
- `GET /orgs/{org_id}` - Get org details
- `GET /orgs/{org_id}/users` - List users
- `POST /orgs/{org_id}/users` - Add user
- `DELETE /orgs/{org_id}/users/{user_id}` - Remove user

### Upload & Processing

- `POST /api/v1/upload` - Upload files/URLs (JWT or API key)
- `GET /api/v1/upload/status` - Check status
- `GET /api/v1/files` - List files

### Querying

- `POST /api/v1/query` - Query KB (JWT or API key) → AI answer + sources
- `GET /api/v1/conversations` - List conversations
- `POST /api/v1/conversations/{conv_id}/resolve` - Mark resolved

## Frontend Integration

Use the TypeScript client in `frontend-api-client.ts`:

```typescript
import { useKnowledgeBaseAPI } from './api-client';

// OAuth signin (new flow)
const response = await fetch('/auth/oauth/signin', {
  method: 'POST',
  body: JSON.stringify({ provider: 'google' })
});
// User completes OAuth → callback checks onboarding status
// If no org_id: redirect to /onboard
// After onboarding: user has org/kb, can upload files

// Initialize API with JWT after onboarding
const api = useKnowledgeBaseAPI(localStorage.getItem('token'));

// Upload files to user's KB
await api.uploadFiles([file1, file2]);

// Query default KB
const answer = await api.query('What is X?');
```

See `frontend-api-client.ts` for complete examples and React components.

## Authentication Methods

Both JWT and API keys are supported. Choose based on your use case:

### JWT (For Logged-in Users)

```typescript
// 1. OAuth signin
const response = await fetch('/auth/oauth/signin', {
  method: 'POST',
  body: JSON.stringify({ provider: 'google' })
});
const { redirect_url } = await response.json();
// Redirect user to redirect_url

// 2. After OAuth, check callback response
const callbackResponse = await fetch('/auth/callback?code=' + authCode);
const authData = await callbackResponse.json();

if (!authData.org_id) {
  // Redirect to onboarding - user needs to complete setup
  window.location.href = '/onboard';
} else {
  // User is fully set up with org/kb
  const api = useKnowledgeBaseAPI(authData.access_token);
}

// 3. Complete onboarding (if needed)
const onboardingResponse = await fetch('/auth/onboarding', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${authData.access_token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    organization_name: 'My Company',
    description: 'Knowledge base for our team',
    team_size: 5
  })
});

const onboardingData = await onboardingResponse.json();
// onboardingData: { org_id, kb_id, message }
// No api_key generated during onboarding
```

**Advantages:**
- ✅ User-scoped: tied to user's org after onboarding
- ✅ Controlled account creation: collect org details first
- ✅ Seamless frontend integration
- ✅ Secure: JWT-based authentication
- ✅ Passwordless OAuth authentication

### API Keys (For Programmatic Access)

```typescript
// Use API key (sk-/kb_ prefix)
const api = useKnowledgeBaseAPI('sk-xxxxx');
```

**Advantages:**
- ✅ Server-to-server integrations
- ✅ External tool access
- ✅ Can be revoked without affecting users
- ✅ Fine-grained permissions

## Database Schema

Required tables:

- `organizations` - org metadata
- `users` - user profiles linked to orgs
- `knowledge_bases` - KBs linked to orgs
- `documents` - documents in KBs (with embeddings)
- `api_keys` - API keys with org/KB association
- `conversations` - conversation threads
- `messages` - conversation messages

See `schema.sql` for full schema.

## Error Handling

All endpoints return standard error responses:

```json
{
  "detail": "Invalid API key"
}
```

Common status codes:

- `200` - Success
- `400` - Bad request
- `401` - Unauthorized (invalid token/key)
- `403` - Forbidden (insufficient permissions)
- `404` - Not found
- `500` - Server error

## Contributing

This is an internal project. Please follow the existing patterns.

## License

Proprietary

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