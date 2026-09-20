import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.models.booking import Booking, BookingStatus
from app.models.event import Event
from app.models.notification import Notification, NotificationStatus, NotificationType
from app.models.user import User
from app.workers.tasks.booking_email import send_booking_confirmation
from app.workers.tasks.event_notification import notify_event_update

# Note: Tests assume the existence of a pytest fixture 'client' and 'db_session' in conftest.py or similar.
# Since we don't have full visibility into the fixtures, we will use mock.patch heavily.

def test_successful_booking_queues_email():
    with patch("app.services.booking_service.send_booking_confirmation.delay") as mock_delay:
        from app.services.booking_service import create_booking
        from app.schemas.booking import BookingCreate
        from unittest.mock import MagicMock
        
        db_mock = MagicMock()
        db_mock.execute.return_value.rowcount = 1
        
        booking_in = BookingCreate(event_id=uuid.uuid4(), quantity=1)
        create_booking(db=db_mock, customer_id=uuid.uuid4(), booking_in=booking_in)
        
        mock_delay.assert_called_once()


def test_failed_booking_does_not_queue_email():
    with patch("app.services.booking_service.send_booking_confirmation.delay") as mock_delay:
        from app.services.booking_service import create_booking
        from app.schemas.booking import BookingCreate
        from unittest.mock import MagicMock
        from fastapi import HTTPException
        
        db_mock = MagicMock()
        db_mock.execute.return_value.rowcount = 0
        db_mock.get.return_value = None  # event not found
        
        booking_in = BookingCreate(event_id=uuid.uuid4(), quantity=1)
        try:
            create_booking(db=db_mock, customer_id=uuid.uuid4(), booking_in=booking_in)
        except HTTPException:
            pass
            
        mock_delay.assert_not_called()


@patch("app.workers.tasks.booking_email.resend.Emails.send")
@patch("app.workers.tasks.booking_email.SessionLocal")
def test_duplicate_booking_task_does_not_create_duplicate_notifications(mock_session, mock_send):
    db = mock_session.return_value
    
    booking_id = uuid.uuid4()
    
    mock_notification = Notification(status=NotificationStatus.SENT)
    db.query.return_value.filter_by.return_value.first.return_value = mock_notification
    
    send_booking_confirmation(str(booking_id))
    
    # Should not send email again since status is SENT
    mock_send.assert_not_called()


def test_successful_event_update_queues_notification():
    with patch("app.api.routes.events.notify_event_update.delay") as mock_delay:
        from app.api.routes.events import update_event
        from app.schemas.event import EventUpdate
        from app.models.user import User, UserRole
        from app.models.event import Event
        from unittest.mock import MagicMock
        
        db_mock = MagicMock()
        mock_event = Event(id=uuid.uuid4(), organizer_id=uuid.uuid4(), version=1, total_tickets=100)
        db_mock.get.return_value = mock_event
        
        current_user = User(id=mock_event.organizer_id, role=UserRole.ORGANIZER)
        
        update_event(
            event_id=mock_event.id,
            event_update=EventUpdate(title="New Title"),
            db=db_mock,
            current_user=current_user
        )
        
        mock_delay.assert_called_once_with(str(mock_event.id), 2)


@patch("app.workers.tasks.event_notification.resend.Emails.send")
@patch("app.workers.tasks.event_notification.SessionLocal")
def test_event_update_notification_finds_all_customers(mock_session, mock_send):
    db = mock_session.return_value
    
    event_id = uuid.uuid4()
    event = Event(id=event_id, title="Test Event")
    db.get.return_value = event
    
    # Mock customers
    customer1 = User(id=uuid.uuid4(), name="Alice")
    customer2 = User(id=uuid.uuid4(), name="Bob")
    
    db.query.return_value.filter.return_value.all.side_effect = [
        [Booking(customer_id=customer1.id), Booking(customer_id=customer2.id)], # Bookings query
    ]
    
    # To mock the second query for users:
    def mock_query(model):
        m = MagicMock()
        if model == User:
            m.filter.return_value.all.return_value = [customer1, customer2]
        return m
    
    db.query.side_effect = mock_query
    
    # No existing notifications
    db.query.return_value.filter_by.return_value.first.return_value = None
    
    notify_event_update(str(event_id), 2)
    
    assert mock_send.call_count == 2


@patch("app.workers.tasks.booking_email.resend.Emails.send")
@patch("app.workers.tasks.booking_email.SessionLocal")
def test_email_failure_causes_celery_retry(mock_session, mock_send):
    db = mock_session.return_value
    
    booking_id = uuid.uuid4()
    booking = Booking(id=booking_id, event_id=uuid.uuid4(), customer_id=uuid.uuid4())
    db.get.side_effect = [booking, Event(), User()]
    
    # No existing notification
    db.query.return_value.filter_by.return_value.first.return_value = None
    
    mock_send.side_effect = Exception("Resend API error")
    
    with patch("app.workers.tasks.booking_email.send_booking_confirmation.retry") as mock_retry:
        mock_retry.side_effect = Exception("RetryTriggered")
        try:
            send_booking_confirmation(str(booking_id))
        except Exception as e:
            assert str(e) == "RetryTriggered"
            
        mock_retry.assert_called_once()
        
        
@patch("app.workers.tasks.booking_email.resend.Emails.send")
@patch("app.workers.tasks.booking_email.SessionLocal")
def test_notification_status_changes_from_pending_to_sent_on_success(mock_session, mock_send):
    db = mock_session.return_value
    
    booking_id = uuid.uuid4()
    booking = Booking(id=booking_id, event_id=uuid.uuid4(), customer_id=uuid.uuid4())
    db.get.side_effect = [booking, Event(), User()]
    
    # No existing notification
    db.query.return_value.filter_by.return_value.first.return_value = None
    
    notification = Notification(status=NotificationStatus.PENDING)
    
    # Mock db.add to just capture the notification
    def mock_add(obj):
        if isinstance(obj, Notification):
            nonlocal notification
            notification = obj
            
    db.add.side_effect = mock_add
    
    send_booking_confirmation(str(booking_id))
    
    assert notification.status == NotificationStatus.SENT
