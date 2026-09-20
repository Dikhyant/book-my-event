from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from jose import jwt

from unittest.mock import MagicMock
from uuid import UUID

from app.auth.dependencies import get_auth_provider, get_current_user
from app.auth.supabase import SupabaseAuthProvider
from app.core.config import Settings
from app.db.database import get_db
from app.models.user import User, UserRole

ISSUER = "https://test.supabase.co/auth/v1"
SECRET = "test-supabase-jwt-secret"
USER_ID = str(uuid4())


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://localhost/test",
        supabase_url="https://test.supabase.co",
        supabase_jwt_secret=SECRET,
    )


def _token(*, exp_delta: timedelta = timedelta(minutes=5), secret: str = SECRET, **claims) -> str:
    payload = {
        "sub": USER_ID,
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": datetime.now(timezone.utc) + exp_delta,
        "role": "authenticated",
        **claims,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def provider() -> SupabaseAuthProvider:
    return SupabaseAuthProvider(_settings())


@pytest.fixture
def client(provider: SupabaseAuthProvider) -> TestClient:
    mock_db = MagicMock()
    mock_db.get.return_value = User(
        id=UUID(USER_ID),
        name="Test User",
        role=UserRole.CUSTOMER,
    )

    app = FastAPI()
    app.dependency_overrides[get_auth_provider] = lambda: provider
    app.dependency_overrides[get_db] = lambda: mock_db

    @app.get("/protected")
    def protected(user: User = Depends(get_current_user)) -> dict[str, str]:
        return {"user_id": str(user.id)}

    return TestClient(app)


def test_valid_token_returns_sub(provider: SupabaseAuthProvider) -> None:
    assert provider.verify_token(_token()) == USER_ID


def test_jwt_role_claim_is_ignored(provider: SupabaseAuthProvider) -> None:
    token = _token(role="ORGANIZER")
    assert provider.verify_token(token) == USER_ID


def test_malformed_token_is_rejected(provider: SupabaseAuthProvider) -> None:
    with pytest.raises(HTTPException) as exc:
        provider.verify_token("not-a-jwt")
    assert exc.value.status_code == 401


def test_expired_token_is_rejected(provider: SupabaseAuthProvider) -> None:
    with pytest.raises(HTTPException) as exc:
        provider.verify_token(_token(exp_delta=timedelta(minutes=-5)))
    assert exc.value.status_code == 401


def test_invalid_signature_is_rejected(provider: SupabaseAuthProvider) -> None:
    with pytest.raises(HTTPException) as exc:
        provider.verify_token(_token(secret="wrong-secret"))
    assert exc.value.status_code == 401


def test_missing_bearer_token_returns_401(client: TestClient) -> None:
    response = client.get("/protected")
    assert response.status_code == 401


def test_valid_bearer_token_returns_user_id(client: TestClient) -> None:
    response = client.get("/protected", headers={"Authorization": f"Bearer {_token()}"})
    assert response.status_code == 200
    assert response.json() == {"user_id": USER_ID}


def test_malformed_bearer_token_returns_401(client: TestClient) -> None:
    response = client.get("/protected", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401
