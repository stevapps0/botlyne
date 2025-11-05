-- Enable necessary extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Custom types (with IF NOT EXISTS to avoid conflicts)
DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('admin', 'member');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE conversation_status AS ENUM ('ongoing', 'resolved_ai', 'resolved_human', 'escalated');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE message_sender AS ENUM ('user', 'ai');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Create tables (with IF NOT EXISTS to avoid conflicts)
CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role user_role DEFAULT 'member',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS knowledge_bases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS files (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kb_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_path TEXT, -- Supabase Storage path for uploaded files
    url TEXT, -- For URLs
    file_type TEXT NOT NULL, -- e.g., 'pdf', 'docx', 'url'
    size_bytes BIGINT,
    uploaded_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kb_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    file_id UUID REFERENCES files(id) ON DELETE SET NULL, -- Link to source file/URL
    content TEXT NOT NULL,
    embedding VECTOR(384), -- Adjust dimension based on your model (384 for all-MiniLM-L6-v2)
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kb_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    status conversation_status DEFAULT 'ongoing',
    started_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conv_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender message_sender NOT NULL,
    content TEXT NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    permissions JSONB DEFAULT '{"read": true, "write": true, "admin": false}',
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conv_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE UNIQUE,
    response_time FLOAT,
    resolution_time FLOAT,
    satisfaction_score INTEGER CHECK (satisfaction_score >= 1 AND satisfaction_score <= 5),
    ai_responses INTEGER DEFAULT 0,
    handoff_triggered BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance (with IF NOT EXISTS)
CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(org_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_bases_org_id ON knowledge_bases(org_id);
CREATE INDEX IF NOT EXISTS idx_files_kb_id ON files(kb_id);
CREATE INDEX IF NOT EXISTS idx_documents_kb_id ON documents(kb_id);
CREATE INDEX IF NOT EXISTS idx_documents_file_id ON documents(file_id);
CREATE INDEX IF NOT EXISTS idx_documents_embedding ON documents USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_kb_id ON conversations(kb_id);
CREATE INDEX IF NOT EXISTS idx_messages_conv_id ON messages(conv_id);
CREATE INDEX IF NOT EXISTS idx_metrics_conv_id ON metrics(conv_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_org_id ON api_keys(org_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_active ON api_keys(is_active) WHERE is_active = true;

-- RPC function for vector similarity search
CREATE OR REPLACE FUNCTION match_documents(
    query_embedding VECTOR(384),
    kb_id UUID,
    match_count INT DEFAULT 5
)
RETURNS TABLE(
    id UUID,
    content TEXT,
    metadata JSONB,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        d.id,
        d.content,
        d.metadata,
        1 - (d.embedding <=> query_embedding) AS similarity
    FROM documents d
    WHERE d.kb_id = match_documents.kb_id
    ORDER BY d.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- Function to get org_id for a user (helper for RLS)
CREATE OR REPLACE FUNCTION get_user_org_id(user_id UUID)
RETURNS UUID
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN (SELECT org_id FROM users WHERE id = user_id);
END;
$$;

-- Enable Row Level Security
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_bases ENABLE ROW LEVEL SECURITY;
ALTER TABLE files ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;

-- Row Level Security Policies
-- Organizations: Users can only see their own org
CREATE POLICY "org_select_policy" ON organizations
    FOR SELECT USING (id = get_user_org_id(auth.uid()));

-- Users: Users can view members of their org
CREATE POLICY "users_select_policy" ON users
    FOR SELECT USING (org_id = get_user_org_id(auth.uid()));

-- Knowledge bases: Users can access KBs in their org
CREATE POLICY "kb_all_policy" ON knowledge_bases
    FOR ALL USING (org_id = get_user_org_id(auth.uid()));

-- Files: Access via KB
CREATE POLICY "files_all_policy" ON files
    FOR ALL USING (kb_id IN (SELECT id FROM knowledge_bases WHERE org_id = get_user_org_id(auth.uid())));

-- Documents: Access via KB
CREATE POLICY "documents_all_policy" ON documents
    FOR ALL USING (kb_id IN (SELECT id FROM knowledge_bases WHERE org_id = get_user_org_id(auth.uid())));

-- Conversations: Users can access their own conversations
CREATE POLICY "conversations_all_policy" ON conversations
    FOR ALL USING (user_id = auth.uid());

-- Messages: Access via conversation
CREATE POLICY "messages_all_policy" ON messages
    FOR ALL USING (conv_id IN (SELECT id FROM conversations WHERE user_id = auth.uid()));

-- Metrics: Access via conversation
CREATE POLICY "metrics_all_policy" ON metrics
    FOR ALL USING (conv_id IN (SELECT id FROM conversations WHERE user_id = auth.uid()));

-- API Keys: Organization admins can manage their org's API keys
CREATE POLICY "api_keys_all_policy" ON api_keys
    FOR ALL USING (org_id = get_user_org_id(auth.uid()));

-- Triggers for updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_organizations_updated_at BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();