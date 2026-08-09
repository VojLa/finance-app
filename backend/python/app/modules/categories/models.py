from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models.enums import CategoryType


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


class CategoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(min_length=1, max_length=200)
    icon: str | None = Field(default=None, max_length=32)
    color: str | None = Field(default=None, max_length=32)
    type: CategoryType
    parent_id: str | None = Field(default=None, alias="parentId", max_length=200)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Category name is required.")
        return normalized

    @field_validator("icon", "color", "parent_id")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Idempotency key is required.")
        return normalized


class CategoryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    icon: str | None = Field(default=None, max_length=32)
    color: str | None = Field(default=None, max_length=32)
    type: CategoryType | None = None
    parent_id: str | None = Field(default=None, alias="parentId", max_length=200)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @field_validator("icon", "color", "parent_id")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @model_validator(mode="after")
    def require_update(self) -> CategoryUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("At least one category field is required.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Category name cannot be empty.")
        return self


class CategoryChildResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    icon: str | None
    color: str | None
    type: CategoryType
    is_default: bool = Field(serialization_alias="isDefault")
    user_id: str | None = Field(serialization_alias="userId")


class CategoryResponse(CategoryChildResponse):
    parent_id: str | None = Field(serialization_alias="parentId")
    children: list[CategoryChildResponse]


class CategoryDeleteResponse(BaseModel):
    ok: bool
