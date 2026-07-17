from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import MONEY, THRESHOLD, TIMESTAMP
from app.db.models.enums import (
    BUDGET_ALERT_TYPE_DB,
    BUDGET_PERIOD_TYPE_DB,
    BudgetAlertType,
    BudgetPeriodType,
)


class BudgetModel(Base):
    __tablename__ = "Budget"
    __table_args__ = (
        UniqueConstraint("userId", "periodStart", "periodEnd", "name"),
        Index(None, "userId", "periodStart", "periodEnd"),
        {"schema": "public"},
    )  # noqa: RUF012

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[datetime] = mapped_column("periodStart", TIMESTAMP, nullable=False)
    period_end: Mapped[datetime] = mapped_column("periodEnd", TIMESTAMP, nullable=False)
    period_type: Mapped[BudgetPeriodType] = mapped_column(
        "periodType",
        BUDGET_PERIOD_TYPE_DB,
        nullable=False,
        server_default=text("'monthly'::\"BudgetPeriodType\""),
    )
    currency: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'CZK'::text"),
    )
    rollover_enabled: Mapped[bool] = mapped_column(
        "rolloverEnabled",
        nullable=False,
        server_default=text("false"),
    )
    user_id: Mapped[str] = mapped_column(
        "userId",
        ForeignKey("public.User.id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)


class BudgetItemModel(Base):
    __tablename__ = "BudgetItem"
    __table_args__ = (
        Index(None, "budgetId"),
        {"schema": "public"},
    )  # noqa: RUF012

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'CZK'::text"),
    )
    rollover_amount: Mapped[Decimal | None] = mapped_column("rolloverAmount", MONEY)
    budget_id: Mapped[str] = mapped_column(
        "budgetId",
        ForeignKey("public.Budget.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)


class BudgetItemCategoryModel(Base):
    __tablename__ = "BudgetItemCategory"
    __table_args__ = (
        UniqueConstraint("budgetItemId", "categoryId"),
        Index(None, "categoryId"),
        {"schema": "public"},
    )  # noqa: RUF012

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    budget_item_id: Mapped[str] = mapped_column(
        "budgetItemId",
        ForeignKey("public.BudgetItem.id", ondelete="CASCADE"),
        nullable=False,
    )
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


class BudgetAccountModel(Base):
    __tablename__ = "BudgetAccount"
    __table_args__ = (
        UniqueConstraint("budgetId", "accountId"),
        Index(None, "accountId"),
        {"schema": "public"},
    )  # noqa: RUF012

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    budget_id: Mapped[str] = mapped_column(
        "budgetId",
        ForeignKey("public.Budget.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class BudgetAlertModel(Base):
    __tablename__ = "BudgetAlert"
    __table_args__ = (
        Index(None, "userId", "triggeredAt"),
        Index(None, "budgetItemId"),
        {"schema": "public"},
    )  # noqa: RUF012

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "userId",
        ForeignKey("public.User.id"),
        nullable=False,
    )
    budget_item_id: Mapped[str] = mapped_column(
        "budgetItemId",
        ForeignKey("public.BudgetItem.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[BudgetAlertType] = mapped_column(BUDGET_ALERT_TYPE_DB, nullable=False)
    threshold: Mapped[Decimal] = mapped_column(THRESHOLD, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(
        "triggeredAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column("acknowledgedAt", TIMESTAMP)
