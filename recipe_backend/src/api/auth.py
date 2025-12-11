"""
Authentication routes and utilities for the Recipe Hub backend.

This module provides:
- POST /auth/register: User registration with hashed passwords and unique email constraint.
- POST /auth/login: User login using email and password, issuing a JWT bearer token.
- get_current_user dependency: Validates Authorization: Bearer <token> and loads the current user.

Environment variables (loaded via dotenv in app startup):
- JWT_SECRET: Secret key for signing JWTs (REQUIRED in production).
- JWT_ALGORITHM: Algorithm used for JWT signing (default: HS256).
- ACCESS_TOKEN_EXPIRE_MINUTES: Access token lifetime in minutes (default: 60).

Notes:
- Uses passlib[bcrypt] for password hashing.
- Uses python-jose for JWT signing/verification.
- Integrates with SQLAlchemy models.User and dependency-injected DB session.

OpenAPI:
- Routes are documented with summaries and responses.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .deps import get_db
from .models import User

# Configuration from environment (dotenv loaded in app startup in main.py)
JWT_SECRET = os.getenv("JWT_SECRET", "CHANGE_ME_DEV_ONLY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# Password hashing context (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme for bearer token extraction
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", scheme_name="JWT")


# Pydantic schemas
class Token(BaseModel):
    """JWT access token response."""
    access_token: str = Field(..., description="The JWT access token")
    token_type: str = Field("bearer", description="Token type. Always 'bearer'.")


class UserCreate(BaseModel):
    """Schema for user registration."""
    email: EmailStr = Field(..., description="Unique user email")
    password: str = Field(..., min_length=6, description="Account password")
    full_name: Optional[str] = Field(None, description="User's full name")


class UserRead(BaseModel):
    """Sanitized user representation."""
    id: int
    email: EmailStr
    full_name: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


# Utility functions
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT access token for a subject (e.g., user ID or email)."""
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode = {"sub": subject, "exp": expire}
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt


# PUBLIC_INTERFACE
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Retrieve the currently authenticated user by validating a JWT Bearer token.

    Parameters:
    - token: Extracted from the Authorization header by OAuth2PasswordBearer.
    - db: SQLAlchemy session.

    Returns:
    - User ORM instance of the authenticated user.

    Raises:
    - HTTPException 401 if token is invalid/expired or user does not exist.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        subject: Optional[str] = payload.get("sub")
        if subject is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # We store subject as user id if available, else email. Try id first then email.
    user: Optional[User] = None
    if subject.isdigit():
        user = db.get(User, int(subject))
    if user is None:
        stmt = select(User).where(User.email == subject)
        user = db.execute(stmt).scalar_one_or_none()

    if user is None or not user.is_active:
        raise credentials_exception
    return user


router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Create a new user account with a unique email. Password is stored hashed.",
    responses={
        201: {"description": "User created"},
        400: {"description": "Email already registered"},
    },
)
def register_user(payload: UserCreate, db: Session = Depends(get_db)) -> UserRead:
    """
    Register a new user.

    Parameters:
    - payload: UserCreate with email, password, and optional full_name.
    - db: SQLAlchemy session.

    Returns:
    - UserRead: Newly created user (without sensitive fields).

    Errors:
    - 400 if email already exists.
    """
    # Check if email already exists
    existing = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is already registered")

    # Create and persist new user
    user = User(
        email=str(payload.email).lower(),
        hashed_password=get_password_hash(payload.password),
        full_name=payload.full_name,
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    db.flush()  # To get the ID before commit for response
    return UserRead.model_validate(user)


@router.post(
    "/login",
    response_model=Token,
    summary="Login with email and password",
    description="Authenticate using email and password to receive a JWT bearer token.",
    responses={
        200: {"description": "Successful authentication"},
        400: {"description": "Invalid credentials"},
        401: {"description": "Inactive user"},
    },
)
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    """
    Authenticate a user and return an access token.

    Accepts standard OAuth2PasswordRequestForm with 'username' (email) and 'password'.

    Returns:
    - Token: {access_token, token_type: 'bearer'}

    Errors:
    - 400 if credentials are invalid.
    - 401 if user is inactive.
    """
    email = form_data.username.strip().lower()
    stmt = select(User).where(User.email == email)
    user = db.execute(stmt).scalar_one_or_none()

    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect email or password")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")

    token = create_access_token(subject=str(user.id))
    return Token(access_token=token, token_type="bearer")
