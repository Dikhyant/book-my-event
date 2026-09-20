import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.main import app
from app.models.event import Event
from app.models.user import User, UserRole

ORGANIZER_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()
EVENT_ID = uuid.uuid4()

def get_mock_user(role: UserRole) -> User:
    return User(
        id=ORGANIZER_ID if role == UserRole.ORGANIZER else CUSTOMER_ID,
        name="Test User",
        role=role,
    )

def override_get_current_organizer():
    return get_mock_user(UserRole.ORGANIZER)

def override_get_current_customer():
    return get_mock_user(UserRole.CUSTOMER)

@pytest.fixture
def mock_db_session():
    return MagicMock()

@pytest.fixture
def client_organizer(mock_db_session):
    app.dependency_overrides[get_current_user] = override_get_current_organizer
    app.dependency_overrides[get_db] = lambda: mock_db_session
    yield TestClient(app)
    app.dependency_overrides.clear()

@pytest.fixture
def client_customer(mock_db_session):
    app.dependency_overrides[get_current_user] = override_get_current_customer
    app.dependency_overrides[get_db] = lambda: mock_db_session
    yield TestClient(app)
    app.dependency_overrides.clear()

@pytest.fixture
def sample_event():
    return Event(
        id=EVENT_ID,
        title="Test Event",
        description="A great event",
        location="123 Test St",
        event_date=datetime.now(timezone.utc),
        total_tickets=100,
        available_tickets=100,
        organizer_id=ORGANIZER_ID,
        version=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

def test_create_event_organizer(client_organizer, mock_db_session):
    event_data = {
        "title": "New Event",
        "description": "Details here",
        "location": "Online",
        "event_date": datetime.now(timezone.utc).isoformat(),
        "total_tickets": 50,
    }
    
    def mock_refresh(instance):
        instance.id = EVENT_ID
        instance.version = 1
        instance.created_at = datetime.now(timezone.utc)
        instance.updated_at = datetime.now(timezone.utc)
        
    mock_db_session.refresh.side_effect = mock_refresh
    
    response = client_organizer.post("/events", json=event_data)
    assert response.status_code == 201
    
    mock_db_session.add.assert_called_once()
    mock_db_session.commit.assert_called_once()
    mock_db_session.refresh.assert_called_once()

def test_create_event_customer(client_customer):
    event_data = {
        "title": "New Event",
        "event_date": datetime.now(timezone.utc).isoformat(),
        "total_tickets": 50,
    }
    response = client_customer.post("/events", json=event_data)
    assert response.status_code == 403

def test_list_events(client_customer, mock_db_session, sample_event):
    mock_query = MagicMock()
    mock_query.all.return_value = [sample_event]
    mock_db_session.query.return_value = mock_query

    response = client_customer.get("/events")
    assert response.status_code == 200
    assert len(response.json()) == 1

def test_get_event(client_customer, mock_db_session, sample_event):
    mock_db_session.get.return_value = sample_event

    response = client_customer.get(f"/events/{EVENT_ID}")
    assert response.status_code == 200
    assert response.json()["title"] == "Test Event"

def test_update_event_organizer(client_organizer, mock_db_session, sample_event):
    mock_db_session.get.return_value = sample_event
    
    # Mocking booked tickets query to return 0
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_scalar = MagicMock(return_value=0)
    mock_db_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_filter
    mock_filter.scalar = mock_scalar

    update_data = {"title": "Updated Event", "total_tickets": 150}
    response = client_organizer.patch(f"/events/{EVENT_ID}", json=update_data)
    
    assert response.status_code == 200
    mock_db_session.commit.assert_called_once()
    assert sample_event.title == "Updated Event"
    assert sample_event.total_tickets == 150
    assert sample_event.available_tickets == 150
    assert sample_event.version == 2

def test_update_event_customer(client_customer, mock_db_session):
    response = client_customer.patch(f"/events/{EVENT_ID}", json={"title": "Hack"})
    assert response.status_code == 403

def test_delete_event_organizer(client_organizer, mock_db_session, sample_event):
    mock_db_session.get.return_value = sample_event

    response = client_organizer.delete(f"/events/{EVENT_ID}")
    assert response.status_code == 204
    mock_db_session.delete.assert_called_once_with(sample_event)
    mock_db_session.commit.assert_called_once()

def test_delete_event_customer(client_customer, mock_db_session):
    response = client_customer.delete(f"/events/{EVENT_ID}")
    assert response.status_code == 403
