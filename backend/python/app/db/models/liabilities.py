from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import MONEY, TIMESTAMP
from app.db.models.enums import LIABILITY_BALANCE_SOURCE_DB, LiabilityBalanceSource


class LiabilityBalanceModel(Base):
    __tablename__ = "LiabilityBalance"
    __table_args__ = (
        UniqueConstraint("accountId", "effectiveAt", "source"),
        UniqueConstraint("accountId", "source", "externalId"),
        CheckConstraint(
            '"outstandingPrincipal" >= 0',
            name="LiabilityBalance_outstandingPrincipal_nonnegative",
        ),
        CheckConstraint(
            '"accruedInterest" >= 0',
            name="LiabilityBalance_accruedInterest_nonnegative",
        ),
        CheckConstraint(
            '"feesOutstanding" >= 0',
            name="LiabilityBalance_feesOutstanding_nonnegative",
        ),
        CheckConstraint(
            '"totalOutstanding" >= 0',
            name="LiabilityBalance_totalOutstanding_nonnegative",
        ),
        CheckConstraint(
            '"totalOutstanding" = "outstandingPrincipal" + "accruedInterest" + "feesOutstanding"',
            name="LiabilityBalance_totalOutstanding_components",
        ),
        Index(None, "accountId", "effectiveAt"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    effective_at: Mapped[datetime] = mapped_column("effectiveAt", TIMESTAMP, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    outstanding_principal: Mapped[Decimal] = mapped_column(
        "outstandingPrincipal",
        MONEY,
        nullable=False,
    )
    accrued_interest: Mapped[Decimal] = mapped_column(
        "accruedInterest",
        MONEY,
        nullable=False,
    )
    fees_outstanding: Mapped[Decimal] = mapped_column(
        "feesOutstanding",
        MONEY,
        nullable=False,
    )
    total_outstanding: Mapped[Decimal] = mapped_column(
        "totalOutstanding",
        MONEY,
        nullable=False,
    )
    source: Mapped[LiabilityBalanceSource] = mapped_column(
        LIABILITY_BALANCE_SOURCE_DB,
        nullable=False,
    )
    external_id: Mapped[str | None] = mapped_column("externalId", Text)
    created_at: Mapped[datetime] = mapped_column("createdAt", TIMESTAMP, nullable=False)
