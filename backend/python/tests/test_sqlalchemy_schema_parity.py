import os

import pytest

from scripts.sqlalchemy_schema import compare_snapshots, live_snapshot, local_snapshot

DATABASE_URL = os.getenv("DATABASE_URL")


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
async def test_complete_sqlalchemy_metadata_matches_prisma_migrated_postgresql() -> None:
    assert DATABASE_URL is not None

    reflected = await live_snapshot(DATABASE_URL)

    assert compare_snapshots(local_snapshot(), reflected) == 0
