"""Account domain access policies."""

from app.modules.accounts.access import AuthorizedAccount, require_account_access

__all__ = ["AuthorizedAccount", "require_account_access"]
