from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.categories import CategoryModel
from app.modules.categories.models import (
    CategoryChildResponse,
    CategoryCreateRequest,
    CategoryResponse,
    CategoryUpdateRequest,
)
from app.modules.categories.repository import CategoryRepository
from app.shared.errors import ApplicationError

_CATEGORY_NAMESPACE = UUID("f83ef478-1a74-5d73-9325-b2e4cd70cd98")


class CategoryNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="category_not_found", message="The category was not found.", status_code=404
        )


class CategoryConflictError(ApplicationError):
    def __init__(self, message: str = "The category hierarchy is invalid.") -> None:
        super().__init__(code="category_conflict", message=message, status_code=409)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class CategoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = CategoryRepository(session)

    async def list_categories(self, principal: AuthenticatedPrincipal) -> list[CategoryResponse]:
        categories = await self.repository.list_accessible(principal.user_id)
        await self.session.commit()
        return self._responses(categories)

    async def create(
        self,
        *,
        principal: AuthenticatedPrincipal,
        payload: CategoryCreateRequest,
    ) -> CategoryResponse:
        key = f"category:create:{principal.user_id}:{payload.idempotency_key}"
        await self.repository.lock_idempotency_key(key)
        category_id = str(uuid5(_CATEGORY_NAMESPACE, key))
        existing = await self.repository.get_accessible(
            category_id=category_id,
            user_id=principal.user_id,
        )
        if existing is not None:
            if not self._matches_create(existing, principal.user_id, payload):
                await self.session.rollback()
                raise CategoryConflictError("The idempotency key has already been used.")
            categories = await self.repository.list_accessible(principal.user_id)
            await self.session.commit()
            return self._find_response(categories, category_id)

        await self._validate_parent(
            principal=principal,
            parent_id=payload.parent_id,
            category_id=None,
        )
        now = _now()
        category = CategoryModel(
            id=category_id,
            name=payload.name,
            icon=payload.icon,
            color=payload.color,
            type=payload.type,
            parent_id=payload.parent_id,
            is_default=False,
            user_id=principal.user_id,
            created_at=now,
            updated_at=now,
        )
        self.repository.add(category)
        await self._commit()
        categories = await self.repository.list_accessible(principal.user_id)
        await self.session.commit()
        return self._find_response(categories, category_id)

    async def update(
        self,
        *,
        principal: AuthenticatedPrincipal,
        category_id: str,
        payload: CategoryUpdateRequest,
    ) -> CategoryResponse:
        category = await self.repository.get_owned_for_update(
            category_id=category_id,
            user_id=principal.user_id,
        )
        if category is None:
            await self.session.rollback()
            raise CategoryNotFoundError()
        parent_id = (
            payload.parent_id if "parent_id" in payload.model_fields_set else category.parent_id
        )
        await self._validate_parent(
            principal=principal,
            parent_id=parent_id,
            category_id=category.id,
        )
        for field in ("name", "icon", "color", "type", "parent_id"):
            if field in payload.model_fields_set:
                setattr(category, field, getattr(payload, field))
        category.updated_at = _now()
        await self._commit()
        categories = await self.repository.list_accessible(principal.user_id)
        await self.session.commit()
        return self._find_response(categories, category_id)

    async def delete(self, *, principal: AuthenticatedPrincipal, category_id: str) -> None:
        category = await self.repository.get_owned_for_update(
            category_id=category_id,
            user_id=principal.user_id,
        )
        if category is None:
            await self.session.rollback()
            raise CategoryNotFoundError()
        await self.session.delete(category)
        await self._commit()

    async def _validate_parent(
        self,
        *,
        principal: AuthenticatedPrincipal,
        parent_id: str | None,
        category_id: str | None,
    ) -> None:
        if parent_id is None:
            return
        if parent_id == category_id:
            raise CategoryConflictError()
        parent = await self.repository.get_accessible(
            category_id=parent_id,
            user_id=principal.user_id,
        )
        if parent is None:
            raise CategoryNotFoundError()
        visited = {category_id} if category_id is not None else set()
        current = parent
        while current.parent_id is not None:
            if current.id in visited or current.parent_id == category_id:
                raise CategoryConflictError()
            visited.add(current.id)
            next_parent = await self.repository.get_accessible(
                category_id=current.parent_id,
                user_id=principal.user_id,
            )
            if next_parent is None:
                raise CategoryConflictError()
            current = next_parent

    async def _commit(self) -> None:
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    @staticmethod
    def _matches_create(
        category: CategoryModel,
        user_id: str,
        payload: CategoryCreateRequest,
    ) -> bool:
        return (
            category.user_id == user_id
            and not category.is_default
            and category.name == payload.name
            and category.icon == payload.icon
            and category.color == payload.color
            and category.type is payload.type
            and category.parent_id == payload.parent_id
        )

    @classmethod
    def _responses(cls, categories: list[CategoryModel]) -> list[CategoryResponse]:
        accessible_ids = {category.id for category in categories}
        children: dict[str, list[CategoryChildResponse]] = {}
        for category in categories:
            if category.parent_id in accessible_ids:
                children.setdefault(category.parent_id, []).append(cls._child(category))
        return [
            CategoryResponse(
                **cls._child(category).model_dump(),
                parent_id=category.parent_id if category.parent_id in accessible_ids else None,
                children=children.get(category.id, []),
            )
            for category in categories
        ]

    @staticmethod
    def _child(category: CategoryModel) -> CategoryChildResponse:
        return CategoryChildResponse(
            id=category.id,
            name=category.name,
            icon=category.icon,
            color=category.color,
            type=category.type,
            is_default=category.is_default,
            user_id=category.user_id,
        )

    @classmethod
    def _find_response(cls, categories: list[CategoryModel], category_id: str) -> CategoryResponse:
        return next(item for item in cls._responses(categories) if item.id == category_id)
