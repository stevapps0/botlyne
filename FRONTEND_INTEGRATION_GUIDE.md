# Frontend Integration Guide

This guide shows how to integrate with the Knowledge Base AI API from a frontend application. Authentication is handled entirely client-side using Supabase Auth.

## Base URL
```
http://localhost:8000
```

## Authentication

**Important**: Authentication is now handled entirely by Supabase client-side. The API only validates JWT tokens and API keys.

### 1. Supabase Client-Side Authentication

Use Supabase's JavaScript client for authentication:

```javascript
import { createClient } from '@supabase/supabase-js'

const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY)

// Magic Link Authentication
const signInWithMagicLink = async (email) => {
  const { data, error } = await supabase.auth.signInWithOtp({
    email: email,
    options: {
      redirectTo: `${window.location.origin}/auth/callback`
    }
  })
  return { data, error }
}

// OAuth Authentication (Google/GitHub)
const signInWithOAuth = async (provider) => {
  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: provider, // 'google' or 'github'
    options: {
      redirectTo: `${window.location.origin}/auth/callback`
    }
  })
  return { data, error }
}

// Handle Auth Callback
const handleAuthCallback = async () => {
  const { data, error } = await supabase.auth.getSession()
  if (data.session) {
    // User is authenticated
    const token = data.session.access_token
    localStorage.setItem('token', token)

    // Check if user needs onboarding
    const userInfo = await getUserInfo(token)
    if (!userInfo.org_id) {
      // Redirect to onboarding
      window.location.href = '/onboard'
    } else {
      // User is fully set up
      window.location.href = '/dashboard'
    }
  }
  return { data, error }
}
```

### 2. Get Current User Info

Get authenticated user's information using JWT token.

**Request:**
```bash
curl -X GET "http://localhost:8000/auth/user" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Success Response (200):**
```json
{
  "id": "user-uuid",
  "email": "user@example.com",
  "org_id": "org-uuid",
  "role": "admin",
  "kb_id": "kb-uuid"
}
```

**Failure Response (401):**
```json
{
  "detail": "Authentication failed"
}
```

### 3. Get Current User Info

Get authenticated user's information.

**Request:**
```bash
curl -X GET "http://localhost:8000/auth/user" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Success Response (200):**
```json
{
  "id": "user-uuid",
  "email": "user@example.com",
  "org_id": "org-uuid",
  "role": "admin",
  "kb_id": "kb-uuid"
}
```

**Failure Response (401):**
```json
{
  "detail": "Invalid token or user not found"
}
```

## Organization Management

**Note**: All organization endpoints now require authentication (JWT or API key).

### 1. Create Organization

**Request:**
```bash
curl -X POST "http://localhost:8000/orgs" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Company",
    "description": "A tech company focused on AI solutions",
    "team_size": 25
  }'
```

**Success Response (200):**
```json
{
  "id": "org-uuid",
  "name": "My Company",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z",
  "description": "A tech company focused on AI solutions",
  "team_size": 25,
  "shortcode": "a1b2c3"
}
```

### 2. Get Organization Details

**Request:**
```bash
curl -X GET "http://localhost:8000/orgs/org-uuid" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Success Response (200):**
```json
{
  "id": "org-uuid",
  "name": "My Company",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z",
  "description": "A tech company focused on AI solutions",
  "team_size": 25,
  "shortcode": "a1b2c3"
}
```

### 3. List Organization Users

**Request:**
```bash
curl -X GET "http://localhost:8000/orgs/org-uuid/users" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Success Response (200):**
```json
[
  {
    "id": "user-uuid",
    "org_id": "org-uuid",
    "role": "admin",
    "created_at": "2024-01-01T00:00:00Z",
    "email": "user@example.com",
    "first_name": "John",
    "last_name": "Doe"
  }
]
```

## Knowledge Base Management

**Note**: All knowledge base endpoints now require authentication (JWT or API key).

### 1. Create Knowledge Base

**Request:**
```bash
curl -X POST "http://localhost:8000/kb" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "My Knowledge Base", "description": "Company documentation"}'
```

**Success Response (200):**
```json
{
  "id": "kb-uuid",
  "org_id": "org-uuid",
  "name": "My Knowledge Base",
  "description": "Company documentation",
  "created_at": "2024-01-01T00:00:00Z"
}
```

### 2. Get Knowledge Base Details

**Request:**
```bash
curl -X GET "http://localhost:8000/kb/kb-uuid" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Success Response (200):**
```json
{
  "id": "kb-uuid",
  "org_id": "org-uuid",
  "name": "My Knowledge Base",
  "description": "Company documentation",
  "created_at": "2024-01-01T00:00:00Z"
}
```

### 3. List Organization Knowledge Bases

**Request:**
```bash
curl -X GET "http://localhost:8000/orgs/org-uuid/kb" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Success Response (200):**
```json
[
  {
    "id": "kb-uuid",
    "org_id": "org-uuid",
    "name": "My Knowledge Base",
    "description": "Company documentation",
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

## File Upload

### 1. Upload Files and URLs

**Request (multipart/form-data):**
```bash
curl -X POST "http://localhost:8000/upload" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -F "kb_id=kb-uuid" \
  -F "files=@document.pdf" \
  -F "urls=[\"https://example.com/doc1\", \"https://example.com/doc2\"]"
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Upload initiated. Processing in background.",
  "data": {
    "files_processed": 1,
    "urls_processed": 2
  }
}
```

### 2. Check Upload Status

**Request:**
```bash
curl -X GET "http://localhost:8000/upload/status?kb_id=kb-uuid" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Status retrieved successfully",
  "data": {
    "status": {
      "batch_id": "batch-uuid",
      "status": "completed",
      "progress": 3,
      "total_items": 3,
      "completed_at": "2024-01-01T00:00:00Z"
    }
  }
}
```

## Querying

### 1. Query Knowledge Base

**Request:**
```bash
curl -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is machine learning?",
    "kb_id": "kb-uuid",
    "conversation_id": null
  }'
```

**Success Response (200):**
```json
{
  "conversation_id": "conv-uuid",
  "user_message": "What is machine learning?",
  "ai_response": "Machine learning is a subset of artificial intelligence...",
  "sources": [
    {
      "content": "Machine learning is a method of data analysis...",
      "similarity": 0.85,
      "metadata": {
        "source": "ml_guide.pdf",
        "page": 1
      }
    }
  ],
  "response_time": 1.23,
  "handoff_triggered": false,
  "ticket_number": "X9Y8Z7"
}
```

**Failure Response (400):**
```json
{
  "detail": "No knowledge base specified. Either provide kb_id in request or ensure API key is associated with a knowledge base"
}
```

### 2. List Conversations

**Request:**
```bash
curl -X GET "http://localhost:8000/conversations" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Success Response (200):**
```json
[
  {
    "id": "conv-uuid",
    "kb_id": "kb-uuid",
    "ticket_number": "A1B2C3",
    "messages": [
      {
        "id": "msg-uuid",
        "sender": "user",
        "content": "What is AI?",
        "timestamp": "2024-01-01T00:00:00Z"
      },
      {
        "id": "msg-uuid-2",
        "sender": "ai",
        "content": "AI stands for Artificial Intelligence...",
        "timestamp": "2024-01-01T00:00:01Z"
      }
    ],
    "status": "active",
    "started_at": "2024-01-01T00:00:00Z",
    "resolved_at": null
  }
]
```

## API Key Management

### 1. Create API Key

**Request:**
```bash
curl -X POST "http://localhost:8000/apikeys" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My API Key",
    "permissions": {"read": true, "write": true, "admin": false},
    "expires_in_days": 365
  }'
```

**Success Response (200):**
```json
{
  "id": "key-uuid",
  "name": "My API Key",
  "key": "sk-abc123def456...",  // Full key returned only on creation
  "permissions": {
    "read": true,
    "write": true,
    "admin": false
  },
  "created_at": "2024-01-01T00:00:00Z",
  "expires_at": "2025-01-01T00:00:00Z",
  "last_used_at": null,
  "is_active": true,
  "kb_id": null
}
```

### 2. List API Keys

**Request:**
```bash
curl -X GET "http://localhost:8000/apikeys" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Success Response (200):**
```json
[
  {
    "id": "key-uuid",
    "name": "My API Key",
    "key_preview": "sk-abc12***************",
    "permissions": {
      "read": true,
      "write": true,
      "admin": false
    },
    "created_at": "2024-01-01T00:00:00Z",
    "expires_at": "2025-01-01T00:00:00Z",
    "last_used_at": "2024-01-01T12:00:00Z",
    "is_active": true,
    "kb_id": "kb-uuid"
  }
]
```

## Frontend Implementation Flow

### 1. Authentication Flow (Supabase Client-Side)

```javascript
import { createClient } from '@supabase/supabase-js'

const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY)

// 1. Sign in with magic link
const signInWithMagicLink = async (email) => {
  const { data, error } = await supabase.auth.signInWithOtp({
    email: email,
    options: {
      redirectTo: `${window.location.origin}/auth/callback`
    }
  })
  return { data, error }
}

// 2. Sign in with OAuth
const signInWithOAuth = async (provider) => {
  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: provider, // 'google' or 'github'
    options: {
      redirectTo: `${window.location.origin}/auth/callback`
    }
  })
  return { data, error }
}

// 3. Handle auth callback
const handleAuthCallback = async () => {
  const { data, error } = await supabase.auth.getSession()

  if (data.session) {
    const token = data.session.access_token
    localStorage.setItem('token', token)

    // Check onboarding status
    const userInfo = await getUserInfo(token)
    if (!userInfo.org_id) {
      window.location.href = '/onboard'
    } else {
      window.location.href = '/dashboard'
    }
  }
}

// 4. Get user info from API
const getUserInfo = async (token) => {
  const response = await fetch('/auth/user', {
    headers: { 'Authorization': `Bearer ${token}` }
  })
  return response.json()
}

// 5. Sign out
const signOut = async () => {
  await supabase.auth.signOut()
  localStorage.removeItem('token')
  window.location.href = '/login'
}
```

### 2. Query Flow

```javascript
const queryKB = async (query, kbId, conversationId = null) => {
  const token = localStorage.getItem('token');
  const response = await fetch('/query', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({
      query,
      kb_id: kbId,
      conversation_id: conversationId
    })
  });
  return response.json();
};
```

### 3. Upload Flow

```javascript
const uploadFiles = async (kbId, files, urls = []) => {
  const token = localStorage.getItem('token');
  const formData = new FormData();

  formData.append('kb_id', kbId);

  files.forEach(file => {
    formData.append('files', file);
  });

  if (urls.length > 0) {
    formData.append('urls', JSON.stringify(urls));
  }

  const response = await fetch('/upload', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}` },
    body: formData
  });
  return response.json();
};
```

## Error Handling

All API endpoints return appropriate HTTP status codes:

- `200` - Success
- `400` - Bad Request (validation errors)
- `401` - Unauthorized (invalid/missing token)
- `403` - Forbidden (insufficient permissions)
- `404` - Not Found
- `500` - Internal Server Error

Always check the response status and handle errors appropriately in your frontend application.