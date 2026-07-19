from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.repository import AccountRepository


class _Rows:
    def all(self) -> list[object]:
        return []


@pytest.mark.asyncio
async def test_list_accessible_filters_membership_and_archived_accounts_in_stable_order() -> None:
    execute = AsyncMock(return_value=_Rows())
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    session_mock = cast(AsyncMock, session)
    session_mock.configure_mock(execute=execute)

    result = await AccountRepository(session).list_accessible("authenticated-user")

    assert result == []
    assert execute.await_args is not None
    statement = execute.await_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert '"AccountMember"."userId" = \'authenticated-user\'' in compiled
    assert 'public."AccountMember"."accountId" = public."Account".id' in compiled
    assert 'public."Account"."isArchived" IS false' in compiled
    assert 'ORDER BY public."Account"."createdAt" ASC, public."Account".id ASC' in compiled
