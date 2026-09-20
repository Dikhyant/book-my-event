from functools import lru_cache
from typing import NoReturn

import httpx
from fastapi import HTTPException, status
from jose import ExpiredSignatureError, JWTError, jwt

from app.auth.provider import AuthProvider
from app.core.config import Settings, get_settings

_ALLOWED_ALGORITHMS = frozenset({"ES256", "RS256", "HS256"})
_AUTHENTICATED_AUDIENCE = "authenticated"


def _unauthorized() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


@lru_cache(maxsize=8)
def _load_jwks(supabase_url: str) -> dict:
    url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    response = httpx.get(url, timeout=10.0)
    response.raise_for_status()
    return response.json()


class SupabaseAuthProvider(AuthProvider):
    """Verifies Supabase Auth JWTs. Application roles are not read from the token."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def verify_token(self, token: str) -> str:
        if not token or not token.strip():
            _unauthorized()

        try:
            header = jwt.get_unverified_header(token)
        except JWTError:
            _unauthorized()

        key = self._verification_key(header)
        algorithm = header.get("alg")
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=_AUTHENTICATED_AUDIENCE,
                issuer=self._issuer(),
                options={
                    "require_aud": True,
                    "require_exp": True,
                    "require_sub": True,
                },
            )
        except ExpiredSignatureError:
            _unauthorized()
        except JWTError:
            _unauthorized()

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            _unauthorized()
        return subject

    def _issuer(self) -> str:
        url = self._settings.supabase_url.strip()
        if not url:
            _unauthorized()
        return f"{url.rstrip('/')}/auth/v1"

    def _verification_key(self, header: dict) -> str | dict:
        algorithm = header.get("alg")
        if algorithm not in _ALLOWED_ALGORITHMS:
            _unauthorized()

        if algorithm == "HS256":
            secret = self._settings.supabase_jwt_secret
            if not secret:
                _unauthorized()
            return secret

        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            _unauthorized()

        key = self._jwk_for_kid(kid)
        if key is None:
            _load_jwks.cache_clear()
            key = self._jwk_for_kid(kid)
        if key is None:
            _unauthorized()
        return key

    def _jwk_for_kid(self, kid: str) -> dict | None:
        try:
            jwks = _load_jwks(self._settings.supabase_url.rstrip("/"))
        except (httpx.HTTPError, ValueError, TypeError):
            return None
        keys = jwks.get("keys") if isinstance(jwks, dict) else None
        if not isinstance(keys, list):
            return None
        for key in keys:
            if isinstance(key, dict) and key.get("kid") == kid:
                return key
        return None


    def register(self, email: str, password: str) -> dict:
        url = f"{self._settings.supabase_url.rstrip('/')}/auth/v1/signup"

        response = httpx.post(
            url,
            headers={
                "apikey": self._settings.supabase_anon_key,
                "Content-Type": "application/json",
            },
            json={
                "email": email,
                "password": password,
            },
            timeout=10.0,
        )

        if response.is_error:
            try:
                detail = response.json().get("msg", "Registration failed")
            except ValueError:
                detail = "Registration failed"

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=detail,
            )

        data = response.json()

        user = data.get("user")

        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Supabase did not return a user",
            )

        return {
            "user_id": user["id"],
            "access_token": data.get("access_token"),
            "email_confirmation_required": not bool(
                data.get("access_token")
            ),
        }

    def login(self, email: str, password: str) -> dict:
        url = (
            f"{self._settings.supabase_url.rstrip('/')}"
            "/auth/v1/token?grant_type=password"
        )

        response = httpx.post(
            url,
            headers={
                "apikey": self._settings.supabase_anon_key,
                "Content-Type": "application/json",
            },
            json={
                "email": email,
                "password": password,
            },
            timeout=10.0,
        )

        if response.is_error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        data = response.json()

        user = data.get("user")
        access_token = data.get("access_token")

        if not user or not access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication response",
            )

        return {
            "user_id": user["id"],
            "access_token": access_token,
        }
