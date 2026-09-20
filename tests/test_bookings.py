import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.db.database import SessionLocal, get_db
from app.main import app
from app.models.booking import Booking, BookingStatus
from app.models.event import Event
from app.models.user import User, UserRole

ORGANIZER_ID = uuid.UUID("6ccbc16c-f726-4256-9f0e-4368a2cd3418")
CUSTOMER_ID = uuid.UUID("47d5a9d7-8bb1-46da-b391-fd4c555e1041")


def get_mock_user(role: UserRole, user_id: uuid.UUID = None) -> User:
    return User(
        id=user_id or (ORGANIZER_ID if role == UserRole.ORGANIZER else CUSTOMER_ID),
        name="Test User",
        role=role,
    )


def override_get_current_organizer():
    return get_mock_user(UserRole.ORGANIZER)


def override_get_current_customer():
    return get_mock_user(UserRole.CUSTOMER)


def override_get_current_customer_custom(user_id: uuid.UUID):
    return lambda: get_mock_user(UserRole.CUSTOMER, user_id=user_id)


@pytest.fixture
def client_customer_real_db():
    app.dependency_overrides[get_current_user] = override_get_current_customer
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_organizer_real_db():
    app.dependency_overrides[get_current_user] = override_get_current_organizer
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_organizer_cannot_create_booking(client_organizer_real_db):
    response = client_organizer_real_db.post(
        "/bookings",
        json={"event_id": str(uuid.uuid4()), "quantity": 1},
    )
    assert response.status_code == 403


def test_customer_cannot_book_invalid_quantity(client_customer_real_db):
    response = client_customer_real_db.post(
        "/bookings",
        json={"event_id": str(uuid.uuid4()), "quantity": 0},
    )
    assert response.status_code == 422

    response = client_customer_real_db.post(
        "/bookings",
        json={"event_id": str(uuid.uuid4()), "quantity": -5},
    )
    assert response.status_code == 422


def test_customer_cannot_book_invalid_event(client_customer_real_db):
    response = client_customer_real_db.post(
        "/bookings",
        json={"event_id": str(uuid.uuid4()), "quantity": 1},
    )
    assert response.status_code == 404


def test_concurrent_booking_oversell_protection(client_customer_real_db):
    db = SessionLocal()
    
    event_id = uuid.uuid4()
    test_event = Event(
        id=event_id,
        title="Concurrency Test Event",
        event_date=datetime.now(timezone.utc),
        total_tickets=10,
        available_tickets=10,
        organizer_id=ORGANIZER_ID,
    )
    db.add(test_event)
    db.commit()

    try:
        successful_responses = []
        failed_responses = []

        def make_booking_request(i):
            response = client_customer_real_db.post(
                "/bookings",
                json={"event_id": str(event_id), "quantity": 1},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
            return response

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_booking_request, i) for i in range(20)]
            for future in futures:
                resp = future.result()
                if resp.status_code == 201:
                    successful_responses.append(resp)
                elif resp.status_code == 409:
                    failed_responses.append(resp)

        assert len(successful_responses) == 10
        assert len(failed_responses) == 10

        db.refresh(test_event)
        assert test_event.available_tickets == 0
        
        bookings_count = db.query(Booking).filter(Booking.event_id == event_id).count()
        assert bookings_count == 10

    finally:
        db.query(Booking).filter(Booking.event_id == event_id).delete()
        db.delete(test_event)
        db.commit()
        db.close()


def test_idempotency(client_customer_real_db):
    db = SessionLocal()
    
    event_id = uuid.uuid4()
    test_event = Event(
        id=event_id,
        title="Idempotency Test Event",
        event_date=datetime.now(timezone.utc),
        total_tickets=100,
        available_tickets=100,
        organizer_id=ORGANIZER_ID,
    )
    db.add(test_event)
    db.commit()

    try:
        idem_key = str(uuid.uuid4())
        
        # Request 1
        resp1 = client_customer_real_db.post(
            "/bookings",
            json={"event_id": str(event_id), "quantity": 2},
            headers={"Idempotency-Key": idem_key}
        )
        assert resp1.status_code == 201
        
        # Request 2 with same key
        resp2 = client_customer_real_db.post(
            "/bookings",
            json={"event_id": str(event_id), "quantity": 2},
            headers={"Idempotency-Key": idem_key}
        )
        assert resp2.status_code == 201
        
        # Verify same booking returned
        assert resp1.json()["id"] == resp2.json()["id"]
        
        # Verify db tickets
        db.refresh(test_event)
        assert test_event.available_tickets == 98
        
        # Request 3 with different key
        resp3 = client_customer_real_db.post(
            "/bookings",
            json={"event_id": str(event_id), "quantity": 2},
            headers={"Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp3.status_code == 201
        assert resp1.json()["id"] != resp3.json()["id"]
        
        db.refresh(test_event)
        assert test_event.available_tickets == 96
        
    finally:
        db.query(Booking).filter(Booking.event_id == event_id).delete()
        db.delete(test_event)
        db.commit()
        db.close()
