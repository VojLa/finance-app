from sqlalchemy.engine import URL, make_url

_SUPPORTED_DRIVERS = {"postgres", "postgresql", "postgresql+asyncpg"}


def normalize_database_url(database_url: str) -> URL:
    """Convert a PostgreSQL URL to SQLAlchemy's asyncpg dialect.

    Prisma accepts a ``schema`` query parameter that libpq and asyncpg do not use for
    selecting the default schema. The physical schema is explicitly mapped as ``public``.
    """

    url = make_url(database_url)
    if url.drivername not in _SUPPORTED_DRIVERS:
        raise ValueError(f"Unsupported database driver: {url.drivername}")

    query = {key: value for key, value in url.query.items() if key != "schema"}
    return url.set(drivername="postgresql+asyncpg", query=query)
