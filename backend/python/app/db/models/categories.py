from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TIMESTAMP
from app.db.models.enums import (
    CATEGORY_TYPE_DB,
    RULE_FIELD_DB,
    RULE_OPERATOR_DB,
    TRANSACTION_CLASSIFICATION_DB,
    CategoryType,
    RuleField,
    RuleOperator,
    TransactionClassification,
)


class CategoryModel(Base):
    __tablename__ = "Category"
    __table_args__ = (
        Index(None, "userId"),
        Index(None, "parentId"),
        Index(None, "userId", "type"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    icon: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(Text)
    type: Mapped[CategoryType] = mapped_column(CATEGORY_TYPE_DB, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        "parentId",
        ForeignKey("public.Category.id"),
    )
    is_default: Mapped[bool] = mapped_column(
        "isDefault",
        nullable=False,
        server_default=text("false"),
    )
    user_id: Mapped[str | None] = mapped_column("userId", Text)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)


class CategoryRuleModel(Base):
    __tablename__ = "CategoryRule"
    __table_args__ = (
        Index(None, "userId"),
        Index(None, "categoryId"),
        Index(None, "field", "operator"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    field: Mapped[RuleField] = mapped_column(RULE_FIELD_DB, nullable=False)
    operator: Mapped[RuleOperator] = mapped_column(
        RULE_OPERATOR_DB,
        nullable=False,
        server_default=text("'contains'::\"RuleOperator\""),
    )
    classification: Mapped[TransactionClassification | None] = mapped_column(
        TRANSACTION_CLASSIFICATION_DB
    )
    requires_review: Mapped[bool] = mapped_column(
        "requiresReview",
        nullable=False,
        server_default=text("false"),
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    user_id: Mapped[str | None] = mapped_column("userId", Text)
    category_id: Mapped[str] = mapped_column(
        "categoryId",
        ForeignKey("public.Category.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)
