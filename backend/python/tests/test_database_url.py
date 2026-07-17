import pytest

from app.db.url import normalize_database_url


def render(database_url: str) -> str:
    return normalize_database_url(database_url).render_as_string(hide_password=False)


def test_normalize_database_url_uses_asyncpg_and_removes_prisma_schema() -> None:
    assert (
        render("postgresql://user:password@localhost:5432/app?schema=public&sslmode=require")
        == "postgresql+asyncpg://user:password@localhost:5432/app?sslmode=require"
    )


def test_normalize_database_url_accepts_postgres_alias() -> None:
    assert render("postgres://user:password@localhost/app") == (
        "postgresql+asyncpg://user:password@localhost/app"
    )


def test_normalize_database_url_preserves_escaped_credentials() -> None:
    assert render("postgresql://user:p%40ss%2Fword@localhost/app") == (
        "postgresql+asyncpg://user:p%40ss%2Fword@localhost/app"
    )


def test_normalize_database_url_rejects_other_drivers() -> None:
    with pytest.raises(ValueError, match="Unsupported database driver"):
        normalize_database_url("sqlite:///local.db")
