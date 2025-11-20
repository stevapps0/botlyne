# Frontend Integration Guide

This guide shows how to integrate with the Knowledge Base AI API from a frontend application. Authentication is handled entirely client-side using Supabase Auth.

**New Features**: The API now includes WhatsApp integration, human agent workflows, production security features, and monitoring capabilities.

## Base URL
```
http://localhost:8000
```

## Health Checks and Monitoring

### 1. Basic Health Check

**Request:**
```bash
curl -X GET "http://localhost:8000/health"
```

**Success Response (200):**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "message": "Knowledge Base AI API is running"
}
```

### 2. Detailed Health Check

**Request:**
```bash
curl -X GET "http://localhost:8000/health/detailed"
```

**Success Response (200):**
```json
{
  "overall_status": "healthy",
  "timestamp": "2024-01-01T00:00:00Z",
  "checks": {
    "database": "healthy",
    "ai_service": "healthy",
    "redis": "healthy"
  },
  "critical_issues": []
}
```

### 3. System Metrics

**Request:**
```bash
curl -X GET "http://localhost:8000/metrics"
```

**Success Response (200):**
```json
{
  "total_requests": 1250,
  "active_users": 45,
  "total_conversations": 320,
  "average_response_time": 1.2,
  "error_rate": 0.02
}
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
  "detail": "Invalid token or user not found"
}
```

### 3. Get Onboarding Content

Get onboarding welcome content for new users.

**Request:**
```bash
curl -X GET "http://localhost:8000/onboarding"
```

**Success Response (200):**
```json
{
  "title": "Welcome to Your Knowledge Base!",
  "content": "Welcome to your new knowledge base! Here's how to get started...",
  "steps": [
    {
      "title": "Upload Your First Document",
      "description": "Add documents to your knowledge base to start asking questions.",
      "action": "upload"
    }
  ]
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

### 4. Invite User to Organization

**Request:**
```bash
curl -X POST "http://localhost:8000/orgs/org-uuid/invites" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "newuser@example.com",
    "role": "member"
  }'
```

**Success Response (200):**
```json
{
  "message": "Invitation sent successfully",
  "invite_id": "invite-uuid"
}
```

### 5. Accept Organization Invitation

**Request:**
```bash
curl -X POST "http://localhost:8000/accept-invite/invite-uuid"
```

**Success Response (200):**
```json
{
  "redirect_url": "http://localhost:8081/signup?invite=invite-uuid",
  "org_id": "org-uuid",
  "role": "member"
}
```

### 6. Leave Organization

**Request:**
```bash
curl -X POST "http://localhost:8000/orgs/org-uuid/leave" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Success Response (200):**
```json
{
  "message": "Successfully left the organization"
}
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

### 1. Query Knowledge Base (Enhanced AI Agent)

**Request:**
```bash
curl -X POST "http://localhost:8000/api/v1/query" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is machine learning?",
    "kb_id": "kb-uuid",  // Optional: overrides API key KB
    "conversation_id": null
  }'
```

**Success Response (200):**
```json
{
  "conversation_id": "conv-uuid",
  "user_id": "customer_123",
  "user_message": "What is machine learning?",
  "ai_response": "Machine learning is a subset of artificial intelligence...",
  "sources": [
    {
      "title": "Machine Learning Guide",
      "url": "http://localhost:8000/api/v1/files/file-123/view",
      "filename": "ml_guide.pdf",
      "relevance_score": 0.89,
      "excerpt": "Machine learning is a method of data analysis that automates analytical model building..."
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

### 2. Query Flow (Enhanced AI Agent)

```javascript
const queryKB = async (message, kbId = null, conversationId = null) => {
  const token = localStorage.getItem('token');
  const response = await fetch('/api/v1/query', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({
      message,           // Changed from 'query' to 'message'
      kb_id: kbId,       // Optional: overrides API key KB
      conversation_id: conversationId
    })
  });

  const result = await response.json();

  // Handle standardized sources with clickable links
  if (result.sources) {
    result.sources.forEach(source => {
      console.log(`Source: ${source.title} (${source.relevance_score})`);
      if (source.url) {
        // Open source document in new tab
        window.open(source.url, '_blank');
      }
    });
  }

  return result;
};

// Health check function
const checkHealth = async () => {
  const response = await fetch('/health');
  return response.json();
};

// Get detailed health status
const getDetailedHealth = async () => {
  const response = await fetch('/health/detailed');
  return response.json();
};

// Get system metrics
const getMetrics = async () => {
  const response = await fetch('/metrics');
  return response.json();
};

// Get onboarding content
const getOnboardingContent = async () => {
  const response = await fetch('/onboarding');
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

## WhatsApp Integration

### 1. Create WhatsApp Integration

**Request:**
```bash
curl -X POST "http://localhost:8000/api/v1/integrations" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "whatsapp",
    "name": "Customer Support WhatsApp",
    "kb_id": "your_kb_id_here"
  }'
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "WhatsApp integration created successfully",
  "data": {
    "integration": {
      "id": "integration-uuid",
      "org_id": "org-uuid",
      "type": "whatsapp",
      "name": "Customer Support WhatsApp",
      "status": "active",
      "kb_id": "kb-uuid",
      "configs": [
        {
          "key": "instance_name",
          "value": "org-uuid_whatsapp_uuid8",
          "is_secret": false
        }
      ],
      "created_at": "2024-01-01T00:00:00.000000+00:00",
      "updated_at": "2024-01-01T00:00:00.000000+00:00"
    }
  }
}
```

### 2. Get QR Code for WhatsApp Setup

**Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/integrations/integration-uuid/qr" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "QR code retrieved successfully",
  "data": {
    "qr_code": {
      "base64": "iVBORw0KGgoAAAANSUhEUgAA...",
      "ascii": "█████████████████████████████████...",
      "url": "https://example.com/qr"
    }
  }
}
```

### 3. List Organization Integrations

**Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/integrations" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Integrations retrieved successfully",
  "data": {
    "integrations": [
      {
        "id": "integration-uuid",
        "org_id": "org-uuid",
        "type": "whatsapp",
        "name": "Customer Support WhatsApp",
        "status": "active",
        "kb_id": "kb-uuid",
        "configs": [
          {
            "key": "instance_name",
            "value": "***",
            "is_secret": false
          }
        ],
        "created_at": "2024-01-01T00:00:00.000000+00:00",
        "updated_at": "2024-01-01T00:00:00.000000+00:00"
      }
    ]
  }
}
```

### 4. Get Integration Details

**Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/integrations/integration-uuid" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Integration retrieved successfully",
  "data": {
    "integration": {
      "id": "integration-uuid",
      "org_id": "org-uuid",
      "type": "whatsapp",
      "name": "Customer Support WhatsApp",
      "status": "active",
      "kb_id": "kb-uuid",
      "configs": [...],
      "created_at": "2024-01-01T00:00:00.000000+00:00",
      "updated_at": "2024-01-01T00:00:00.000000+00:00"
    }
  }
}
```

### 5. Delete Integration

**Request:**
```bash
curl -X DELETE "http://localhost:8000/api/v1/integrations/integration-uuid" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Integration deleted successfully"
}
```

### Frontend WhatsApp Integration Flow

```javascript
const setupWhatsAppIntegration = async (kbId, integrationName = 'Customer Support WhatsApp') => {
  const token = localStorage.getItem('token');

  try {
    // 1. Create WhatsApp integration
    const createResponse = await fetch('/api/v1/integrations', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        type: 'whatsapp',
        name: integrationName,
        kb_id: kbId
      })
    });

    const createData = await createResponse.json();
    if (!createData.success) {
      throw new Error(createData.error || createData.message);
    }

    const integrationId = createData.data.integration.id;

    // 2. Get QR code for setup
    const qrResponse = await fetch(`/api/v1/integrations/${integrationId}/qr`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });

    const qrData = await qrResponse.json();
    if (!qrData.success) {
      throw new Error(qrData.error || qrData.message);
    }

    // 3. Display QR code to user
    displayQRCode(qrData.data.qr_code);

    // 4. Poll for connection status (optional)
    const checkStatus = async () => {
      const statusResponse = await fetch(`/api/v1/integrations/${integrationId}`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const statusData = await statusResponse.json();
      return statusData.data.integration.status;
    };

    // Check status every 5 seconds until active
    const pollStatus = setInterval(async () => {
      try {
        const status = await checkStatus();
        if (status === 'active') {
          clearInterval(pollStatus);
          showSuccessMessage('WhatsApp integration is now active!');
        }
      } catch (error) {
        console.error('Status check failed:', error);
      }
    }, 5000);

  } catch (error) {
    console.error('WhatsApp setup failed:', error);
    showErrorMessage('Failed to setup WhatsApp integration');
  }
};

// List all integrations
const listIntegrations = async () => {
  const token = localStorage.getItem('token');
  const response = await fetch('/api/v1/integrations', {
    headers: { 'Authorization': `Bearer ${token}` }
  });
  const data = await response.json();
  return data.data.integrations;
};

// Delete integration
const deleteIntegration = async (integrationId) => {
  const token = localStorage.getItem('token');
  const response = await fetch(`/api/v1/integrations/${integrationId}`, {
    method: 'DELETE',
    headers: { 'Authorization': `Bearer ${token}` }
  });
  return response.json();
};

const displayQRCode = (qrCodeData) => {
  // Display QR code in modal or dedicated UI
  const qrContainer = document.getElementById('qr-code-container');
  qrContainer.innerHTML = `
    <img src="data:image/png;base64,${qrCodeData.base64}" alt="WhatsApp QR Code">
    <p>Scan this QR code with WhatsApp on your phone to connect your business account.</p>
  `;
};
```

## Webapp Chat Integration

### 1. Create Webapp Chat Integration

**Request:**
```bash
curl -X POST "http://localhost:8000/api/v1/integrations" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "webchat",
    "name": "Website Chat Widget",
    "kb_id": "your_kb_id_here"
  }'
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Webchat integration created successfully",
  "data": {
    "integration": {
      "id": "integration-uuid",
      "org_id": "org-uuid",
      "type": "webchat",
      "name": "Website Chat Widget",
      "status": "active",
      "kb_id": "kb-uuid",
      "configs": [
        {
          "key": "chat_endpoint",
          "value": "http://localhost:8000/chat/a1b2c3",
          "is_secret": false
        },
        {
          "key": "shortcode",
          "value": "a1b2c3",
          "is_secret": false
        }
      ],
      "created_at": "2024-01-01T00:00:00.000000+00:00",
      "updated_at": "2024-01-01T00:00:00.000000+00:00"
    }
  }
}
```

### 2. Send Chat Message

**Request:**
```bash
curl -X POST "http://localhost:8000/chat/a1b2c3" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "How do I reset my password?",
    "session_id": null
  }'
```

**Success Response (200):**
```json
{
  "session_id": "session-uuid",
  "message": {
    "id": "msg-uuid",
    "role": "assistant",
    "content": "To reset your password, go to the login page and click 'Forgot Password'...",
    "timestamp": "2024-01-01T00:00:00"
  },
  "sources": [
    {
      "title": "Password Reset Guide",
      "filename": "password_guide.pdf",
      "relevance_score": 0.92,
      "excerpt": "Password reset instructions...",
      "url": "http://localhost:8000/api/v1/files/file-123/view"
    }
  ],
  "response_time": 1.45,
  "handoff_triggered": false
}
```

### 3. Stream Chat Response

**Request:**
```bash
curl -X POST "http://localhost:8000/chat/a1b2c3/stream" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What are your business hours?",
    "session_id": null,
    "stream": true
  }'
```

**Streaming Response:**
```
data: {"chunk": "Our business", "finished": false}

data: {"chunk": " hours are", "finished": false}

data: {"chunk": " Monday through Friday", "finished": false}

data: {"chunk": " 9 AM to 5 PM", "finished": false}

data: {"chunk": "", "finished": true, "sources": [...], "response_time": 1.23}
```

### 4. Get Chat Session History

**Request:**
```bash
curl -X GET "http://localhost:8000/chat/a1b2c3/session/session-uuid" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

**Success Response (200):**
```json
{
  "session_id": "session-uuid",
  "messages": [
    {
      "id": "msg-1",
      "role": "user",
      "content": "How do I reset my password?",
      "timestamp": "2024-01-01T00:00:00"
    },
    {
      "id": "msg-2",
      "role": "assistant",
      "content": "To reset your password...",
      "timestamp": "2024-01-01T00:00:01"
    }
  ],
  "is_active": true,
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T00:00:01"
}
```

### Frontend Webapp Chat Integration

```javascript
class ChatWidget {
  constructor(apiKey, shortcode, containerId) {
    this.apiKey = apiKey;
    this.shortcode = shortcode;
    this.container = document.getElementById(containerId);
    this.sessionId = null;
    this.init();
  }

  init() {
    // Create chat UI
    this.container.innerHTML = `
      <div class="chat-widget">
        <div class="chat-messages" id="messages"></div>
        <div class="chat-input">
          <input type="text" id="messageInput" placeholder="Type your message...">
          <button id="sendButton">Send</button>
        </div>
      </div>
    `;

    // Bind events
    document.getElementById('sendButton').onclick = () => this.sendMessage();
    document.getElementById('messageInput').onkeypress = (e) => {
      if (e.key === 'Enter') this.sendMessage();
    };
  }

  async sendMessage() {
    const input = document.getElementById('messageInput');
    const message = input.value.trim();
    if (!message) return;

    // Add user message to UI
    this.addMessage('user', message);
    input.value = '';

    try {
      const response = await fetch(`/chat/${this.shortcode}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.apiKey}`
        },
        body: JSON.stringify({
          message: message,
          session_id: this.sessionId
        })
      });

      const data = await response.json();
      if (data.session_id) {
        this.sessionId = data.session_id;
      }

      // Add AI response to UI
      this.addMessage('assistant', data.message.content);

      // Show sources if available
      if (data.sources && data.sources.length > 0) {
        this.showSources(data.sources);
      }

    } catch (error) {
      console.error('Chat error:', error);
      this.addMessage('assistant', 'Sorry, I encountered an error. Please try again.');
    }
  }

  async sendStreamingMessage(message) {
    // Add user message
    this.addMessage('user', message);

    try {
      const response = await fetch(`/chat/${this.shortcode}/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.apiKey}`
        },
        body: JSON.stringify({
          message: message,
          session_id: this.sessionId,
          stream: true
        })
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let assistantMessage = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = JSON.parse(line.slice(6));
            if (data.chunk) {
              assistantMessage += data.chunk;
              this.updateLastMessage('assistant', assistantMessage);
            }
            if (data.finished) {
              if (data.sources) {
                this.showSources(data.sources);
              }
              if (data.session_id) {
                this.sessionId = data.session_id;
              }
              break;
            }
          }
        }
      }

    } catch (error) {
      console.error('Streaming error:', error);
      this.addMessage('assistant', 'Sorry, I encountered an error.');
    }
  }

  addMessage(role, content) {
    const messages = document.getElementById('messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    messageDiv.textContent = content;
    messages.appendChild(messageDiv);
    messages.scrollTop = messages.scrollHeight;
  }

  updateLastMessage(role, content) {
    const messages = document.getElementById('messages');
    const lastMessage = messages.lastElementChild;
    if (lastMessage && lastMessage.classList.contains(role)) {
      lastMessage.textContent = content;
    } else {
      this.addMessage(role, content);
    }
  }

  showSources(sources) {
    const sourcesDiv = document.createElement('div');
    sourcesDiv.className = 'chat-sources';
    sourcesDiv.innerHTML = '<h4>Related Documents:</h4>' +
      sources.map(source =>
        `<a href="${source.url}" target="_blank">${source.title}</a> (${Math.round(source.relevance_score * 100)}% relevant)`
      ).join('<br>');
    document.getElementById('messages').appendChild(sourcesDiv);
  }
}

// Initialize chat widget
const chat = new ChatWidget('your-api-key', 'a1b2c3', 'chat-container');
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