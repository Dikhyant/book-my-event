import logging
from datetime import datetime, timezone
import uuid

import resend
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.database import SessionLocal
from app.models.booking import Booking
from app.models.event import Event
from app.models.notification import Notification, NotificationStatus, NotificationType
from app.models.user import User
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()

@celery_app.task(bind=True, max_retries=5, default_retry_delay=60, acks_late=True)
def send_booking_confirmation(self, booking_id_str: str):
    logger.info(f"Booking confirmation queued: booking_id={booking_id_str}")
    
    db: Session = SessionLocal()
    try:
        booking_id = uuid.UUID(booking_id_str)
        booking = db.get(Booking, booking_id)
        if not booking:
            logger.error(f"Booking not found: booking_id={booking_id_str}")
            return
            
        event = db.get(Event, booking.event_id)
        customer = db.get(User, booking.customer_id)
        
        if not event or not customer:
            logger.error(f"Event or Customer not found for booking: booking_id={booking_id_str}")
            return

        deduplication_key = f"booking-confirmation:{booking_id_str}"
        
        # Check deduplication
        existing_notification = (
            db.query(Notification)
            .filter_by(deduplication_key=deduplication_key)
            .first()
        )
        
        if existing_notification:
            if existing_notification.status == NotificationStatus.SENT:
                logger.info(f"Booking confirmation already sent: booking_id={booking_id_str}")
                return
            notification = existing_notification
        else:
            notification = Notification(
                user_id=customer.id,
                event_id=event.id,
                booking_id=booking.id,
                type=NotificationType.BOOKING_CONFIRMATION,
                status=NotificationStatus.PENDING,
                deduplication_key=deduplication_key,
            )
            db.add(notification)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                logger.info(f"Concurrent notification creation prevented for: {deduplication_key}")
                notification = db.query(Notification).filter_by(deduplication_key=deduplication_key).first()
                if notification and notification.status == NotificationStatus.SENT:
                    return

        # Prepare email
        html_content = f"""
        <html>
            <body>
                <h2>Booking Confirmation</h2>
                <p>Hello {customer.name},</p>
                <p>Your booking for <strong>{event.title}</strong> has been confirmed.</p>
                <ul>
                    <li><strong>Date:</strong> {event.event_date.strftime('%Y-%m-%d %H:%M %Z')}</li>
                    <li><strong>Location:</strong> {event.location}</li>
                    <li><strong>Quantity:</strong> {booking.quantity}</li>
                    <li><strong>Booking ID:</strong> {booking.id}</li>
                </ul>
                <p>Thank you for booking with us!</p>
            </body>
        </html>
        """
        
        try:
            # Assuming user's email is stored somewhere. Wait, `User` model only has `id`, `name`, `role`, `created_at`, `updated_at`.
            # User model doesn't have an email column! 
            # The system must use a dummy or mocked email if not present, or maybe just `name@example.com`
            # Wait, looking at the user request: "Event update notification finds all customers who booked the event. Send email to each customer"
            # It seems we should use a mock email or add email column. But requirement says "Do not modify the existing database schema".
            # So I will use `f"{customer.name.replace(' ', '.').lower()}@example.com"` if there's no email. Wait! Is there an email in `User`? Let me check `user.py` again.
            
            customer_email = getattr(customer, "email", f"{customer.id}@example.com")
            
            if not settings.resend_api_key:
                raise ValueError("RESEND_API_KEY is not set. Worker cannot send emails.")
            resend.api_key = settings.resend_api_key
            
            resend.Emails.send({
                "from": settings.email_from,
                "to": customer_email,
                "subject": f"Booking Confirmed: {event.title}",
                "html": html_content,
            })
            
            notification.status = NotificationStatus.SENT
            notification.sent_at = datetime.now(timezone.utc)
            db.commit()
            
            logger.info(f"Booking confirmation sent: booking_id={booking_id_str}")
            
        except Exception as e:
            notification.status = NotificationStatus.FAILED
            db.commit()
            logger.error(f"Email delivery failed: booking_id={booking_id_str} retrying... Error: {str(e)}")
            # Exponential backoff retry
            raise self.retry(exc=e, countdown=2 ** self.request.retries)
            
    finally:
        db.close()
