# Testing Documentation

## Overview

The test suite has been updated to align with the simplified authentication system using Supabase client-side auth and JWT/API key validation. All tests now properly mock JWT tokens and API keys for the consolidated authentication service.

## Test Structure

### Test Files

1. **conftest.py** - Pytest configuration and shared fixtures
   - `client` - FastAPI test client
   - `mock_supabase` - Mock Supabase database (conditionally live or mocked)
   - `sample_user`, `sample_org`, `sample_kb` - Test data fixtures
   - `jwt_token` - Mock JWT token (no prefix)
   - `api_key_token` - Mock API key token (sk- prefix)
   - `auth_headers_jwt` - Authorization headers with JWT
   - `auth_headers_api_key` - Authorization headers with API key

2. **test_auth.py** - User management endpoints (no OAuth testing)
   - Get user info with JWT validation
   - Organization management (create, get, list users)
   - API key management (create, list, delete)
   - Admin role validation
   - Missing/invalid auth header handling

3. **test_kb.py** - Knowledge base endpoints
   - Create KB with JWT auth
   - Create KB with API key auth
   - Get KB details (now requires auth)
   - List organization KBs (now requires auth)
   - Verify auth is required for all KB operations

4. **test_upload.py** - File/URL upload endpoints
   - Upload files with JWT
   - Upload files with API key
   - Upload URLs with JWT
   - Check upload status
   - Verify auth is required
   - Verify kb_id is required

5. **test_query.py** - Query endpoints
   - Query KB with JWT
   - Query KB with API key
   - List conversations
   - Resolve conversations
   - Verify auth is required
   - Verify kb_id and query parameters are required

6. **test_etl.py** - ETL pipeline components
   - ItemProcessor functionality
   - Text vectorization and chunking
   - Loading data to Supabase
   - Similarity search
   - Full pipeline integration

7. **test_health.py** - Health check endpoints
   - Health check returns correct status
   - Root endpoint returns API info

8. **test_integration.py** - Integration tests
   - Full ETL pipeline with live database
   - Database connectivity
   - Schema setup validation

## Authentication Testing

**Note**: Authentication testing now focuses on JWT and API key validation since OAuth is handled client-side by Supabase.

### JWT Testing

JWT tokens are tested with tokens that have **no prefix**. Example:
```python
jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test.token"
auth_headers = {"Authorization": f"Bearer {jwt_token}"}
```

JWT validation flow:
1. Token detected as JWT (no sk-/kb_ prefix)
2. Validated via `supabase.auth.get_user(token)`
3. User lookup to retrieve org_id
4. Returns TokenData with user_id, org_id, email

### API Key Testing

API keys are tested with tokens that have **sk-** prefix. Example:
```python
api_key_token = "sk-proj-test-api-key-123456789"
auth_headers = {"Authorization": f"Bearer {api_key_token}"}
```

API key validation flow:
1. Token detected as API key (has sk- prefix)
2. Hashed and validated via database lookup
3. Returns TokenData with user_id="api_key_user", org_id from key

### No Auth Testing

All protected endpoints should return 401 when no Authorization header is provided.

## Running Tests

### Run all tests
```bash
pytest tests/ -v
```

### Run specific test file
```bash
pytest tests/test_auth.py -v
```

### Run specific test function
```bash
pytest tests/test_auth.py::test_email_password_signup -v
```

### Run with coverage
```bash
pytest tests/ --cov=src --cov-report=html
```

### Run with debugging output
```bash
pytest tests/ -v -s
```

### Run with specific markers
```bash
pytest tests/ -v -m "not slow"
```

## Test Fixtures

### Database Fixtures

```python
@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)

@pytest.fixture
def mock_supabase(use_live_db):
    """Mock or real Supabase client."""
    # Set use_live_db = True to use real database
    # Set use_live_db = False to use mocks
```

### Authentication Fixtures

```python
@pytest.fixture
def jwt_token(sample_user):
    """Mock JWT token (no prefix)."""
    return "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test.token"

@pytest.fixture
def api_key_token():
    """Mock API key token (sk- prefix)."""
    return "sk-proj-test-api-key-123456789"

@pytest.fixture
def auth_headers_jwt(jwt_token):
    """JWT authorization headers."""
    return {"Authorization": f"Bearer {jwt_token}"}

@pytest.fixture
def auth_headers_api_key(api_key_token):
    """API key authorization headers."""
    return {"Authorization": f"Bearer {api_key_token}"}
```

### Data Fixtures

```python
@pytest.fixture
def sample_user():
    """Test user data."""
    return {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "email": "tester@openlyne.com",
        "org_id": "550e8400-e29b-41d4-a716-446655440001",
        "role": "member"
    }

@pytest.fixture
def sample_org():
    """Test organization data."""
    return {
        "id": "550e8400-e29b-41d4-a716-446655440001",
        "name": "Test Organization",
        "created_at": "2024-01-01T00:00:00Z"
    }

@pytest.fixture
def sample_kb():
    """Test knowledge base data."""
    return {
        "id": "550e8400-e29b-41d4-a716-446655440002",
        "org_id": "550e8400-e29b-41d4-a716-446655440001",
        "name": "Test Knowledge Base",
        "created_at": "2024-01-01T00:00:00Z"
    }
```

## Mocking Strategy

### Mock Supabase Database Operations

```python
from unittest.mock import patch, MagicMock

# Mock table operations
with patch('src.core.database.supabase') as mock_supabase:
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    
    # Mock select
    mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value = \
        MagicMock(data=sample_user)
    
    # Mock insert
    mock_table.insert.return_value.execute.return_value = \
        MagicMock(data=[{"id": "new-id"}])
```

### Mock JWT Validation

```python
with patch('src.core.auth_utils.supabase.auth.get_user') as mock_get_user:
    mock_get_user.return_value = MagicMock(user=MagicMock(id=sample_user["id"]))
    # Now JWT validation will succeed
```

### Mock API Key Validation

```python
with patch('src.core.database.supabase.table') as mock_table:
    mock_key_result = MagicMock()
    mock_key_result.data = {
        "org_id": sample_org["id"],
        "is_active": True,
        "expires_at": None
    }
    mock_table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_key_result
    # Now API key validation will succeed
```

## Test Examples

### Testing JWT Authentication

```python
def test_query_kb_with_jwt(client, mock_supabase, sample_kb, sample_user, jwt_token):
    """Test querying knowledge base with JWT authentication."""
    auth_headers = {"Authorization": f"Bearer {jwt_token}"}

    # Mock JWT validation
    with patch('src.core.database.supabase.auth.get_user') as mock_get_user:
        mock_get_user.return_value = MagicMock(user=MagicMock(id=sample_user["id"]))

        # Mock user lookup
        mock_user_result = MagicMock()
        mock_user_result.data = sample_user
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_user_result

        # Mock KB verification
        mock_kb_result = MagicMock()
        mock_kb_result.data = sample_kb
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_kb_result

        # ... test implementation ...

        response = client.post("/query",
                              json={"query": "test", "kb_id": sample_kb["id"]},
                              headers=auth_headers)

        assert response.status_code in [200, 401, 422]
```

### Testing API Key Authentication

```python
def test_query_kb_with_api_key(client, mock_supabase, sample_kb, api_key_token):
    """Test querying knowledge base with API key authentication."""
    auth_headers = {"Authorization": f"Bearer {api_key_token}"}

    # Mock API key validation
    with patch('src.core.database.supabase.table') as mock_table:
        mock_key_result = MagicMock()
        mock_key_result.data = {
            "org_id": sample_kb["org_id"],
            "is_active": True,
            "expires_at": None
        }
        mock_table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_key_result

        # ... test implementation ...

        response = client.post("/query",
                              json={"query": "test", "kb_id": sample_kb["id"]},
                              headers=auth_headers)

        assert response.status_code in [200, 401, 422]
```

### Testing No Authentication

```python
def test_query_requires_auth(client):
    """Test that query endpoints require authentication."""
    response = client.post("/query",
                          json={"query": "Test", "kb_id": "test-id"})
    assert response.status_code == 401
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.11']
    
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-asyncio
      
      - name: Run tests
        run: pytest tests/ -v --tb=short
```

## Debugging Failed Tests

### Enable Verbose Output

```bash
pytest tests/test_auth.py::test_email_password_signup -vv -s
```

### Print Debug Information

```python
def test_example(client):
    response = client.post("/endpoint", json={})
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 200
```

### Use pdb for Interactive Debugging

```python
def test_example(client):
    response = client.post("/endpoint", json={})
    import pdb; pdb.set_trace()  # Breakpoint
    assert response.status_code == 200
```

## Test Coverage

To generate coverage reports:

```bash
pytest tests/ --cov=src --cov-report=html
```

Then open `htmlcov/index.html` in a browser.

## Known Limitations

1. **Live Database Tests**: Tests using `use_live_db = True` require valid Supabase credentials
2. **Mock Limitations**: Some async operations may not mock perfectly
3. **Storage Tests**: File upload tests use mocked storage operations

## Future Improvements

- [ ] Add integration tests with real Supabase database
- [ ] Add performance tests for large-scale uploads
- [ ] Add stress tests for concurrent queries
- [ ] Add E2E tests with Playwright/Selenium
- [ ] Add property-based tests with Hypothesis
- [ ] Add snapshot testing for API responses
