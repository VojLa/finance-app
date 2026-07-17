from datetime import datetime

from sqlalchemy import ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TIMESTAMP
from app.db.models.enums import (
    ALIAS_MATCH_TYPE_DB,
    COUNTERPARTY_TYPE_DB,
    AliasMatchType,
    CounterpartyType,
)


class CounterpartyModel(Base):
    __tablename__ = "Counterparty"
    __table_args__ = (
        Index(None, "userId"),
        Index(None, "userId", "name"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "userId",
        ForeignKey("public.User.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[CounterpartyType] = mapped_column(
        COUNTERPARTY_TYPE_DB,
        nullable=False,
        server_default=text("'other'::\"CounterpartyType\""),
    )
    account_number: Mapped[str | None] = mapped_column("accountNumber", Text)
    iban: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)


class CounterpartyAliasModel(Base):
    __tablename__ = "CounterpartyAlias"
    __table_args__ = (
        Index(None, "counterpartyId"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    counterparty_id: Mapped[str] = mapped_column(
        "counterpartyId",
        ForeignKey("public.Counterparty.id", ondelete="CASCADE"),
        nullable=False,
    )
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    match_type: Mapped[AliasMatchType] = mapped_column(
        "matchType",
        ALIAS_MATCH_TYPE_DB,
        nullable=False,
        server_default=text("'contains'::\"AliasMatchType\""),
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
