import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from supabase import Client, create_client

from load_tests.config import TEST_USERS_FILE, settings


def _get_supabase_client() -> Client:
    url = settings.SUPABASE_URL
    key = settings.SUPABASE_SERVICE_ROLE_KEY
    if not url or not key:
        print(
            "Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in the environment or .env file."
        )
        sys.exit(1)
    return create_client(url, key)


def _ensure_db_user(supabase: Client, user_id: str, name: str):
    """Ensure the user exists in the public.users table using the Supabase client."""
    supabase.table("users").upsert(
        {
            "id": user_id,
            "name": name,
            "role": "CUSTOMER",
        }
    ).execute()


def create_users(count: int, prefix: str):
    if count > 5000:
        print("Error: Too many users requested (max 5000).")
        sys.exit(1)

    supabase = _get_supabase_client()

    existing_users = []
    if TEST_USERS_FILE.exists():
        with open(TEST_USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            existing_users = data.get("users", [])

    if len(existing_users) >= count:
        print("\nLoad-test user provisioning complete\n")
        print(f"Requested:             {count}")
        print(f"Already existed:       {len(existing_users)}")
        print(f"Created:               0")
        print(f"Profiles ensured:      {len(existing_users)}")
        print(f"Transient retries:     0")
        print(f"Failed:                0\n")
        print(f"Creation concurrency:  {settings.LOAD_TEST_USER_CREATION_CONCURRENCY}\n")
        print(f"Saved:\n{TEST_USERS_FILE}")
        return

    password = settings.LOAD_TEST_USER_PASSWORD
    needed = count - len(existing_users)
    start_index = len(existing_users) + 1

    print(f"Creating {needed} new test users (prefix: {prefix})...")

    # Pre-fetch email to UUID mappings for fast resolution if they already exist
    email_to_id = {}
    page = 1
    while True:
        try:
            users = supabase.auth.admin.list_users(page=page, per_page=1000)
            if not users:
                break
            for u in users:
                email_to_id[u.email] = u.id
            if len(users) < 1000:
                break
            page += 1
        except Exception as e:
            print(f"Error pre-fetching users: {e}")
            break

    results = list(existing_users)
    
    stats_lock = Lock()
    stats = {
        "already_existed": len(existing_users),
        "created": 0,
        "profiles_ensured": len(existing_users),
        "transient_retries": 0,
        "failed": 0
    }

    def _create_single_user(i):
        email = f"{prefix}{i:05d}@example.com"
        name = f"Load Test User {i}"

        max_attempts = 5
        attempt = 1

        while attempt <= max_attempts:
            try:
                # Try to create user
                try:
                    res = supabase.auth.admin.create_user(
                        {"email": email, "password": password, "email_confirm": True}
                    )
                    user_id = res.user.id

                    with stats_lock:
                        stats["created"] += 1

                except Exception as e:
                    error_str = str(e).lower()
                    if "already been registered" in error_str or "already registered" in error_str:
                        user_id = email_to_id.get(email)
                        if not user_id:
                            print(f"Could not find existing user UUID for {email}")
                            with stats_lock:
                                stats["failed"] += 1
                            return None
                    else:
                        raise e  # Let the outer try-except handle transient errors

                # Ensure row in public.users using Supabase data API
                _ensure_db_user(supabase, user_id, name)
                
                with stats_lock:
                    stats["profiles_ensured"] += 1

                return {"id": user_id, "email": email}
                
            except Exception as e:
                error_str = str(e).lower()
                is_transient = any(
                    err in error_str for err in ["10035", "connectionreseterror", "timeouterror", "oserror"]
                )
                
                if is_transient and attempt < max_attempts:
                    with stats_lock:
                        stats["transient_retries"] += 1
                        
                    backoff = (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    time.sleep(backoff)
                    attempt += 1
                else:
                    print(f"Failed to create user {email}: {e}")
                    with stats_lock:
                        stats["failed"] += 1
                    return None

        return None

    # Bounded concurrent creation using thread pool
    with ThreadPoolExecutor(max_workers=settings.LOAD_TEST_USER_CREATION_CONCURRENCY) as executor:
        futures = []
        for i in range(start_index, start_index + needed):
            futures.append(executor.submit(_create_single_user, i))

        for f in futures:
            r = f.result()
            if r:
                results.append(r)

    # Save results
    TEST_USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TEST_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump({"users": results}, f, indent=2)

    print("\nLoad-test user provisioning complete\n")
    print(f"Requested:             {count}")
    print(f"Already existed:       {stats['already_existed']}")
    print(f"Created:               {stats['created']}")
    print(f"Profiles ensured:      {stats['profiles_ensured']}")
    print(f"Transient retries:     {stats['transient_retries']}")
    print(f"Failed:                {stats['failed']}\n")
    print(f"Creation concurrency:  {settings.LOAD_TEST_USER_CREATION_CONCURRENCY}\n")
    print(f"Saved:\n{TEST_USERS_FILE}")


def cleanup_users(prefix: str):
    supabase = _get_supabase_client()
    print(f"Cleaning up users with email prefix '{prefix}'...")

    deleted = 0
    page = 1
    while True:
        try:
            users = supabase.auth.admin.list_users(page=page, per_page=1000)
            if not users:
                break

            for u in users:
                if u.email and u.email.startswith(prefix):
                    supabase.auth.admin.delete_user(u.id)
                    deleted += 1

            if len(users) < 1000:
                break
            page += 1
        except Exception as e:
            print(f"Error listing users: {e}")
            break

    if TEST_USERS_FILE.exists():
        TEST_USERS_FILE.unlink()

    print(f"Deleted {deleted} test users matching prefix '{prefix}'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate load testing users.")
    parser.add_argument(
        "--count", type=int, help="Number of users to ensure exists"
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default=settings.LOAD_TEST_USER_PREFIX,
        help="Email prefix for test users",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete all test users matching the prefix",
    )

    args = parser.parse_args()

    if args.cleanup:
        cleanup_users(args.prefix)
    elif args.count:
        create_users(args.count, args.prefix)
    else:
        parser.print_help()
