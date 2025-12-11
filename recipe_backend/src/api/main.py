import os
from typing import List

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# PUBLIC_INTERFACE
def parse_csv_env(value: str) -> List[str]:
    """Parse a comma-separated environment variable into a list of strings."""
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]

# App metadata with OpenAPI info and tags
openapi_tags = [
    {"name": "Health", "description": "Service health checks"},
    {"name": "Diagnostics", "description": "Runtime configuration and diagnostics"},
    {"name": "Auth", "description": "Authentication and user session"},
    {"name": "Categories", "description": "Recipe categories"},
    {"name": "Recipes", "description": "Browse and search recipes"},
    {"name": "Favorites", "description": "Manage favorite recipes (protected)"},
    {"name": "Notes", "description": "Manage personal notes (protected)"},
]

app = FastAPI(
    title="Recipe Hub Backend",
    description=(
        "Backend API for the Recipe Hub application. "
        "Provides endpoints for authentication, recipe management, favorites, and notes."
    ),
    version="0.1.0",
    openapi_tags=openapi_tags,
)

# Load environment configuration (dotenv is already in requirements)
from dotenv import load_dotenv
load_dotenv()  # loads variables from a .env file if present

# Read configuration with sensible defaults
DATABASE_URL = os.getenv("DATABASE_URL", "")
JWT_SECRET = os.getenv("JWT_SECRET", "CHANGE_ME_DEV_ONLY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
CORS_ALLOW_ORIGINS = parse_csv_env(os.getenv("CORS_ALLOW_ORIGINS", ""))

# Configure CORS. If no explicit origins, allow all for development convenience.
allow_all = not CORS_ALLOW_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all else CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and include routers after app instantiation to avoid circular imports
from .auth import router as auth_router, get_current_user  # noqa: E402
from .recipes import (  # noqa: E402
    categories_router,
    favorites_router,
    notes_router,
    recipes_router,
)

app.include_router(auth_router)
app.include_router(categories_router)
app.include_router(recipes_router)
app.include_router(favorites_router)
app.include_router(notes_router)

# If a real DATABASE_URL is provided, ensure metadata is created to avoid missing table runtime errors.
# This is a no-op for in-memory sqlite fallback used when DATABASE_URL is empty.
try:
    if DATABASE_URL:
        from sqlalchemy import create_engine
        from .models import Base  # import here to avoid circulars
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        Base.metadata.create_all(bind=engine)
except Exception:
    # Avoid app startup failure if database is temporarily unreachable.
    # Diagnostics endpoint will still show database_configured flag.
    pass

# Simple config model to expose limited non-sensitive runtime info if needed
class RuntimeConfig(BaseModel):
    """Non-sensitive runtime configuration values for diagnostics."""
    cors_allow_origins: List[str]
    jwt_algorithm: str
    access_token_expire_minutes: int
    database_configured: bool

@app.get("/", summary="Health Check", tags=["Health"])
def health_check():
    """Health check endpoint. Returns a simple JSON indicating service status."""
    return {"message": "Healthy"}

# PUBLIC_INTERFACE
@app.get("/config/runtime", summary="Runtime Config (sanitized)", tags=["Diagnostics"])
def get_runtime_config() -> RuntimeConfig:
    """Return sanitized runtime configuration to aid debugging (no secrets)."""
    return RuntimeConfig(
        cors_allow_origins=CORS_ALLOW_ORIGINS if CORS_ALLOW_ORIGINS else ["*"],
        jwt_algorithm=JWT_ALGORITHM,
        access_token_expire_minutes=ACCESS_TOKEN_EXPIRE_MINUTES,
        database_configured=bool(DATABASE_URL),
    )

# Example protected endpoint to verify JWT functionality in docs
@app.get("/auth/me", tags=["Auth"], summary="Get current user (protected)")
def read_current_user(user=Depends(get_current_user)):
    """Return the current authenticated user information."""
    from .auth import UserRead  # local import to avoid circular typing issues
    return UserRead.model_validate(user)
