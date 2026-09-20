import argparse
import asyncio
import time

from load_tests.auth import get_test_users_with_tokens
from load_tests.client import BoundedHttpClient
from load_tests.config import settings
from load_tests.runner import display_metrics


async def run_booking_test(event_id: str, num_users: int, concurrency: int):
    print(f"Loading and authenticating {num_users} users...")
    users = await get_test_users_with_tokens(num_users)
    if not users:
        print("No users authenticated. Aborting.")
        return

    print(f"Starting booking test for event {event_id} with {len(users)} users (concurrency: {concurrency})...")
    client = BoundedHttpClient(concurrency_limit=concurrency)
    
    url = "/bookings"
    payload = {"event_id": event_id, "quantity": 1}

    # Prepare tasks
    tasks = []
    for user in users:
        tasks.append(
            client.post(
                url=url,
                token=user["token"],
                json_data=payload,
                use_idempotency=True,
            )
        )

    start_time = time.perf_counter()
    results = await asyncio.gather(*tasks)
    total_time = time.perf_counter() - start_time

    await client.close()

    # Verify final tickets by logging in as one of the users (they are customers, so they can get event details)
    # Actually, any authenticated user can view events
    final_tickets = None
    oversold = None
    if users:
        verify_client = BoundedHttpClient(concurrency_limit=1)
        res = await verify_client.get(f"/events/{event_id}", users[0]["token"])
        await verify_client.close()
        
        if res.is_success:
            # We need to manually do the request to parse JSON for this one-off
            pass
            
    # Do manual verification with standard httpx
    async with httpx.AsyncClient(base_url=settings.BASE_URL) as standard_client:
        r = await standard_client.get(f"/events/{event_id}", headers={"Authorization": f"Bearer {users[0]['token']}"})
        if r.status_code == 200:
            event_data = r.json()
            final_tickets = event_data.get("available_tickets")
            
            successful_requests = sum(1 for res in results if res.is_success)
            expected_remaining = event_data.get("total_tickets", 0) - successful_requests
            if final_tickets is not None:
                oversold = 0 if final_tickets >= 0 else abs(final_tickets)
                # Note: true oversold would mean booked > total_tickets

    stats = {}
    if final_tickets is not None:
        stats["Final Available Tickets"] = final_tickets
    if oversold is not None:
        stats["Oversold Tickets"] = oversold
        
    display_metrics(results, total_time, additional_stats=stats)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Concurrent booking load test.")
    parser.add_argument("--event-id", type=str, required=True, help="UUID of the event to book")
    parser.add_argument("--users", type=int, required=True, help="Number of users to simulate")
    parser.add_argument("--concurrency", type=int, required=True, help="Max concurrent HTTP requests")
    
    args = parser.parse_args()
    
    import httpx  # Late import for the one-off request
    asyncio.run(run_booking_test(args.event_id, args.users, args.concurrency))
