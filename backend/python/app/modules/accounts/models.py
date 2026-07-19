from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models.enums import AccountMemberRole, AccountRelationType, AccountType


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    type: AccountType
    currency: str
    color: str | None
    notes: str | None
    is_archived: bool
    role: AccountMemberRole
    relation_type: AccountRelationType
    created_at: datetime
    updated_at: datetime


class AccountMemberResponse(BaseModel):
    id: str
    user_id: str
    email: str
    name: str | None
    role: AccountMemberRole
    relation_type: AccountRelationType
    accepted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AccountMemberRoleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AccountMemberRole

    @model_validator(mode="after")
    def forbid_owner_assignment(self) -> "AccountMemberRoleUpdateRequest":
        if self.role is AccountMemberRole.owner:
            raise ValueError("Ownership transfer is not supported by this endpoint.")
        return self


class AccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    type: AccountType
    currency: str = Field(min_length=3, max_length=3)
    color: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Account name must not be blank.")
        return normalized

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha() or not normalized.isascii():
            raise ValueError("Currency must be a three-letter ASCII code.")
        return normalized

    @field_validator("color", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class AccountUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    color: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Account name must not be blank.")
        return normalized

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha() or not normalized.isascii():
            raise ValueError("Currency must be a three-letter ASCII code.")
        return normalized

    @field_validator("color", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def require_update(self) -> "AccountUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one mutable account field is required.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Account name must not be null.")
        if "currency" in self.model_fields_set and self.currency is None:
            raise ValueError("Account currency must not be null.")
        return self
