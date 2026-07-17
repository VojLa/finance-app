from datetime import datetime

from sqlalchemy import Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TIMESTAMP


class UserModel(Base):
    __tablename__ = "User"
    __table_args__ = (
        UniqueConstraint("email"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column("passwordHash", Text)
    base_currency: Mapped[str] = mapped_column(
        "baseCurrency",
        Text,
        nullable=False,
        server_default=text("'CZK'::text"),
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)
