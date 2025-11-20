# Botlyne Production Readiness Implementation Guide

## Overview

This guide documents the critical enhancements implemented to make the Botlyne knowledge base AI system production-ready. All P0 and P1 critical items have been completed and integrated.

## ✅ Completed Enhancements

### 1. Database Triggers & Auto-Cleanup

**Features Implemented:**
- **Abandoned Conversation Cleanup**: Automatically marks conversations older than 24 hours as resolved
- **Message Cleanup**: Removes messages from conversations resolved for more than 7 days
- **Audit Logging**: Comprehensive audit trail for all critical table operations
- **Index Maintenance**: Automated statistics updates and maintenance tasks

**Database Tables Added:**
```sql
-- Audit logging
audit_logs (table_name, record_id, operation, old_values, new_values, user_id, org_id, timestamp)

-- Integration support
integrations, integration_configs, integration_events

-- Human agent workflow
support_agents, agent_assignments, agent_queue, agent_responses
```

**Triggers Created:**
- `cleanup_abandoned_conversations` - Handles conversation timeouts
- `cleanup_old_messages` - Manages message retention
- `log_audit_event` - Tracks all data changes
- `update_conversation_metrics` - Updates performance metrics

### 2. Webhook Security Implementation

**Features Implemented:**
- **HMAC Signature Validation**: Validates request authenticity with timestamp protection
- **Rate Limiting**: Redis-based rate limiting (60 req/min default) with in-memory fallback
- **IP Whitelisting**: CIDR and single IP support per integration
- **Request Monitoring**: Comprehensive logging of all webhook activity

**Security Features:**
```python
# Webhook endpoint protection
POST /api/v1/integrations/webhook/{integration_id}

# Required headers
X-Timestamp: <unix_timestamp>
X-Signature: <hmac_sha256_signature>
```

**Configuration:**
```python
# Environment variables
REDIS_URL=redis://localhost:6379
WEBHOOK_SIGNATURE_SECRET=your_webhook_secret
ALLOWED_WEBHOOK_IPS=192.168.1.0/24,10.0.0.1
RATE_LIMIT_REQUESTS_PER_MINUTE=60
```

### 3. Human Agent Workflow

**Features Implemented:**
- **Agent Assignment System**: Automatic and manual conversation assignment
- **Queue Management**: Priority-based queue with timeout handling
- **Response Injection**: Agents can inject responses into active conversations
- **Escalation Workflows**: Automatic and manual conversation escalation
- **Agent Status Management**: Real-time agent availability tracking

**API Endpoints:**
```python
# Agent management
POST /api/v1/agents/assign/{conversation_id}
POST /api/v1/agents/queue
POST /api/v1/agents/response/{conversation_id}
POST /api/v1/agents/escalate/{conversation_id}
```

**Agent Capabilities:**
- Skill-based routing
- Shift hour awareness
- Workload balancing
- Conversation transfers
- Performance tracking

### 4. Error Handling & Resilience

**Features Implemented:**
- **Circuit Breaker Pattern**: Protects services from cascading failures
- **Retry Mechanisms**: Exponential backoff with jitter for robust retries
- **Graceful Degradation**: Fallback strategies for service failures
- **Structured Error Logging**: JSON-formatted logs with full context

**Usage Examples:**
```python
# Circuit breaker protection
from src.core.retry_utils import with_circuit_breaker

@with_circuit_breaker(failure_threshold=5, timeout=60)
async def external_api_call():
    # Service call with automatic protection
    pass

# Retry with backoff
from src.core.retry_utils import retry_async

@retry_async(max_attempts=3, base_delay=1.0, exponential_base=2.0)
async def unreliable_service():
    # Service call with automatic retries
    pass
```

### 5. Monitoring & Observability

**Features Implemented:**
- **Health Checks**: Comprehensive health monitoring for all services
- **Performance Metrics**: Request counting, error tracking, response time monitoring
- **Structured Logging**: JSON-formatted logs with correlation IDs
- **Alerting**: Automatic alerting for critical service failures

**Health Check Endpoints:**
```
GET /health - Basic health check
GET /health/detailed - Full system health report
GET /metrics - Performance metrics summary
```

**Monitoring Features:**
- Database connectivity checks
- Redis availability verification
- External API health monitoring
- System resource monitoring (CPU, memory, disk)
- Conversation processing health
- Circuit breaker status tracking

## Configuration

### Environment Variables

```bash
# Database and Redis
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_supabase_key
REDIS_URL=redis://localhost:6379

# External Services
GOOGLE_API_KEY=your_google_api_key
EVOLUTION_API_BASE_URL=https://evolution-api.sliplane.app
EVOLUTION_API_GLOBAL_KEY=your_evolution_api_key

# Security
WEBHOOK_SIGNATURE_SECRET=your_webhook_secret
ALLOWED_WEBHOOK_IPS=192.168.1.0/24

# Rate Limiting
RATE_LIMIT_REQUESTS_PER_MINUTE=100
RATE_LIMIT_REQUESTS_PER_HOUR=1000

# Circuit Breaker
CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
CIRCUIT_BREAKER_TIMEOUT=60

# Logging
LOG_LEVEL=INFO
ENABLE_STRUCTURED_LOGGING=true
```

### Database Setup

1. **Run the enhanced schema:**
```bash
# Apply all production enhancements
psql -d your_database -f schema.sql
```

2. **Set up Redis (optional but recommended):**
```bash
# Install and start Redis
redis-server
```

3. **Configure Supabase triggers:**
```sql
-- Run maintenance tasks (schedule this via cron)
SELECT run_maintenance_tasks();
```

## API Usage Examples

### Webhook Security

```javascript
// Secure webhook client
const payload = {
  message: { body: "Hello from webhook" },
  timestamp: Date.now()
};

const signature = signPayload(payload, webhookSecret);

fetch(webhookUrl, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-Timestamp': payload.timestamp,
    'X-Signature': signature
  },
  body: JSON.stringify(payload)
});
```

### Human Agent Workflow

```python
# Assign conversation to agent
from src.services.human_agent_workflow import human_agent_workflow

result = await human_agent_workflow.assign_conversation_to_agent(
    conversation_id="conv_123",
    priority="high",
    assignment_type="escalation"
)

# Inject agent response
await human_agent_workflow.inject_agent_response(
    conversation_id="conv_123",
    agent_id="agent_456",
    message="I'll help you with that issue.",
    message_type="text"
)
```

### Error Handling

```python
from src.services.error_handling import error_handler, error_context

@error_handler(track_errors=True)
async def risky_operation():
    # Function with automatic error tracking
    pass

# Context manager usage
with error_context(error_tracker, {"operation": "user_upload"}):
    # Errors will be automatically tracked
    perform_operation()
```

### Circuit Breaker Protection

```python
from src.core.retry_utils import retry_async, with_circuit_breaker

@with_circuit_breaker(failure_threshold=3)
@retry_async(max_attempts=3)
async def external_api_call():
    # Protected service call
    return await http_client.get(url)
```

## Health Monitoring

### Health Check Responses

**Healthy System:**
```json
{
  "overall_status": "healthy",
  "timestamp": "2025-11-20T09:46:13.897Z",
  "checks": {
    "database": {
      "status": "healthy",
      "response_time_ms": 45.2
    },
    "redis": {
      "status": "healthy",
      "response_time_ms": 2.1
    }
  },
  "total_checks": 5,
  "healthy_checks": 5
}
```

**Degraded System:**
```json
{
  "overall_status": "degraded",
  "critical_issues": [],
  "checks": {
    "external_apis": {
      "status": "degraded",
      "message": "External APIs overall status: degraded - Google AI API unavailable"
    }
  }
}
```

### Metrics Collection

```python
from src.services.health_checks import metrics_collector

# Automatic metrics collection via middleware
# Manual metrics recording
metrics_collector.record_request(
    endpoint="/api/v1/query",
    status_code=200,
    response_time=1.245
)
```

## Production Deployment Checklist

### Security
- [ ] Configure webhook secrets for all integrations
- [ ] Set up IP whitelisting for webhook endpoints
- [ ] Enable Redis for production rate limiting
- [ ] Configure proper CORS origins
- [ ] Set up SSL/TLS certificates

### Monitoring
- [ ] Deploy Redis instance for rate limiting
- [ ] Configure log aggregation (ELK, Datadog, etc.)
- [ ] Set up alerting for health check failures
- [ ] Monitor circuit breaker states
- [ ] Track error rates and response times

### Database
- [ ] Apply enhanced schema with triggers
- [ ] Set up regular maintenance tasks
- [ ] Configure audit log retention policies
- [ ] Monitor database performance metrics

### Load Testing
- [ ] Test rate limiting under load
- [ ] Verify circuit breaker behavior
- [ ] Test webhook security under attack scenarios
- [ ] Validate agent workflow performance
- [ ] Check health check endpoint reliability

## Troubleshooting

### Common Issues

**Circuit Breaker Open:**
```python
# Check circuit breaker status
from src.core.retry_utils import resilience_manager
health_status = resilience_manager.get_health_status()
```

**High Error Rates:**
```python
# Check error tracking
from src.services.error_handling import error_tracker
# Errors are automatically tracked in audit_logs table
```

**Webhook Failures:**
```python
# Check webhook logs
# Integration events are tracked in integration_events table
```

### Log Analysis

**Structured Logs:**
All production logs are JSON-formatted for easy parsing:

```json
{
  "timestamp": "2025-11-20T09:46:13.897Z",
  "level": "ERROR",
  "message": "Database connection failed",
  "service": "botlyne",
  "exception": {
    "type": "ConnectionError",
    "message": "Connection refused"
  }
}
```

**Health Check Logs:**
```json
{
  "timestamp": "2025-11-20T09:46:13.897Z",
  "level": "WARNING",
  "message": "Health check degraded",
  "overall_status": "degraded",
  "check_results": {
    "external_apis": "degraded"
  }
}
```

## Support

For issues or questions:
1. Check the health check endpoints for system status
2. Review structured logs for detailed error information
3. Use the metrics endpoint for performance analysis
4. Monitor circuit breaker states for service health

## Performance Considerations

- **Redis**: Use for production rate limiting and caching
- **Circuit Breakers**: Prevent cascade failures in microservices
- **Health Checks**: Run every 60 seconds by default
- **Audit Logs**: Automatic cleanup after 90 days
- **Message Cleanup**: Messages deleted after 7 days for resolved conversations

This implementation provides a robust, scalable, and monitorable production environment for the Botlyne knowledge base AI system.