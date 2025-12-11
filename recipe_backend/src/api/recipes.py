"""
Recipes, Categories, Favorites, and Notes API routes.

This module defines:
- Categories router: list categories.
- Recipes router: list, detail, and ingredient-based search.
- Favorites router (protected): list, add, remove favorites for the current user.
- Notes router (protected): CRUD operations for user notes on recipes.

Ingredient search:
- GET /recipes/search?ingredients=tomato,onion
- Ingredients parameter is comma-separated list; AND semantics mean the recipe must
  include all provided ingredients. Uses a normalized form of ingredient names by
  lowercasing and trimming whitespace for comparison.

Security:
- Favorites and Notes endpoints require authentication via JWT (get_current_user).
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .deps import get_current_user, get_db
from .models import Category, Favorite, Note, Recipe, RecipeIngredient, User

# -----------------------------------------------------------------------------
# Pydantic Schemas
# -----------------------------------------------------------------------------

class CategoryRead(BaseModel):
    """Public representation of a category."""
    id: int
    name: str
    description: Optional[str] = None

    class Config:
        from_attributes = True


class RecipeIngredientRead(BaseModel):
    """Public representation of a recipe ingredient line."""
    id: int
    name: str
    quantity: Optional[str] = None

    class Config:
        from_attributes = True


class RecipeRead(BaseModel):
    """Public representation of a recipe."""
    id: int
    title: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    servings: Optional[int] = None

    class Config:
        from_attributes = True


class RecipeDetailRead(RecipeRead):
    """Detailed representation of a recipe with ingredients and categories."""
    instructions: Optional[str] = None
    categories: List[CategoryRead] = []
    ingredients: List[RecipeIngredientRead] = []


class FavoriteRead(BaseModel):
    """Favorite relationship info."""
    id: int
    user_id: int
    recipe_id: int

    class Config:
        from_attributes = True


class FavoriteCreate(BaseModel):
    """Payload to create a favorite for a recipe."""
    recipe_id: int = Field(..., description="ID of the recipe to favorite")


class NoteRead(BaseModel):
    """Public representation of a note."""
    id: int
    user_id: int
    recipe_id: int
    content: str

    class Config:
        from_attributes = True


class NoteCreate(BaseModel):
    """Payload to create a new note."""
    recipe_id: int = Field(..., description="ID of the recipe to attach the note to")
    content: str = Field(..., min_length=1, description="Note content (non-empty)")


class NoteUpdate(BaseModel):
    """Payload to update an existing note."""
    content: str = Field(..., min_length=1, description="Updated note content")


# -----------------------------------------------------------------------------
# Utility
# -----------------------------------------------------------------------------

def _normalize_ingredient(value: str) -> str:
    """Normalize ingredient name to compare. Lowercase and strip spaces."""
    return value.strip().lower()


# -----------------------------------------------------------------------------
# Routers
# -----------------------------------------------------------------------------

categories_router = APIRouter(prefix="/categories", tags=["Categories"])
recipes_router = APIRouter(prefix="/recipes", tags=["Recipes"])
favorites_router = APIRouter(prefix="/favorites", tags=["Favorites"])
notes_router = APIRouter(prefix="/notes", tags=["Notes"])


# -----------------------------------------------------------------------------
# Categories
# -----------------------------------------------------------------------------

@categories_router.get(
    "",
    response_model=List[CategoryRead],
    summary="List categories",
    description="Return all recipe categories.",
)
def list_categories(db: Session = Depends(get_db)) -> List[CategoryRead]:
    """List all categories."""
    categories = db.execute(select(Category).order_by(Category.name.asc())).scalars().all()
    return [CategoryRead.model_validate(c) for c in categories]


# -----------------------------------------------------------------------------
# Recipes
# -----------------------------------------------------------------------------

@recipes_router.get(
    "",
    response_model=List[RecipeRead],
    summary="List recipes",
    description="Return a list of public recipes ordered by recent.",
)
def list_recipes(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of recipes to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> List[RecipeRead]:
    """List public recipes with pagination."""
    stmt = (
        select(Recipe)
        .where(Recipe.is_public.is_(True))
        .order_by(Recipe.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    recipes = db.execute(stmt).scalars().all()
    return [RecipeRead.model_validate(r) for r in recipes]


@recipes_router.get(
    "/{recipe_id}",
    response_model=RecipeDetailRead,
    summary="Get recipe details",
    description="Return detailed information for a recipe, including categories and ingredients.",
)
def get_recipe(
    recipe_id: int = Path(..., ge=1, description="Recipe ID"),
    db: Session = Depends(get_db),
) -> RecipeDetailRead:
    """Retrieve recipe details or 404 if not found or not public."""
    recipe = db.get(Recipe, recipe_id)
    if recipe is None or not recipe.is_public:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")

    # Eagerly load related data by accessing them (relationships configured)
    categories = [CategoryRead.model_validate(c) for c in recipe.categories]
    ingredients = [RecipeIngredientRead.model_validate(i) for i in recipe.ingredients]

    return RecipeDetailRead(
        **RecipeDetailRead.model_validate(recipe).model_dump(),
        categories=categories,
        ingredients=ingredients,
    )


@recipes_router.get(
    "/search",
    response_model=List[RecipeRead],
    summary="Search recipes by ingredients",
    description=(
        "Search public recipes that include all provided ingredients (AND semantics). "
        "Provide comma-separated 'ingredients' query parameter using ingredient names; "
        "matching is case-insensitive and whitespace-insensitive."
    ),
)
def search_recipes_by_ingredients(
    ingredients: str = Query(
        ...,
        description="Comma-separated ingredient names. AND semantics; recipes must include all.",
        example="tomato,onion,basil",
    ),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> List[RecipeRead]:
    """
    Search recipes that contain all specified ingredients.

    Implementation uses a grouped HAVING query:
    - Filter ingredients to those in the normalized list.
    - Group by recipe and require count of distinct matched ingredient names to equal
      the number of requested ingredients.
    - Only include public recipes.
    """
    raw = [p for p in (ingredients.split(",") if ingredients else []) if p.strip()]
    if not raw:
        return []
    terms = [_normalize_ingredient(p) for p in raw]
    # Build query: select recipes that have all terms
    # Using lower(RecipeIngredient.name) for normalization
    subq = (
        select(
            RecipeIngredient.recipe_id.label("recipe_id"),
            func.count(func.distinct(func.lower(RecipeIngredient.name))).label("matched"),
        )
        .where(func.lower(RecipeIngredient.name).in_(terms))
        .group_by(RecipeIngredient.recipe_id)
        .having(func.count(func.distinct(func.lower(RecipeIngredient.name))) == len(set(terms)))
        .subquery()
    )

    stmt = (
        select(Recipe)
        .join(subq, Recipe.id == subq.c.recipe_id)
        .where(Recipe.is_public.is_(True))
        .order_by(Recipe.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    recipes = db.execute(stmt).scalars().all()
    return [RecipeRead.model_validate(r) for r in recipes]


# -----------------------------------------------------------------------------
# Favorites (Protected)
# -----------------------------------------------------------------------------

@favorites_router.get(
    "",
    response_model=List[RecipeRead],
    summary="List my favorite recipes",
    description="Return the current user's favorite recipes.",
)
def list_my_favorites(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user()),
) -> List[RecipeRead]:
    """List the current user's favorite recipes."""
    # Join favorites to recipes to return recipe info
    stmt = (
        select(Recipe)
        .join(Favorite, Favorite.recipe_id == Recipe.id)
        .where(Favorite.user_id == user.id)
        .order_by(Favorite.created_at.desc())
    )
    recipes = db.execute(stmt).scalars().all()
    return [RecipeRead.model_validate(r) for r in recipes]


@favorites_router.post(
    "",
    response_model=FavoriteRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add recipe to favorites",
    description="Mark a recipe as favorite for the current user.",
    responses={
        201: {"description": "Favorite created"},
        409: {"description": "Already favorited"},
        404: {"description": "Recipe not found"},
    },
)
def add_favorite(
    payload: FavoriteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user()),
) -> FavoriteRead:
    """Add a recipe to the current user's favorites."""
    recipe = db.get(Recipe, payload.recipe_id)
    if recipe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")

    # Check existing favorite
    existing = db.execute(
        select(Favorite).where(
            Favorite.user_id == user.id, Favorite.recipe_id == payload.recipe_id
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already favorited")

    fav = Favorite(user_id=user.id, recipe_id=payload.recipe_id)
    db.add(fav)
    db.flush()
    return FavoriteRead.model_validate(fav)


@favorites_router.delete(
    "/{recipe_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove recipe from favorites",
    description="Unmark a recipe as favorite for the current user.",
    responses={
        204: {"description": "Favorite removed"},
        404: {"description": "Favorite not found"},
    },
)
def remove_favorite(
    recipe_id: int = Path(..., ge=1, description="Recipe ID to remove from favorites"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user()),
) -> None:
    """Remove a recipe from the current user's favorites."""
    fav = db.execute(
        select(Favorite).where(Favorite.user_id == user.id, Favorite.recipe_id == recipe_id)
    ).scalar_one_or_none()
    if not fav:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Favorite not found")
    db.delete(fav)
    # commit handled by dependency


# -----------------------------------------------------------------------------
# Notes (Protected)
# -----------------------------------------------------------------------------

@notes_router.get(
    "",
    response_model=List[NoteRead],
    summary="List my notes",
    description="Return all notes created by the current user.",
)
def list_my_notes(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user()),
) -> List[NoteRead]:
    """List all notes by the current user."""
    notes = db.execute(
        select(Note).where(Note.user_id == user.id).order_by(Note.updated_at.desc())
    ).scalars().all()
    return [NoteRead.model_validate(n) for n in notes]


@notes_router.post(
    "",
    response_model=NoteRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a note",
    description="Create a new note for a recipe.",
    responses={
        201: {"description": "Note created"},
        404: {"description": "Recipe not found"},
    },
)
def create_note(
    payload: NoteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user()),
) -> NoteRead:
    """Create a new note for a recipe by the current user."""
    recipe = db.get(Recipe, payload.recipe_id)
    if recipe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    note = Note(user_id=user.id, recipe_id=payload.recipe_id, content=payload.content)
    db.add(note)
    db.flush()
    return NoteRead.model_validate(note)


@notes_router.get(
    "/{note_id}",
    response_model=NoteRead,
    summary="Get a note",
    description="Get a specific note belonging to the current user.",
    responses={404: {"description": "Note not found"}},
)
def get_note(
    note_id: int = Path(..., ge=1, description="Note ID"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user()),
) -> NoteRead:
    """Get a note by ID if it belongs to the current user."""
    note = db.get(Note, note_id)
    if note is None or note.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return NoteRead.model_validate(note)


@notes_router.put(
    "/{note_id}",
    response_model=NoteRead,
    summary="Update a note",
    description="Update content of a specific note belonging to the current user.",
    responses={404: {"description": "Note not found"}},
)
def update_note(
    note_id: int,
    payload: NoteUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user()),
) -> NoteRead:
    """Update a note's content if it belongs to the current user."""
    note = db.get(Note, note_id)
    if note is None or note.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    note.content = payload.content
    # Flush to persist update before returning
    db.flush()
    return NoteRead.model_validate(note)


@notes_router.delete(
    "/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a note",
    description="Delete a specific note belonging to the current user.",
    responses={404: {"description": "Note not found"}},
)
def delete_note(
    note_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user()),
) -> None:
    """Delete a note if it belongs to the current user."""
    note = db.get(Note, note_id)
    if note is None or note.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    db.delete(note)
    # commit handled by dependency
