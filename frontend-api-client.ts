// Frontend API Client for Knowledge Base AI API
// TypeScript client for React frontend integration
// Supports both JWT (from authentication) and API keys

// For React/Vite environments - replace with your actual API URL
const API_BASE_URL = 'http://localhost:8000';

export interface AuthResponse {
  user: { id: string; email: string };
  session: { access_token: string };
  org_id: string;
}

export interface KBResponse {
  id: string;
  org_id: string;
  name: string;
  description: string;
  created_at: string;
}

export interface UploadResponse {
  success: boolean;
  message: string;
  data: {
    files_processed: number;
    urls_processed: number;
  };
  error?: string;
}

export interface QueryRequest {
  query: string;
  kb_id?: string; // Optional - uses token association if not provided
  conversation_id?: string; // Optional - for continuing conversations
}

export interface QueryResponse {
  conversation_id: string;
  user_message: string;
  ai_response: string;
  sources: Array<{
    content: string;
    similarity: number;
    metadata: Record<string, unknown>;
  }>;
  response_time: number;
  handoff_triggered: boolean;
}

export interface FileInfo {
  id: string;
  kb_id: string;
  filename: string;
  file_path?: string;
  url?: string;
  file_type: string;
  size_bytes?: number;
  uploaded_by: string;
  uploaded_at: string;
}

export interface UploadStatus {
  status: string;
  message?: string;
  data?: {
    status: string;
  };
}

class KnowledgeBaseAPI {
  private token: string; // Can be JWT or API key

  /**
   * Initialize API client with JWT or API key
   * @param token - JWT token from auth or API key (sk-/kb_ prefix)
   */
  constructor(token: string) {
    this.token = token;
  }

  private getHeaders(): HeadersInit {
    return {
      'Authorization': `Bearer ${this.token}`,
      'Content-Type': 'application/json',
    };
  }

  // ============ Authentication ============

  /**
   * Sign up with email and password (creates org automatically)
   */
  static async signup(email: string, password: string, organizationName?: string): Promise<AuthResponse> {
    const response = await fetch(`${API_BASE_URL}/auth/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email,
        password,
        organization_name: organizationName || `${email}'s Organization`,
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Signup failed');
    }

    return response.json();
  }

  /**
   * Sign in with email and password
   */
  static async signin(email: string, password: string): Promise<AuthResponse> {
    const response = await fetch(`${API_BASE_URL}/auth/signin`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Sign in failed');
    }

    return response.json();
  }

  // ============ Knowledge Base Management ============

  /**
   * Create a new knowledge base (JWT auth required)
   */
  async createKnowledgeBase(name: string, description?: string): Promise<KBResponse> {
    const response = await fetch(`${API_BASE_URL}/kb`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({
        name,
        description: description || '',
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'KB creation failed');
    }

    return response.json();
  }

  /**
   * Get knowledge base details
   */
  async getKnowledgeBase(kbId: string): Promise<KBResponse> {
    const response = await fetch(`${API_BASE_URL}/kb/${kbId}`, {
      method: 'GET',
      headers: this.getHeaders(),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to get KB');
    }

    return response.json();
  }

  // ============ Document Upload (ETL) ============

  /**
   * Upload files and URLs to knowledge base
   * Works with both JWT (logged-in users) and API keys
   */
  async uploadFiles(files: File[], urls?: string[]): Promise<UploadResponse> {
    const formData = new FormData();

    // Add files
    files.forEach((file) => {
      formData.append('files', file);
    });

    // Add URLs as JSON string if provided
    if (urls && urls.length > 0) {
      formData.append('urls', JSON.stringify(urls));
    }

    const response = await fetch(`${API_BASE_URL}/api/v1/upload`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${this.token}`,
        // Don't set Content-Type for FormData - browser sets it with boundary
      },
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Upload failed');
    }

    return response.json();
  }

  /**
   * Upload only URLs
   */
  async uploadUrls(urls: string[]): Promise<UploadResponse> {
    const response = await fetch(`${API_BASE_URL}/api/v1/upload`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ urls }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'URL upload failed');
    }

    return response.json();
  }

  // ============ Query & Answers ============

  /**
   * Query the knowledge base for answers
   * Works with both JWT (logged-in users) and API keys
   */
  async queryKnowledgeBase(request: QueryRequest): Promise<QueryResponse> {
    const response = await fetch(`${API_BASE_URL}/api/v1/query`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Query failed');
    }

    return response.json();
  }

  /**
   * Simple query without kb_id (uses token association)
   */
  query(query: string, kbId?: string, conversationId?: string): Promise<QueryResponse> {
    return this.queryKnowledgeBase({
      query,
      kb_id: kbId,
      conversation_id: conversationId,
    });
  }

  // ============ Utility Methods ============

  /**
   * Check upload processing status
   */
  async getUploadStatus(): Promise<UploadStatus> {
    const response = await fetch(`${API_BASE_URL}/api/v1/upload/status`, {
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${this.token}`,
      },
    });

    if (!response.ok) {
      throw new Error('Failed to get upload status');
    }

    return response.json();
  }

  /**
   * List files in knowledge base
   */
  async listFiles(): Promise<{ data: { files: FileInfo[] } }> {
    const response = await fetch(`${API_BASE_URL}/api/v1/files`, {
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${this.token}`,
      },
    });

    if (!response.ok) {
      throw new Error('Failed to list files');
    }

    return response.json();
  }
}

// React Hook for using the API
export function useKnowledgeBaseAPI(token: string) {
  const api = new KnowledgeBaseAPI(token);

  return {
    // Auth methods
    signup: (email: string, password: string, orgName?: string) =>
      KnowledgeBaseAPI.signup(email, password, orgName),
    signin: (email: string, password: string) => KnowledgeBaseAPI.signin(email, password),

    // KB methods
    createKnowledgeBase: (name: string, description?: string) =>
      api.createKnowledgeBase(name, description),
    getKnowledgeBase: (kbId: string) => api.getKnowledgeBase(kbId),

    // Upload methods
    uploadFiles: (files: File[], urls?: string[]) => api.uploadFiles(files, urls),
    uploadUrls: (urls: string[]) => api.uploadUrls(urls),

    // Query methods
    query: (query: string, kbId?: string, conversationId?: string) =>
      api.query(query, kbId, conversationId),
    queryKnowledgeBase: (request: QueryRequest) => api.queryKnowledgeBase(request),

    // Utility methods
    getUploadStatus: () => api.getUploadStatus(),
    listFiles: () => api.listFiles(),
  };
}

// Example usage in React components:

// Auth Component Example
/*
import React, { useState } from 'react';
import { useKnowledgeBaseAPI } from './api-client';

function AuthComponent({ onAuthSuccess }: { onAuthSuccess: (token: string, orgId: string) => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSignup = async () => {
    setLoading(true);
    setError('');
    try {
      const result = await KnowledgeBaseAPI.signup(email, password);
      localStorage.setItem('token', result.session.access_token);
      localStorage.setItem('org_id', result.org_id);
      onAuthSuccess(result.session.access_token, result.org_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleSignin = async () => {
    setLoading(true);
    setError('');
    try {
      const result = await KnowledgeBaseAPI.signin(email, password);
      localStorage.setItem('token', result.session.access_token);
      localStorage.setItem('org_id', result.org_id);
      onAuthSuccess(result.session.access_token, result.org_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container">
      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="Email"
      />
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Password"
      />
      {error && <div className="error">{error}</div>}
      <button onClick={handleSignup} disabled={loading}>
        {loading ? 'Loading...' : 'Sign Up'}
      </button>
      <button onClick={handleSignin} disabled={loading}>
        {loading ? 'Loading...' : 'Sign In'}
      </button>
    </div>
  );
}
*/

// KB Creation Component Example
/*
import React, { useState } from 'react';
import { useKnowledgeBaseAPI } from './api-client';

function CreateKBComponent({ token }: { token: string }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [loading, setLoading] = useState(false);
  const api = useKnowledgeBaseAPI(token);

  const handleCreate = async () => {
    setLoading(true);
    try {
      const kb = await api.createKnowledgeBase(name, description);
      localStorage.setItem('kb_id', kb.id);
      console.log('KB created:', kb);
    } catch (error) {
      console.error('Failed to create KB:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <input
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="KB Name"
      />
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Description"
      />
      <button onClick={handleCreate} disabled={loading || !name}>
        {loading ? 'Creating...' : 'Create KB'}
      </button>
    </div>
  );
}
*/

// Upload Component Example
/*
import React, { useState } from 'react';
import { useKnowledgeBaseAPI } from './api-client';

function UploadComponent({ token }: { token: string }) {
  const [files, setFiles] = useState<File[]>([]);
  const [urls, setUrls] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const api = useKnowledgeBaseAPI(token);

  const handleUpload = async () => {
    setUploading(true);
    try {
      const result = await api.uploadFiles(files, urls);
      console.log('Upload successful:', result);
      setFiles([]);
      setUrls([]);
    } catch (error) {
      console.error('Upload failed:', error);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div>
      <input
        type="file"
        multiple
        onChange={(e) => setFiles(Array.from(e.target.files || []))}
      />
      <textarea
        placeholder="Enter URLs (one per line)"
        value={urls.join('\n')}
        onChange={(e) => setUrls(e.target.value.split('\n').filter((url) => url.trim()))}
      />
      <button onClick={handleUpload} disabled={uploading || (files.length === 0 && urls.length === 0)}>
        {uploading ? 'Uploading...' : 'Upload'}
      </button>
    </div>
  );
}
*/

// Chat Component Example
/*
import React, { useState } from 'react';
import { useKnowledgeBaseAPI } from './api-client';

interface Message {
  id: string;
  text: string;
  isUser: boolean;
  sources?: Array<{ content: string; similarity: number }>;
}

function ChatComponent({ token }: { token: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string>();
  const api = useKnowledgeBaseAPI(token);

  const handleSendMessage = async () => {
    if (!input.trim()) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      text: input,
      isUser: true,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    try {
      const response = await api.query(input, undefined, conversationId);

      const aiMessage: Message = {
        id: response.conversation_id + '_ai',
        text: response.ai_response,
        isUser: false,
        sources: response.sources,
      };

      setMessages((prev) => [...prev, aiMessage]);
      setConversationId(response.conversation_id);
    } catch (error) {
      console.error('Query failed:', error);
      const errorMessage: Message = {
        id: Date.now().toString() + '_error',
        text: 'Sorry, I encountered an error. Please try again.',
        isUser: false,
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-container">
      <div className="messages">
        {messages.map((message) => (
          <div key={message.id} className={message.isUser ? 'user-message' : 'ai-message'}>
            <p>{message.text}</p>
            {message.sources && message.sources.length > 0 && (
              <div className="sources">
                <h4>Sources:</h4>
                {message.sources.map((source, index) => (
                  <div key={index} className="source">
                    <small>{source.content.substring(0, 100)}...</small>
                    <span>Similarity: {(source.similarity * 100).toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="input-container">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
          placeholder="Ask a question..."
          disabled={loading}
        />
        <button onClick={handleSendMessage} disabled={loading}>
          {loading ? 'Thinking...' : 'Send'}
        </button>
      </div>
    </div>
  );
}
*/

export default KnowledgeBaseAPI;