import argparse
import asyncio
import time
import httpx

from load_tests.auth import authenticate_user
from load_tests.client import BoundedHttpClient
from load_tests.config import settings
from load_tests.runner import display_metrics


async def run_event_update_test(
    event_id: str, requests: int, concurrency: int, email: str, password: str
):
    print(f"Authenticating organizer {email}...")
    
    async with httpx.AsyncClient() as client:
        token = await authenticate_user(client, email, password)
        
    if not token:
        print("Failed to authenticate organizer. Aborting.")
        return

    print(f"Starting event update test for event {event_id} with {requests} requests (concurrency: {concurrency})...")
    
    http_client = BoundedHttpClient(concurrency_limit=concurrency)
    url = f"/events/{event_id}"

    tasks = []
    for i in range(requests):
        # Modify a safe field. We'll alternate the description slightly to avoid identical payloads if that matters,
        # but the requirement just says "modify a safe test field such as description/title"
        payload = {"description": f"Load test description update {i}"}
        tasks.append(
            http_client.patch(
                url=url,
                token=token,
                json_data=payload,
            )
        )

    start_time = time.perf_counter()
    results = await asyncio.gather(*tasks)
    total_time = time.perf_counter() - start_time

    await http_client.close()

    display_metrics(results, total_time)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Concurrent event update load test.")
    parser.add_argument("--event-id", type=str, required=True, help="UUID of the event to update")
    parser.add_argument("--requests", type=int, required=True, help="Number of update requests to send")
    parser.add_argument("--concurrency", type=int, required=True, help="Max concurrent HTTP requests")
    parser.add_argument("--email", type=str, required=True, help="Organizer email")
    parser.add_argument("--password", type=str, required=True, help="Organizer password")
    
    args = parser.parse_args()
    
    asyncio.run(
        run_event_update_test(
            args.event_id, args.requests, args.concurrency, args.email, args.password
        )
    )
