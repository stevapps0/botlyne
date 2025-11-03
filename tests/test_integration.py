"""Integration tests using live Supabase database."""
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    """FastAPI test client for integration tests."""
    return TestClient(app)


def test_full_etl_pipeline_integration(client):
    """Integration test for the complete ETL pipeline with live database."""
    # This test would require setting up real test data in Supabase
    # For now, it's a placeholder showing the structure

    # 1. Create organization
    # 2. Create user and add to org
    # 3. Create knowledge base
    # 4. Upload file/URL
    # 5. Query knowledge base
    # 6. Verify results

    # Example structure:
    """
    # Create test organization
    org_response = client.post("/auth/orgs", json={"name": "Integration Test Org"})
    assert org_response.status_code == 200
    org_id = org_response.json()["id"]

    # Create test user (would need real auth token)
    # Upload test document
    # Query and verify AI response
    """

    # For now, just test that the API is responsive
    health_response = client.get("/health")
    assert health_response.status_code == 200
    assert health_response.json()["status"] == "healthy"


def test_database_connection():
    """Test that we can connect to the live Supabase database."""
    from src.core.database import supabase

    # Test basic connectivity
    try:
        # Try a simple query that should work even with empty tables
        result = supabase.table("organizations").select("count", count="exact").execute()
        # If we get here without exception, connection is working
        assert True
    except Exception as e:
        # If tables don't exist yet, that's expected
        if "relation" in str(e).lower():
            assert True  # Database connection works, just no tables yet
        else:
            raise  # Re-raise unexpected errors


def test_schema_setup():
    """Test that the database schema is properly set up."""
    from src.core.database import supabase

    # Check if our tables exist by trying to query them
    tables_to_check = ["organizations", "users", "knowledge_bases", "files", "documents"]

    for table_name in tables_to_check:
        try:
            # Try to select count from each table
            result = supabase.table(table_name).select("count", count="exact").limit(1).execute()
            print(f"✅ Table '{table_name}' exists")
        except Exception as e:
            if "relation" in str(e).lower():
                print(f"❌ Table '{table_name}' does not exist")
                raise AssertionError(f"Required table '{table_name}' is missing from database")
            else:
                # Other errors (permissions, etc.) - re-raise
                raise