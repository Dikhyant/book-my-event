import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.auth.dependencies import (
    get_auth_provider,
    get_current_user,
)
from app.auth.supabase import SupabaseAuthProvider
from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import UserResponse


router = APIRouter(prefix="/auth", tags=["Authentication"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    user: UserResponse


@router.post("/register", response_model=AuthResponse)
def register(
    request: RegisterRequest,
    db: Session = Depends(get_db),
    auth_provider: SupabaseAuthProvider = Depends(get_auth_provider),
):
    try:
        auth_result = auth_provider.register(
            email=request.email,
            password=request.password,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    user = User(
        id=auth_result["user_id"],
        name=request.name,
    )

    db.add(user)

    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        user = db.query(User).filter(User.id == auth_result["user_id"]).first()
        if not user:
            logging.exception("IntegrityError on user insert, but user not found:")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User profile could not be created",
            )
    except Exception as exc:
        logging.exception("Database insert for user failed:")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User profile could not be created",
        )

    return AuthResponse(
        access_token=auth_result["access_token"],
        user=user,
    )


@router.post("/login", response_model=AuthResponse)
def login(
    request: LoginRequest,
    db: Session = Depends(get_db),
    auth_provider: SupabaseAuthProvider = Depends(get_auth_provider),
):
    try:
        auth_result = auth_provider.login(
            email=request.email,
            password=request.password,
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    user = (
        db.query(User)
        .filter(User.id == auth_result["user_id"])
        .first()
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found",
        )

    return AuthResponse(
        access_token=auth_result["access_token"],
        user=user,
    )


@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: User = Depends(get_current_user),
):
    return current_user