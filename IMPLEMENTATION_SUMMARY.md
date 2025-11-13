# User Onboarding Flow - Implementation Summary

## Overview

Users can now complete the full flow: **signup → create org → create KB → upload/ETL → query & get answers**.

**Authentication:** All endpoints support both:
- **JWT tokens** (from authenticated users - no prefix)
- **API keys** (for programmatic/external access - sk-/kb_ prefix)

The backend automatically detects token type and validates accordingly.

## Architecture

### Authentication Flow

```
Request with Bearer Token
    ↓
validate_bearer_token() in auth_utils.py
    ↓
    ├─ Has sk- or kb_ prefix? → API Key validation
    │                          └─ Check api_keys table
    │                          └─ Return org_id, kb_id, api_key_id
    │
    └─ No prefix? → JWT validation
                   └─ Supabase auth.get_user()
                   └─ Get org_id from users table
                   └─ Return user_id, org_id
```

## Changes Made

### 1. JWT & API Key Authentication ✅

**File:** `src/core/auth_utils.py` (NEW)

- Centralized token validation (JWT or API key)
- Detects token type: JWT (no prefix) vs API key (sk-/kb_ prefix)
- JWT validates via Supabase, fails immediately if invalid
- API key validates against database
- Returns `TokenData` with user/org/kb info

**Updated Files:**
- `src/api/v1/kb.py` - Uses centralized JWT/API key validation
- `src/api/v1/query.py` - Uses centralized JWT/API key validation
- `src/api/v1/upload.py` - Uses centralized JWT/API key validation

### 2. User Account Creation ✅
**Endpoint:** `POST /auth/signup`
**Input:**
```json
{
  "email": "user@example.com",
  "password": "secure_password",
  "organization_name": "My Company"
}
```
**Behavior:**
- Creates Supabase auth user
- Auto-creates organization
- Creates user record linked to org
- Returns JWT token + org_id

### 3. Sign In ✅
**Endpoint:** `POST /auth/signin`
**Input:**
```json
{
  "email": "user@example.com",
  "password": "password"
}
```
**Returns:** JWT token + org_id

### 4. Organization Management ✅
**Endpoints:**
- `POST /orgs` - Create org
- `GET /orgs/{org_id}` - Get org details
- `GET /orgs/{org_id}/users` - List users
- `POST /orgs/{org_id}/users` - Add user
- `DELETE /orgs/{org_id}/users/{user_id}` - Remove user

### 5. Knowledge Base Management ✅
**File:** `src/api/v1/auth.py` (NEW endpoints)

**Endpoints:**
- `POST /kb` - Create KB (JWT protected)
  ```json
  {
    "name": "Customer Support KB",
    "description": "FAQs and troubleshooting"
  }
  ```
- `GET /kb/{kb_id}` - Get KB details
- `GET /orgs/{org_id}/kb` - List org KBs

**Auth:** Only authenticated users in the org can create KBs

### 6. ETL Pipeline ✅

**Endpoint:** `POST /api/v1/upload`

**Features:**
- Upload files or URLs
- Auto-vectorize and chunk documents
- Store in vector DB
- Link to KB
- Works with both JWT and API keys

### 7. Query & Answers ✅

**Endpoint:** `POST /api/v1/query`

**Features:**
- Query KB with natural language
- Retrieve similar documents
- Generate AI-powered answers
- Return sources + similarity scores
- Works with both JWT and API keys

## Frontend Integration

### 1. Sign Up & Get Token
```typescript
const response = await fetch('http://localhost:8000/auth/signup', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    email: 'user@example.com',
    password: 'password',
    organization_name: 'My Org'
  })
});

const { session, org_id } = await response.json();
localStorage.setItem('token', session.access_token);
localStorage.setItem('org_id', org_id);
```

### 2. Create Knowledge Base
```typescript
const token = localStorage.getItem('token');
const response = await fetch('http://localhost:8000/kb', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
  },
  body: JSON.stringify({
    name: 'My KB',
    description: 'My knowledge base'
  })
});

const { id: kb_id } = await response.json();
localStorage.setItem('kb_id', kb_id);
```

### 3. Upload Documents
```typescript
const formData = new FormData();
formData.append('files', file);

const response = await fetch('http://localhost:8000/upload', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`
  },
  body: formData
});
```

### 4. Query & Get Answers
```typescript
const response = await fetch('http://localhost:8000/query', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
  },
  body: JSON.stringify({
    query: 'How do I reset my password?',
    kb_id: localStorage.getItem('kb_id')
  })
});

const { ai_response, sources } = await response.json();
```

## Database Requirements

Ensure these tables exist:
- `organizations` - org data
- `users` - user profiles linked to orgs
- `knowledge_bases` - KBs linked to orgs
- `documents` - documents in KBs
- `api_keys` - API keys with verify/update functions
- `conversations` - conversation threads
- `vector_embeddings` - embeddings for similarity search

## Testing Flow

```
1. POST /auth/signup → Get JWT + org_id
2. POST /kb → Create KB with JWT
3. POST /api/v1/upload → Upload files with JWT
4. POST /api/v1/query → Query KB with JWT
5. Verify responses include sources + answers
```

## Authentication Comparison

| Feature | JWT | API Key |
|---------|-----|---------|
| User signup | ✅ | ❌ |
| Auto org creation | ✅ | ❌ |
| KB creation | ✅ | ❌ |
| Upload files | ✅ | ✅ |
| Query KB | ✅ | ✅ |
| Server-to-server | ❌ | ✅ |
| Revokable | ❌ | ✅ |
| Fine-grained permissions | ❌ | ✅ |

## Summary

✅ **Complete user flow implemented**
- Users can create accounts with auto org creation
- JWT auth for authenticated users
- API keys for programmatic access
- ETL pipeline works with both auth methods
- Query/answers work with both auth methods
