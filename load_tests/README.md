# Event Booking System Load Testing Framework

This directory contains a reusable asyncio HTTP load-testing framework designed to test the real FastAPI API under concurrent traffic.

## Environment Variables

The load-testing framework depends on the following environment variables (can be set in the root `.env` file):

- `BASE_URL`: The URL of the FastAPI application (default: `http://localhost:8000`)
- `LOAD_TEST_USER_PASSWORD`: The password used for generated test users.
- `SUPABASE_URL`: Your Supabase project URL.
- `SUPABASE_ANON_KEY`: Your Supabase anon key (for authentication).
- `SUPABASE_SERVICE_ROLE_KEY`: Your Supabase service role key (required **only** for `create_test_users.py` to use the Admin API).
- `LOAD_TEST_USER_PREFIX`: The prefix for generated emails (default: `loadtest`).
- `DATABASE_URL`: The PostgreSQL database URL (used by `create_test_users.py` to ensure user rows exist in `public.users`).

---

## 1. Creating Test Users

The generator uses the Supabase Auth Admin API to create auto-confirmed test users safely without triggering frontend redirects or email quotas. It also ensures rows exist in `public.users`.

### How to create 1,000 users
```bash
python load_tests/create_test_users.py --count 1000
```

### How to create 5,000 users
```bash
python load_tests/create_test_users.py --count 5000
```

**Note:** The script is idempotent. Running it again with `--count 1000` will detect existing users in `test_users.json` and skip recreation.

---

## 2. Running Load Tests

### Concurrent Bookings Test
This test selects the requested number of authenticated customers and blasts `POST /bookings` concurrently.

**How to run a 3-user test:**
```bash
python load_tests/concurrent_bookings.py --event-id <EVENT_UUID> --users 3 --concurrency 3
```

**How to run a 100-user test:**
```bash
python load_tests/concurrent_bookings.py --event-id <EVENT_UUID> --users 100 --concurrency 50
```

**How to run a 1,000-user test:**
```bash
python load_tests/concurrent_bookings.py --event-id <EVENT_UUID> --users 1000 --concurrency 1000
```

**How to run a 5,000-user test:**
```bash
python load_tests/concurrent_bookings.py --event-id <EVENT_UUID> --users 5000 --concurrency 500
```

#### Understanding Concurrency vs Total Users
- **Users (`--users`)**: The total number of unique customers that will attempt to book a ticket.
- **Concurrency (`--concurrency`)**: The maximum number of simultaneous HTTP requests in flight at any given time. If you have 5000 users and 500 concurrency, the framework will send 500 requests simultaneously, queueing the rest until slots free up.

### Concurrent Event Updates Test
This tests `PATCH /events/{event_id}`. Since this requires an organizer, you must provide valid organizer credentials.

```bash
python load_tests/concurrent_event_updates.py --event-id <EVENT_UUID> --requests 100 --concurrency 20 --email organizer@example.com --password mysecret
```

---

## 3. Interpreting Metrics

The runner will output a summary block:
- **Total Requests**: The number of attempts made.
- **Requests per second**: The throughput of your API.
- **Status 2xx**: Successful responses.
- **Status 409**: Insufficient ticket errors (expected in concurrent booking scenarios where demand exceeds supply).
- **Latency Distribution (min, max, avg, p50, p95, p99)**: Shows the responsiveness of the API under load.
- **Final Available Tickets**: The database's authoritative ticket count after the test completes.
- **Oversold Tickets**: Must be 0. If it is greater than 0, your database locking mechanism failed.

**Verifying tickets:** You do not need to manually calculate tickets. The script automatically reads the final `available_tickets` from `GET /events/{event_id}` and reports it.

---

## 4. Cleanup

To delete all generated test users (identified by their email prefix):

```bash
python load_tests/create_test_users.py --cleanup --prefix loadtest
```
*(Warning: Ensure the prefix is correct so you do not delete real users.)*

---

> [!WARNING]
> **Production Safety**
> This tool is strictly for local, development, or staging environments. Never point it at an unrelated production system or a third-party API, as it generates massive concurrent HTTP traffic that resembles a Denial of Service (DoS) attack.
