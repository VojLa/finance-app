from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

PRISMA_NAMING_CONVENTION = {
    "ix": "%(table_name)s_%(column_0_N_name)s_idx",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "fk": "%(table_name)s_%(column_0_N_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    """Declarative metadata for schema objects mirrored from Prisma."""

    metadata = MetaData(naming_convention=PRISMA_NAMING_CONVENTION)
