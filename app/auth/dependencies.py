import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.provider import AuthProvider
from app.auth.supabase import SupabaseAuthProvider
from app.db.database import get_db
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)


def get_auth_provider() -> SupabaseAuthProvider:
    return SupabaseAuthProvider()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    provider: AuthProvider = Depends(get_auth_provider),
    db: Session = Depends(get_db),
) -> User:
    """Return the `public.users` row for the authenticated JWT subject."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    subject = provider.verify_token(credentials.credentials)
    try:
        user_id = uuid.UUID(subject)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user
