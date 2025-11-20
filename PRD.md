# Product Requirements Document (PRD): Multi-Tenant Knowledge Base AI API

## Overview
This document outlines the requirements for a multi-tenant API that enables organizations to create knowledge bases from uploaded files and URLs, and query them using an AI agent powered by retrieval-augmented generation (RAG). The system supports user management, performance tracking, and human handoff for unresolved queries.

## Product Vision
To provide organizations with a secure, scalable platform for building and querying custom knowledge bases using AI, with comprehensive analytics and seamless escalation to human support when needed.

## Target Users
- **Organizations**: Businesses needing internal knowledge management and customer support automation.
- **Administrators**: Org users who manage team members and knowledge bases.
- **Members**: Team users who upload content and query the knowledge base.
- **Support Teams**: Human agents who handle escalated queries.

## Key Features

### 1. Multi-Tenant Architecture
- Organizations can create accounts and manage multiple users.
- Admins can add/remove members with role-based access (admin/member).
- Complete data isolation between organizations using Row Level Security (RLS).

### 2. Authentication & Authorization
- User signup/signin via email/password or OAuth (Google/GitHub).
- JWT-based API authentication.
- Role-based permissions: Admins manage orgs/users; members access assigned knowledge bases.

### 3. Knowledge Base Management
- Create multiple knowledge bases per organization.
- Upload files (PDF, DOCX, PPTX, etc.) or URLs for processing.
- Automatic extraction, chunking, and vectorization of content.
- Track processing status and source metadata.

### 4. Advanced AI-Powered Querying
- **Intelligent Agent**: Specialized customer support AI with human-like conversation flow
- **Smart KB Search**: Automatic decision between conversational responses and knowledge base queries
- **Confidence Scoring**: AI responses include confidence scores (0-1) for quality assessment
- **Context Management**: Automatic truncation and optimization (max 8000 characters)
- **Safe Math Evaluation**: Secure mathematical calculations using sympy
- **Two-Stage Review**: Primary agent generates responses, review agent validates safety and quality
- **Escalation Detection**: Automatic identification of complex issues requiring human assistance
- **Email Collection**: Intelligent prompting for contact information during escalation
- **Source Transparency**: Clickable source links for response verification
- **Performance Monitoring**: Response times, tool usage, and analytics tracking
- **RAG with Vector Search**: Enhanced retrieval using pgvector similarity search
- **Conversation Continuity**: Full session management with message history

### 5. Performance Analytics
- Track metrics: Total conversations, AI resolution rate, average response time, customer satisfaction, resolution time, chats handled, chat deflection rate, escalation rate.
- Dashboard views for organization-level insights.
- Data export for further analysis.

### 6. Human Handoff
- Automatic escalation when AI confidence is low or user requests human help.
- Email notifications to support team with query details and conversation history.
- Manual resolution tracking and satisfaction scoring.

### 7. WhatsApp Integration ✅
- **AI-Powered WhatsApp Chat**: Connect WhatsApp Business accounts to knowledge bases
- **Automatic Customer Responses**: Instant AI answers from organization's KB
- **Multi-Organization Support**: Each org can connect their own WhatsApp instances
- **QR Code Setup**: Easy WhatsApp Web connection via secure QR scanning
- **Webhook Processing**: Real-time message handling and automated responses
- **Extensible Framework**: Ready for future integrations (email, API, etc.)

## Technical Requirements

### Architecture
- **Backend**: FastAPI (Python) for REST API with comprehensive logging and monitoring.
- **Database**: Supabase PostgreSQL with vector extensions and conversation/message storage.
- **Storage**: Supabase Storage for uploaded files with access-controlled viewing.
- **AI**: Advanced Pydantic AI agents with Google Gemini, confidence scoring, and two-stage review system.
- **Processing**: Docling for document extraction, OpenLyne for web scraping, Sentence Transformers for embeddings.
- **Safety**: Sympy for secure mathematical evaluation, input validation, and content filtering.

### API Endpoints
- **Auth**: `/auth/signup`, `/auth/signin`, `/auth/oauth/*`
- **Organizations**: `/orgs` (CRUD), `/orgs/{id}/users` (manage members)
- **Knowledge Bases**: `/orgs/{org_id}/kbs` (CRUD)
- **Uploads**: `/kbs/{kb_id}/upload` (files/URLs)
- **Querying**: `/api/v1/query` (AI responses)
- **Integrations**: `/api/v1/integrations` (WhatsApp, email, API setup)
- **Metrics**: `/orgs/{org_id}/metrics` (analytics)
- **Conversations**: `/conversations/{id}/resolve` (handoff management)

### Data Models
- **Organizations**: id, name, created_at, updated_at
- **Users**: id, org_id, role, created_at
- **Knowledge Bases**: id, org_id, name, created_at
- **Files**: id, kb_id, filename, file_path/url, file_type, size_bytes, uploaded_by, uploaded_at
- **Documents**: id, kb_id, file_id, content, embedding, metadata, created_at
- **Conversations**: id, user_id, kb_id, status, started_at, resolved_at
- **Messages**: id, conv_id, sender, content, timestamp
- **Metrics**: id, conv_id, response_time, resolution_time, satisfaction_score, ai_responses, handoff_triggered, created_at
- **Integrations**: id, org_id, type, name, status, kb_id, created_at, updated_at
- **Integration Configs**: id, integration_id, key, value, is_secret, created_at
- **Integration Events**: id, integration_id, event_type, payload, status, created_at

### Security
- Row Level Security (RLS) for tenant isolation.
- Input validation and sanitization.
- Rate limiting and file size restrictions.
- Secure storage of API keys and credentials.

### Performance
- Asynchronous processing for uploads and queries.
- Vector indexing for fast similarity search.
- Caching for frequently accessed data.
- Scalable to handle multiple organizations and large knowledge bases.

### Non-Functional Requirements
- **Availability**: 99.9% uptime.
- **Response Time**: <2s for queries, <10s for uploads.
- **Scalability**: Support 1000+ organizations, 10k+ documents per KB.
- **Compliance**: GDPR-compliant data handling.
- **Monitoring**: Logging, error tracking, and alerting.

## User Stories

### As an Admin
- I want to create an organization and invite team members so I can manage access.
- I want to create knowledge bases and assign them to users so they can contribute content.
- I want to view analytics dashboards so I can monitor AI performance and support efficiency.

### As a Member
- I want to upload documents and URLs so I can build the knowledge base.
- I want to ask questions in natural language so I can get accurate answers quickly.
- I want to rate responses so I can provide feedback for improvement.

### As a Support Agent
- I want to receive email notifications for escalated queries so I can provide human assistance.
- I want to access conversation history so I can understand context.
- I want to mark resolutions and collect satisfaction scores so I can track performance.

### As a WhatsApp Integration User
- I want to connect my WhatsApp Business account so customers can chat with AI.
- I want customers to receive instant, accurate responses from my knowledge base.
- I want to manage multiple WhatsApp integrations for different departments.
- I want to monitor WhatsApp conversation analytics and performance.

## Success Metrics
- **User Adoption**: Number of active organizations and API key usage.
- **AI Performance**: AI resolution rate >85% with confidence scoring validation.
- **User Satisfaction**: Average satisfaction score >4.2/5 with detailed feedback collection.
- **Response Quality**: Average confidence score >0.7 with review agent validation.
- **Response Times**: Average <2 seconds for queries, <1 second for conversational responses.
- **Escalation Rate**: <15% of queries with intelligent detection and smooth handoff.
- **Source Transparency**: >90% of KB responses include clickable source links.
- **Safety Score**: 100% of responses pass review agent safety checks.
- **WhatsApp Integration**: >80% of organizations with active WhatsApp integrations, <3 second average response time, >90% message success rate.

## Risks & Mitigations
- **AI Hallucinations**: Mitigated by RAG and source attribution in responses.
- **Data Privacy**: RLS and encryption ensure tenant isolation.
- **Scalability**: Use async processing and optimize queries.
- **Integration Issues**: Thorough testing of ETL pipeline and AI agent.

## Timeline
- **Phase 1 (MVP)**: Auth, org management, basic ETL, querying (2-3 weeks).
- **Phase 2**: Metrics, handoff, advanced features (2 weeks).
- **Phase 3**: Testing, deployment, monitoring (1 week).

## Dependencies
- Supabase account and configuration.
- Google AI API key.
- OpenLyne API key.
- Email service for notifications.
- Evolution API account and key (for WhatsApp integration).
- Redis (optional, for production performance optimization).
- Additional packages: slowapi, structlog, prometheus-client.

This PRD will be updated as development progresses and requirements evolve.