from fastapi import FastAPI

from app.api.routes.auth import router as auth_router
from app.api.routes.health import router as health_router
from app.models import Booking, Event, User

app = FastAPI(
    title="Event Booking System",
    description="Role-based event booking API mapped to an existing PostgreSQL schema.",
    docs_url="/docs",
)

app.include_router(health_router)
app.include_router(auth_router)

# Imported so mappings are registered with SQLAlchemy. Schema is never created here.
_ = (User, Event, Booking)
