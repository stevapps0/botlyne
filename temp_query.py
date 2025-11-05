from src.core.database import supabase

# API key is stored as plain text in key_hash field
api_key = "sk-RTcxfT582oGQlTWpHgNc5tAdA9WeLU6d"

# Query the API key record
key_data = supabase.table("api_keys").select("*").eq("key_hash", api_key).single().execute()

if key_data.data:
    print("API Key Record:")
    print(f"ID: {key_data.data['id']}")
    print(f"Org ID: {key_data.data['org_id']}")
    print(f"Name: {key_data.data['name']}")
    print(f"Active: {key_data.data['is_active']}")

    # Get organization details
    org_data = supabase.table("organizations").select("*").eq("id", key_data.data['org_id']).single().execute()
    if org_data.data:
        print("\nOrganization:")
        print(f"ID: {org_data.data['id']}")
        print(f"Name: {org_data.data['name']}")
        print(f"Description: {org_data.data.get('description')}")
        print(f"Team Size: {org_data.data.get('team_size')}")

    # Get users in this org
    users_data = supabase.table("users").select("*").eq("org_id", key_data.data['org_id']).execute()
    if users_data.data:
        print("\nUsers in Organization:")
        for user in users_data.data:
            print(f"ID: {user['id']}")
            print(f"Role: {user.get('role')}")
            print(f"Email: {user.get('email')}")
            print(f"Name: {user.get('first_name')} {user.get('last_name')}")
            print("---")
else:
    print("API key not found")