"""Pytest configuration and fixtures."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from main import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def use_live_db():
    """Fixture to indicate whether to use live database for testing."""
    return True  # Set to True to use live Supabase database


@pytest.fixture
def mock_supabase(use_live_db):
    """Mock Supabase client for testing - conditionally use live DB."""
    if use_live_db:
        # Don't mock - use real Supabase connection
        from src.core.database import supabase
        yield supabase
    else:
        # Use mocks for isolated testing
        with patch('src.core.database.supabase') as mock_supabase, \
             patch('src.api.v1.auth.supabase') as mock_auth_supabase, \
             patch('src.api.v1.kb.supabase') as mock_kb_supabase, \
             patch('src.api.v1.upload.supabase') as mock_upload_supabase, \
             patch('src.api.v1.query.supabase') as mock_query_supabase:

            # Configure all supabase mocks to return the same mock
            for mock in [mock_supabase, mock_auth_supabase, mock_kb_supabase, mock_upload_supabase, mock_query_supabase]:
                mock.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock()
                mock.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock()
                mock.table.return_value.insert.return_value.execute.return_value = MagicMock()
                mock.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
                mock.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock()
                mock.auth.sign_up.return_value = MagicMock()
                mock.auth.sign_in_with_password.return_value = MagicMock()
                mock.auth.get_user.return_value = MagicMock()

            yield mock_supabase


@pytest.fixture
def sample_user():
    """Sample user data for testing."""
    return {
        "id": "550e8400-e29b-41d4-a716-446655440000",  # Valid UUID
        "email": "tester@openlyne.com",
        "org_id": "550e8400-e29b-41d4-a716-446655440001",  # Valid UUID
        "role": "member"
    }


@pytest.fixture
def sample_org():
    """Sample organization data for testing."""
    return {
        "id": "550e8400-e29b-41d4-a716-446655440001",  # Valid UUID
        "name": "Test Organization",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z"
    }


@pytest.fixture
def sample_kb():
    """Sample knowledge base data for testing."""
    return {
        "id": "550e8400-e29b-41d4-a716-446655440002",  # Valid UUID
        "org_id": "550e8400-e29b-41d4-a716-446655440001",  # Valid UUID
        "name": "Test Knowledge Base",
        "created_at": "2024-01-01T00:00:00Z"
    }


@pytest.fixture
def auth_headers(sample_user):
    """Mock authorization headers."""
    return {"Authorization": f"Bearer mock-token-{sample_user['id']}"}


@pytest.fixture
def test_org_id():
    """Test organization ID that exists in live database."""
    # This should be a real org ID from your Supabase database
    # You'll need to create this org first or get it from existing data
    return "550e8400-e29b-41d4-a716-446655440001"


@pytest.fixture
def test_kb_id():
    """Test knowledge base ID that exists in live database."""
    # This should be a real KB ID from your Supabase database
    # You'll need to create this KB first or get it from existing data
    return "550e8400-e29b-41d4-a716-446655440002"


@pytest.fixture
def mock_auth_user(mock_supabase, sample_user):
    """Mock authenticated user."""
    mock_user = MagicMock()
    mock_user.id = sample_user["id"]
    mock_user.email = sample_user["email"]
    mock_user.model_dump.return_value = {
        "id": sample_user["id"],
        "email": sample_user["email"]
    }

    mock_response = MagicMock()
    mock_response.user = mock_user
    mock_supabase.auth.get_user.return_value = mock_response
    return mock_user


@pytest.fixture
def mock_user_table(mock_supabase, sample_user):
    """Mock users table query."""
    mock_result = MagicMock()
    mock_result.data = sample_user
    mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_result
    return mock_result