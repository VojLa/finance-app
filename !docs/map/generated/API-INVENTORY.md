<!--
  GENERATED FILE — created by scripts/docs/generate_api_inventory.py.
  Do not edit manually; run the generator instead.
-->

# API Inventory

**Operations:** 61

| Method | Path | Operation ID | Summary |

| --- | --- | --- | --- |

| GET | `/` | `root__get` | Root |

| GET | `/api/v1/accounts` | `list_accounts_api_v1_accounts_get` | List Accounts |

| POST | `/api/v1/accounts` | `create_account_api_v1_accounts_post` | Create Account |

| POST | `/api/v1/accounts/invites/accept` | `accept_account_invite_api_v1_accounts_invites_accept_post` | Accept Account Invite |

| PATCH | `/api/v1/accounts/{account_id}` | `update_account_api_v1_accounts__account_id__patch` | Update Account |

| POST | `/api/v1/accounts/{account_id}/archive` | `archive_account_api_v1_accounts__account_id__archive_post` | Archive Account |

| POST | `/api/v1/accounts/{account_id}/holdings/rebuild` | `rebuild_holdings_api_v1_accounts__account_id__holdings_rebuild_post` | Rebuild Holdings |

| GET | `/api/v1/accounts/{account_id}/imports` | `list_import_batches_api_v1_accounts__account_id__imports_get` | List Import Batches |

| POST | `/api/v1/accounts/{account_id}/imports` | `create_import_batch_api_v1_accounts__account_id__imports_post` | Create Import Batch |

| POST | `/api/v1/accounts/{account_id}/imports/jobs` | `start_import_job_api_v1_accounts__account_id__imports_jobs_post` | Start Import Job |

| GET | `/api/v1/accounts/{account_id}/imports/jobs/{job_id}` | `get_import_job_api_v1_accounts__account_id__imports_jobs__job_id__get` | Get Import Job |

| POST | `/api/v1/accounts/{account_id}/imports/jobs/{job_id}/retry` | `retry_import_job_api_v1_accounts__account_id__imports_jobs__job_id__retry_post` | Retry Import Job |

| GET | `/api/v1/accounts/{account_id}/imports/{batch_id}` | `get_import_batch_api_v1_accounts__account_id__imports__batch_id__get` | Get Import Batch |

| POST | `/api/v1/accounts/{account_id}/imports/{batch_id}/canonical-post` | `canonical_post_import_batch_api_v1_accounts__account_id__imports__batch_id__canonical_post_post` | Canonical Post Import Batch |

| POST | `/api/v1/accounts/{account_id}/imports/{batch_id}/classify` | `classify_import_batch_api_v1_accounts__account_id__imports__batch_id__classify_post` | Classify Import Batch |

| POST | `/api/v1/accounts/{account_id}/imports/{batch_id}/deduplicate` | `deduplicate_import_batch_api_v1_accounts__account_id__imports__batch_id__deduplicate_post` | Deduplicate Import Batch |

| PUT | `/api/v1/accounts/{account_id}/imports/{batch_id}/file` | `upload_import_file_api_v1_accounts__account_id__imports__batch_id__file_put` | Upload Import File |

| POST | `/api/v1/accounts/{account_id}/imports/{batch_id}/normalize` | `normalize_import_batch_api_v1_accounts__account_id__imports__batch_id__normalize_post` | Normalize Import Batch |

| POST | `/api/v1/accounts/{account_id}/imports/{batch_id}/parse` | `parse_import_batch_api_v1_accounts__account_id__imports__batch_id__parse_post` | Parse Import Batch |

| POST | `/api/v1/accounts/{account_id}/imports/{batch_id}/post` | `post_import_batch_api_v1_accounts__account_id__imports__batch_id__post_post` | Post Import Batch |

| GET | `/api/v1/accounts/{account_id}/invites` | `list_account_invites_api_v1_accounts__account_id__invites_get` | List Account Invites |

| POST | `/api/v1/accounts/{account_id}/invites` | `create_account_invite_api_v1_accounts__account_id__invites_post` | Create Account Invite |

| DELETE | `/api/v1/accounts/{account_id}/invites/{invite_id}` | `revoke_account_invite_api_v1_accounts__account_id__invites__invite_id__delete` | Revoke Account Invite |

| POST | `/api/v1/accounts/{account_id}/liability-balances` | `create_manual_liability_balance_api_v1_accounts__account_id__liability_balances_post` | Create Manual Liability Balance |

| GET | `/api/v1/accounts/{account_id}/members` | `list_account_members_api_v1_accounts__account_id__members_get` | List Account Members |

| PATCH | `/api/v1/accounts/{account_id}/members/{member_id}` | `update_account_member_role_api_v1_accounts__account_id__members__member_id__patch` | Update Account Member Role |

| DELETE | `/api/v1/accounts/{account_id}/members/{member_id}` | `remove_account_member_api_v1_accounts__account_id__members__member_id__delete` | Remove Account Member |

| POST | `/api/v1/accounts/{account_id}/restore` | `restore_account_api_v1_accounts__account_id__restore_post` | Restore Account |

| POST | `/api/v1/accounts/{account_id}/snapshots/recalculate` | `recalculate_account_snapshot_api_v1_accounts__account_id__snapshots_recalculate_post` | Recalculate Account Snapshot |

| POST | `/api/v1/auth/credentials/verify` | `verify_credentials_api_v1_auth_credentials_verify_post` | Verify Credentials |

| GET | `/api/v1/auth/me` | `get_current_user_api_v1_auth_me_get` | Get Current User |

| PUT | `/api/v1/auth/me/base-currency` | `change_base_currency_api_v1_auth_me_base_currency_put` | Change Base Currency |

| PUT | `/api/v1/auth/password` | `change_password_api_v1_auth_password_put` | Change Password |

| POST | `/api/v1/auth/register` | `register_user_api_v1_auth_register_post` | Register User |

| GET | `/api/v1/budgets/monthly` | `get_monthly_budget_api_v1_budgets_monthly_get` | Get Monthly Budget |

| PUT | `/api/v1/budgets/monthly` | `save_monthly_budget_api_v1_budgets_monthly_put` | Save Monthly Budget |

| GET | `/api/v1/categories` | `list_categories_api_v1_categories_get` | List Categories |

| POST | `/api/v1/categories` | `create_category_api_v1_categories_post` | Create Category |

| PATCH | `/api/v1/categories/{category_id}` | `update_category_api_v1_categories__category_id__patch` | Update Category |

| DELETE | `/api/v1/categories/{category_id}` | `delete_category_api_v1_categories__category_id__delete` | Delete Category |

| POST | `/api/v1/dashboard/current` | `read_current_dashboard_api_v1_dashboard_current_post` | Read Current Dashboard |

| POST | `/api/v1/dashboard/published` | `read_published_dashboard_api_v1_dashboard_published_post` | Read Published Dashboard |

| POST | `/api/v1/dashboard/snapshot` | `read_dashboard_snapshot_api_v1_dashboard_snapshot_post` | Read Dashboard Snapshot |

| GET | `/api/v1/health/live` | `liveness_api_v1_health_live_get` | Liveness |

| GET | `/api/v1/health/ready` | `readiness_api_v1_health_ready_get` | Readiness |

| POST | `/api/v1/investments/manual` | `create_manual_investment_api_v1_investments_manual_post` | Create Manual Investment |

| GET | `/api/v1/investments/symbols/{symbol}` | `read_symbol_detail_api_v1_investments_symbols__symbol__get` | Read Symbol Detail |

| POST | `/api/v1/net-worth/snapshots/recalculate` | `recalculate_net_worth_snapshot_api_v1_net_worth_snapshots_recalculate_post` | Recalculate Net Worth Snapshot |

| GET | `/api/v1/operational-dashboard` | `get_operational_dashboard_api_v1_operational_dashboard_get` | Get Operational Dashboard |

| GET | `/api/v1/portfolio` | `get_portfolio_api_v1_portfolio_get` | Get Portfolio |

| GET | `/api/v1/portfolio/accounts/{account_id}/snapshot` | `read_portfolio_snapshot_api_v1_portfolio_accounts__account_id__snapshot_get` | Read Portfolio Snapshot |

| POST | `/api/v1/portfolio/current` | `read_current_portfolio_api_v1_portfolio_current_post` | Read Current Portfolio |

| GET | `/api/v1/portfolio/history` | `read_portfolio_history_api_v1_portfolio_history_get` | Read Portfolio History |

| POST | `/api/v1/portfolio/published` | `read_published_portfolio_api_v1_portfolio_published_post` | Read Published Portfolio |

| POST | `/api/v1/portfolio/snapshot` | `read_multi_account_portfolio_snapshot_api_v1_portfolio_snapshot_post` | Read Multi Account Portfolio Snapshot |

| GET | `/api/v1/read-model-version` | `read_model_version_api_v1_read_model_version_get` | Read Model Version |

| POST | `/api/v1/snapshot-refresh/recalculate` | `recalculate_user_snapshot_refresh_api_v1_snapshot_refresh_recalculate_post` | Recalculate User Snapshot Refresh |

| GET | `/api/v1/transactions` | `list_transactions_api_v1_transactions_get` | List Transactions |

| POST | `/api/v1/transactions` | `create_transaction_api_v1_transactions_post` | Create Transaction |

| PATCH | `/api/v1/transactions/{transaction_id}` | `update_transaction_api_v1_transactions__transaction_id__patch` | Update Transaction |

| DELETE | `/api/v1/transactions/{transaction_id}` | `delete_transaction_api_v1_transactions__transaction_id__delete` | Delete Transaction |
