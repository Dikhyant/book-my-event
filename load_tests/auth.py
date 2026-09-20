import asyncio
import json
from typing import Optional

import httpx

from load_tests.config import TEST_USERS_FILE, settings

# Cache mapping user id to access token
_token_cache: dict[str, str] = {}


async def authenticate_user(
    client: httpx.AsyncClient, email: str, password: str
) -> Optional[str]:
    """Authenticate a user against Supabase Auth using password grant type."""
    url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/token?grant_type=password"
    try:
        response = await client.post(
            url,
            headers={
                "apikey": settings.SUPABASE_ANON_KEY,
                "Content-Type": "application/json",
            },
            json={"email": email, "password": password},
            timeout=10.0,
        )
        if response.is_success:
            data = response.json()
            return data.get("access_token")
        else:
            return None
    except Exception:
        return None


async def get_test_users_with_tokens(
    required_count: int,
) -> list[dict[str, str]]:
    """
    Load test users from test_users.json and authenticate them concurrently.
    Uses caching to avoid re-authenticating.
    """
    if not TEST_USERS_FILE.exists():
        raise FileNotFoundError(
            f"{TEST_USERS_FILE} not found. Run create_test_users.py first."
        )

    with open(TEST_USERS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    users = data.get("users", [])
    if len(users) < required_count:
        raise ValueError(
            f"Not enough users in {TEST_USERS_FILE}. "
            f"Found {len(users)}, need {required_count}. "
            "Run create_test_users.py to generate more."
        )

    users_to_use = users[:required_count]
    results = []

    # Bounded concurrency for authentication to avoid rate limiting
    auth_semaphore = asyncio.Semaphore(10)

    async def _auth_task(client: httpx.AsyncClient, user: dict):
        user_id = user["id"]
        email = user["email"]
        
        # Check cache
        if user_id in _token_cache:
            return {"id": user_id, "email": email, "token": _token_cache[user_id]}

        async with auth_semaphore:
            token = await authenticate_user(
                client, email, settings.LOAD_TEST_USER_PASSWORD
            )
            if token:
                _token_cache[user_id] = token
                return {"id": user_id, "email": email, "token": token}
            else:
                print(f"Failed to authenticate user {email}")
                return None

    async with httpx.AsyncClient(timeout=settings.DEFAULT_TIMEOUT) as client:
        tasks = [_auth_task(client, user) for user in users_to_use]
        auth_results = await asyncio.gather(*tasks)

    for r in auth_results:
        if r is not None:
            results.append(r)

    if len(results) < required_count:
        print(f"Warning: Only authenticated {len(results)}/{required_count} users successfully.")
        
    return results
