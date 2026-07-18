from datetime import datetime

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TIMESTAMP
from app.db.models.enums import (
    ACCOUNT_INVITE_STATUS_DB,
    ACCOUNT_MEMBER_ROLE_DB,
    ACCOUNT_RELATION_TYPE_DB,
    ACCOUNT_TYPE_DB,
    AccountInviteStatus,
    AccountMemberRole,
    AccountRelationType,
    AccountType,
)


class AccountModel(Base):
    __tablename__ = "Account"
    __table_args__ = (
        Index(None, "type"),
        Index(None, "isArchived"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[AccountType] = mapped_column(ACCOUNT_TYPE_DB, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(
        "isArchived",
        nullable=False,
        server_default=text("false"),
    )
    archived_at: Mapped[datetime | None] = mapped_column("archivedAt", TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class AccountMemberModel(Base):
    __tablename__ = "AccountMember"
    __table_args__ = (
        UniqueConstraint("accountId", "userId"),
        Index(None, "userId"),
        Index(None, "accountId", "role"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        "userId",
        ForeignKey("public.User.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[AccountMemberRole] = mapped_column(
        ACCOUNT_MEMBER_ROLE_DB,
        nullable=False,
        server_default=text("'viewer'::\"AccountMemberRole\""),
    )
    relation_type: Mapped[AccountRelationType] = mapped_column(
        "relationType",
        ACCOUNT_RELATION_TYPE_DB,
        nullable=False,
        server_default=text("'owner'::\"AccountRelationType\""),
    )
    invited_by_id: Mapped[str | None] = mapped_column("invitedById", Text)
    accepted_at: Mapped[datetime | None] = mapped_column("acceptedAt", TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)


class AccountInviteModel(Base):
    __tablename__ = "AccountInvite"
    __table_args__ = (
        UniqueConstraint("tokenHash"),
        Index(None, "accountId", "status"),
        Index(None, "email", "status"),
        Index(None, "inviterId", "createdAt"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id", ondelete="CASCADE"),
        nullable=False,
    )
    inviter_id: Mapped[str] = mapped_column(
        "inviterId",
        ForeignKey("public.User.id", ondelete="RESTRICT"),
        nullable=False,
    )
    accepted_by_id: Mapped[str | None] = mapped_column(
        "acceptedById",
        ForeignKey("public.User.id", ondelete="SET NULL"),
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[AccountMemberRole] = mapped_column(
        ACCOUNT_MEMBER_ROLE_DB,
        nullable=False,
        server_default=text("'viewer'::\"AccountMemberRole\""),
    )
    status: Mapped[AccountInviteStatus] = mapped_column(
        ACCOUNT_INVITE_STATUS_DB,
        nullable=False,
        server_default=text("'pending'::\"AccountInviteStatus\""),
    )
    token_hash: Mapped[str] = mapped_column("tokenHash", Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column("expiresAt", TIMESTAMP, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column("acceptedAt", TIMESTAMP)
    revoked_at: Mapped[datetime | None] = mapped_column("revokedAt", TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)
