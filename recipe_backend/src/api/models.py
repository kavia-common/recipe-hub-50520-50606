"""
SQLAlchemy ORM models for the Recipe Hub backend.

Defines:
- Base: Declarative base for all models
- User: Application users with hashed passwords
- Category: Recipe categories
- Recipe: Recipes with metadata and relations
- RecipeCategory: Association table for many-to-many Recipe<->Category
- RecipeIngredient: Ingredients for a recipe
- Favorite: Users' favorite recipes
- Note: Users' personal notes on recipes
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Table,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


# Association table for many-to-many Recipe <-> Category
recipe_categories_table = Table(
    "recipe_categories",
    Base.metadata,
    Column("recipe_id", ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True),
    Column("category_id", ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True),
    UniqueConstraint("recipe_id", "category_id", name="uq_recipe_category"),
)


class User(Base):
    """Represents an application user account."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relations
    recipes: Mapped[List["Recipe"]] = relationship(
        back_populates="author",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    favorites: Mapped[List["Favorite"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    notes: Mapped[List["Note"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # PUBLIC_INTERFACE
    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"User(id={self.id}, email={self.email!r})"


class Category(Base):
    """Represents a category to which recipes can belong (e.g., Breakfast, Vegan)."""
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    recipes: Mapped[List["Recipe"]] = relationship(
        secondary=recipe_categories_table,
        back_populates="categories",
    )

    # PUBLIC_INTERFACE
    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"Category(id={self.id}, name={self.name!r})"


class Recipe(Base):
    """Represents a recipe entity with metadata and relationships."""
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    prep_time_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cook_time_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    servings: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    author_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relations
    author: Mapped[Optional[User]] = relationship(back_populates="recipes")
    categories: Mapped[List[Category]] = relationship(
        secondary=recipe_categories_table,
        back_populates="recipes",
    )
    ingredients: Mapped[List["RecipeIngredient"]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    favorites: Mapped[List["Favorite"]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    notes: Mapped[List["Note"]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # PUBLIC_INTERFACE
    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"Recipe(id={self.id}, title={self.title!r})"


class RecipeIngredient(Base):
    """Represents an ingredient line belonging to a recipe."""
    __tablename__ = "recipe_ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    recipe_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recipes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    quantity: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")

    # PUBLIC_INTERFACE
    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"RecipeIngredient(id={self.id}, name={self.name!r})"


class Favorite(Base):
    """Represents a user's favorite recipe."""
    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "recipe_id", name="uq_favorite_user_recipe"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    recipe_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recipes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="favorites")
    recipe: Mapped[Recipe] = relationship(back_populates="favorites")

    # PUBLIC_INTERFACE
    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"Favorite(id={self.id}, user_id={self.user_id}, recipe_id={self.recipe_id})"


class Note(Base):
    """Represents a user's personal note on a recipe."""
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    recipe_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recipes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="notes")
    recipe: Mapped[Recipe] = relationship(back_populates="notes")

    # PUBLIC_INTERFACE
    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"Note(id={self.id}, user_id={self.user_id}, recipe_id={self.recipe_id})"
