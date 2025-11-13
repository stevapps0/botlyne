# Seamless User Onboarding - Implementation Summary

## Overview

Users can now complete the full flow with **one-click signup**: **email → magic link → instant account with org, KB, API key, and welcome content**.

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

### 1. Magic Link Authentication ✅

**File:** `src/api/v1/auth.py`

- Replaced password-based signup with magic link authentication
- Uses `supabase.auth.sign_in_with_otp()` for passwordless signup
- Unified callback handles both magic links and OAuth
- Auto-creates user, organization, knowledge base, and API key on first signup

### 2. Seamless Onboarding ✅

**Auto-created on signup:**
- User account in Supabase Auth
- Organization with personalized name
- Default knowledge base ("My Knowledge Base")
- API key associated with the KB
- Welcome content uploaded to KB for immediate querying

**New Endpoints:**
- `POST /auth/signup` - Magic link signup (email only)
- `GET /auth/callback` - Auto-setup callback for new users
- `GET /onboarding` - Welcome content and tutorial steps

### 3. Welcome Email Integration ✅

**File:** `src/api/v1/auth.py`

- Custom SMTP emails via Supabase Edge Function
- Includes API key, dashboard link, and onboarding instructions
- Non-blocking - signup succeeds even if email fails

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

### 1. Magic Link Signup
```typescript
// Send magic link
const response = await fetch('http://localhost:8000/auth/signup', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    email: 'user@example.com'
  })
});

// User receives email and clicks magic link
// Redirects to your app with auth code
```

### 2. Handle Auth Callback
```typescript
// After user clicks magic link, handle callback
const urlParams = new URLSearchParams(window.location.search);
const code = urlParams.get('code');

const response = await fetch(`http://localhost:8000/auth/callback?code=${code}`);
const { session, org_id, kb_id, api_key } = await response.json();

// Store credentials
localStorage.setItem('token', session.access_token);
localStorage.setItem('org_id', org_id);
localStorage.setItem('kb_id', kb_id);
localStorage.setItem('api_key', api_key);

// Account is fully set up - user can immediately upload/query
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
1. POST /auth/signup → Send magic link email
2. GET /auth/callback?code=xxx → Auto-create account + return JWT + org_id + kb_id + api_key
3. POST /api/v1/upload → Upload files with JWT (KB auto-selected)
4. POST /api/v1/query → Query KB with JWT
5. Verify responses include sources + answers
```

## Authentication Comparison

| Feature | JWT | API Key |
|---------|-----|---------|
| Magic link signup | ✅ | ❌ |
| Auto org/KB/API key creation | ✅ | ❌ |
| Welcome content & emails | ✅ | ❌ |
| Upload files | ✅ | ✅ |
| Query KB | ✅ | ✅ |
| Server-to-server | ❌ | ✅ |
| Revokable | ❌ | ✅ |
| Fine-grained permissions | ❌ | ✅ |

## Summary

✅ **Seamless one-click onboarding implemented**
- Magic link signup creates full account instantly
- Auto-provisioned: user, organization, knowledge base, API key
- Welcome content uploaded for immediate querying
- Custom welcome emails with credentials
- Passwordless authentication with Supabase
- Works with both JWT and API key authentication
