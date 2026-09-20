import logging
from datetime import datetime, timezone
import uuid

import resend
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.database import SessionLocal
from app.models.booking import Booking, BookingStatus
from app.models.event import Event
from app.models.notification import Notification, NotificationStatus, NotificationType
from app.models.user import User
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()

resend.api_key = settings.resend_api_key

@celery_app.task(bind=True, max_retries=5, default_retry_delay=60, acks_late=True)
def notify_event_update(self, event_id_str: str, event_version: int):
    logger.info(f"Event update notification started: event_id={event_id_str} version={event_version}")
    
    db: Session = SessionLocal()
    try:
        event_id = uuid.UUID(event_id_str)
        event = db.get(Event, event_id)
        if not event:
            logger.error(f"Event not found: event_id={event_id_str}")
            return
            
        # Find all customers who booked the event
        bookings = (
            db.query(Booking)
            .filter(Booking.event_id == event_id, Booking.status == BookingStatus.CONFIRMED)
            .all()
        )
        
        customer_ids = {b.customer_id for b in bookings}
        customers = db.query(User).filter(User.id.in_(customer_ids)).all()
        
        for customer in customers:
            deduplication_key = f"event-update:{event_id_str}:{event_version}:{customer.id}"
            
            existing_notification = (
                db.query(Notification)
                .filter_by(deduplication_key=deduplication_key)
                .first()
            )
            
            if existing_notification:
                if existing_notification.status == NotificationStatus.SENT:
                    continue
                notification = existing_notification
            else:
                notification = Notification(
                    user_id=customer.id,
                    event_id=event.id,
                    type=NotificationType.EVENT_UPDATE,
                    status=NotificationStatus.PENDING,
                    deduplication_key=deduplication_key,
                )
                db.add(notification)
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    notification = db.query(Notification).filter_by(deduplication_key=deduplication_key).first()
                    if notification and notification.status == NotificationStatus.SENT:
                        continue
            
            # Prepare email
            html_content = f"""
            <html>
                <body>
                    <h2>Event Update: {event.title}</h2>
                    <p>Hello {customer.name},</p>
                    <p>There has been an update to an event you are attending.</p>
                    <ul>
                        <li><strong>Event:</strong> {event.title} (ID: {event.id})</li>
                        <li><strong>Date:</strong> {event.event_date.strftime('%Y-%m-%d %H:%M %Z')}</li>
                        <li><strong>Location:</strong> {event.location}</li>
                        <li><strong>Description:</strong> {event.description or 'No description provided.'}</li>
                    </ul>
                    <p>Thank you for using our platform!</p>
                </body>
            </html>
            """
            
            customer_email = getattr(customer, "email", f"{customer.id}@example.com")
            
            try:
                resend.Emails.send({
                    "from": settings.email_from,
                    "to": customer_email,
                    "subject": f"Event Update: {event.title}",
                    "html": html_content,
                })
                
                notification.status = NotificationStatus.SENT
                notification.sent_at = datetime.now(timezone.utc)
                db.commit()
                
                logger.info(f"Event update notification sent: event_id={event_id_str} user_id={customer.id}")
                
            except Exception as e:
                notification.status = NotificationStatus.FAILED
                db.commit()
                logger.error(f"Email delivery failed: user_id={customer.id} retrying... Error: {str(e)}")
                raise self.retry(exc=e, countdown=2 ** self.request.retries)
            
    finally:
        db.close()
