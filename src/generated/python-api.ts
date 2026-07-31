// This file is generated. Do not edit manually.

export interface paths {
  "/": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Root */
    get: operations["root__get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/accounts": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** List Accounts */
    get: operations["list_accounts_api_v1_accounts_get"]
    put?: never
    /** Create Account */
    post: operations["create_account_api_v1_accounts_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/accounts/invites/accept": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Accept Account Invite */
    post: operations["accept_account_invite_api_v1_accounts_invites_accept_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/accounts/{account_id}": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    /** Update Account */
    patch: operations["update_account_api_v1_accounts__account_id__patch"]
    trace?: never
  }
  "/api/v1/accounts/{account_id}/archive": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Archive Account */
    post: operations["archive_account_api_v1_accounts__account_id__archive_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/accounts/{account_id}/holdings/rebuild": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Rebuild Holdings */
    post: operations["rebuild_holdings_api_v1_accounts__account_id__holdings_rebuild_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/accounts/{account_id}/imports": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** List Import Batches */
    get: operations["list_import_batches_api_v1_accounts__account_id__imports_get"]
    put?: never
    /** Create Import Batch */
    post: operations["create_import_batch_api_v1_accounts__account_id__imports_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/accounts/{account_id}/imports/{batch_id}": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Import Batch */
    get: operations["get_import_batch_api_v1_accounts__account_id__imports__batch_id__get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/accounts/{account_id}/imports/{batch_id}/classify": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Classify Import Batch */
    post: operations["classify_import_batch_api_v1_accounts__account_id__imports__batch_id__classify_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/accounts/{account_id}/imports/{batch_id}/deduplicate": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Deduplicate Import Batch */
    post: operations["deduplicate_import_batch_api_v1_accounts__account_id__imports__batch_id__deduplicate_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/accounts/{account_id}/imports/{batch_id}/file": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    /** Upload Import File */
    put: operations["upload_import_file_api_v1_accounts__account_id__imports__batch_id__file_put"]
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/accounts/{account_id}/imports/{batch_id}/normalize": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Normalize Import Batch */
    post: operations["normalize_import_batch_api_v1_accounts__account_id__imports__batch_id__normalize_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/accounts/{account_id}/imports/{batch_id}/parse": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Parse Import Batch */
    post: operations["parse_import_batch_api_v1_accounts__account_id__imports__batch_id__parse_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/accounts/{account_id}/imports/{batch_id}/post": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Post Import Batch */
    post: operations["post_import_batch_api_v1_accounts__account_id__imports__batch_id__post_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/accounts/{account_id}/invites": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** List Account Invites */
    get: operations["list_account_invites_api_v1_accounts__account_id__invites_get"]
    put?: never
    /** Create Account Invite */
    post: operations["create_account_invite_api_v1_accounts__account_id__invites_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/accounts/{account_id}/invites/{invite_id}": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    post?: never
    /** Revoke Account Invite */
    delete: operations["revoke_account_invite_api_v1_accounts__account_id__invites__invite_id__delete"]
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/accounts/{account_id}/members": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** List Account Members */
    get: operations["list_account_members_api_v1_accounts__account_id__members_get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/accounts/{account_id}/members/{member_id}": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    post?: never
    /** Remove Account Member */
    delete: operations["remove_account_member_api_v1_accounts__account_id__members__member_id__delete"]
    options?: never
    head?: never
    /** Update Account Member Role */
    patch: operations["update_account_member_role_api_v1_accounts__account_id__members__member_id__patch"]
    trace?: never
  }
  "/api/v1/accounts/{account_id}/restore": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Restore Account */
    post: operations["restore_account_api_v1_accounts__account_id__restore_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/accounts/{account_id}/snapshots/recalculate": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Recalculate Account Snapshot */
    post: operations["recalculate_account_snapshot_api_v1_accounts__account_id__snapshots_recalculate_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/auth/me": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /**
     * Get Current User
     * @description Return the database-backed identity represented by the internal token.
     */
    get: operations["get_current_user_api_v1_auth_me_get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/dashboard/snapshot": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Read Dashboard Snapshot */
    post: operations["read_dashboard_snapshot_api_v1_dashboard_snapshot_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/health/live": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Liveness */
    get: operations["liveness_api_v1_health_live_get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/health/ready": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Readiness */
    get: operations["readiness_api_v1_health_ready_get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/net-worth/snapshots/recalculate": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Recalculate Net Worth Snapshot */
    post: operations["recalculate_net_worth_snapshot_api_v1_net_worth_snapshots_recalculate_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/portfolio": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Portfolio */
    get: operations["get_portfolio_api_v1_portfolio_get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/portfolio/accounts/{account_id}/snapshot": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Read Portfolio Snapshot */
    get: operations["read_portfolio_snapshot_api_v1_portfolio_accounts__account_id__snapshot_get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/portfolio/snapshot": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Read Multi Account Portfolio Snapshot */
    post: operations["read_multi_account_portfolio_snapshot_api_v1_portfolio_snapshot_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/v1/snapshot-refresh/recalculate": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Recalculate User Snapshot Refresh */
    post: operations["recalculate_user_snapshot_refresh_api_v1_snapshot_refresh_recalculate_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
}
export type webhooks = Record<string, never>
export interface components {
  schemas: {
    /** AccountCreateRequest */
    AccountCreateRequest: {
      /** Color */
      color?: string | null
      /** Currency */
      currency: string
      /** Name */
      name: string
      /** Notes */
      notes?: string | null
      type: components["schemas"]["AccountType-Input"]
    }
    /** AccountInviteAcceptRequest */
    AccountInviteAcceptRequest: {
      /** Token */
      token: string
    }
    /** AccountInviteAcceptedResponse */
    AccountInviteAcceptedResponse: {
      /** Account Id */
      account_id: string
      /** Member Id */
      member_id: string
    }
    /** AccountInviteCreateRequest */
    AccountInviteCreateRequest: {
      /** Email */
      email: string
      /**
       * Expires In Hours
       * @default 72
       */
      expires_in_hours: number
      /** @default viewer */
      role: components["schemas"]["AccountMemberRole"]
    }
    /** AccountInviteCreatedResponse */
    AccountInviteCreatedResponse: {
      /** Accepted At */
      accepted_at: string | null
      /** Account Id */
      account_id: string
      /**
       * Created At
       * Format: date-time
       */
      created_at: string
      /** Email */
      email: string
      /**
       * Expires At
       * Format: date-time
       */
      expires_at: string
      /** Id */
      id: string
      /** Inviter Id */
      inviter_id: string
      /** Revoked At */
      revoked_at: string | null
      role: components["schemas"]["AccountMemberRole"]
      status: components["schemas"]["AccountInviteStatus"]
      /** Token */
      token: string
      /**
       * Updated At
       * Format: date-time
       */
      updated_at: string
    }
    /** AccountInviteResponse */
    AccountInviteResponse: {
      /** Accepted At */
      accepted_at: string | null
      /** Account Id */
      account_id: string
      /**
       * Created At
       * Format: date-time
       */
      created_at: string
      /** Email */
      email: string
      /**
       * Expires At
       * Format: date-time
       */
      expires_at: string
      /** Id */
      id: string
      /** Inviter Id */
      inviter_id: string
      /** Revoked At */
      revoked_at: string | null
      role: components["schemas"]["AccountMemberRole"]
      status: components["schemas"]["AccountInviteStatus"]
      /**
       * Updated At
       * Format: date-time
       */
      updated_at: string
    }
    /**
     * AccountInviteStatus
     * @enum {string}
     */
    AccountInviteStatus: "pending" | "accepted" | "revoked" | "expired"
    /** AccountMemberResponse */
    AccountMemberResponse: {
      /** Accepted At */
      accepted_at: string | null
      /**
       * Created At
       * Format: date-time
       */
      created_at: string
      /** Email */
      email: string
      /** Id */
      id: string
      /** Name */
      name: string | null
      relation_type: components["schemas"]["AccountRelationType"]
      role: components["schemas"]["AccountMemberRole"]
      /**
       * Updated At
       * Format: date-time
       */
      updated_at: string
      /** User Id */
      user_id: string
    }
    /**
     * AccountMemberRole
     * @enum {string}
     */
    AccountMemberRole: "owner" | "admin" | "viewer" | "editor"
    /** AccountMemberRoleUpdateRequest */
    AccountMemberRoleUpdateRequest: {
      role: components["schemas"]["AccountMemberRole"]
    }
    /**
     * AccountRelationType
     * @enum {string}
     */
    AccountRelationType: "owner" | "joint_owner" | "manager" | "beneficiary" | "collaborator"
    /** AccountResponse */
    AccountResponse: {
      /** Color */
      color: string | null
      /**
       * Created At
       * Format: date-time
       */
      created_at: string
      /** Currency */
      currency: string
      /** Id */
      id: string
      /** Is Archived */
      is_archived: boolean
      /** Name */
      name: string
      /** Notes */
      notes: string | null
      relation_type: components["schemas"]["AccountRelationType"]
      role: components["schemas"]["AccountMemberRole"]
      type: components["schemas"]["app__db__models__enums__AccountType"]
      /**
       * Updated At
       * Format: date-time
       */
      updated_at: string
    }
    /** AccountSnapshotRecalculateRequest */
    AccountSnapshotRecalculateRequest: {
      /** Outputcurrency */
      outputCurrency?: string | null
    }
    /** AccountSnapshotRecalculateResponse */
    AccountSnapshotRecalculateResponse: {
      /** Accountid */
      accountId: string
      /** Currency */
      currency: string
      granularity: components["schemas"]["app__db__models__enums__SnapshotGranularity"]
      /** Itemcount */
      itemCount: number
      /** Snapshotid */
      snapshotId: string
      /**
       * Status
       * @enum {string}
       */
      status: "created" | "replayed"
      /** Timestamp */
      timestamp: string
    }
    /** AccountSummary */
    AccountSummary: {
      /** Currency */
      currency: string
      /** Id */
      id: string
      /** Name */
      name: string
      /** Type */
      type: string
    }
    /**
     * AccountType
     * @enum {string}
     */
    "AccountType-Input":
      | "bank"
      | "cash"
      | "savings"
      | "broker"
      | "exchange"
      | "crypto_wallet"
      | "credit_card"
      | "loan"
      | "mortgage"
    /** AccountUpdateRequest */
    AccountUpdateRequest: {
      /** Color */
      color?: string | null
      /** Currency */
      currency?: string | null
      /** Name */
      name?: string | null
      /** Notes */
      notes?: string | null
    }
    /**
     * AssetType
     * @description Asset classification copied into the portfolio presentation contract.
     * @enum {string}
     */
    AssetType: "stock" | "etf" | "crypto" | "commodity" | "cash" | "bond" | "other"
    /** CurrentUserResponse */
    CurrentUserResponse: {
      /** Email */
      email: string
      /** Id */
      id: string
      /** Name */
      name?: string | null
    }
    /** DashboardAccountCardResponse */
    DashboardAccountCardResponse: {
      /** Accountcurrency */
      accountCurrency: string
      /** Accountid */
      accountId: string
      accountType: components["schemas"]["app__modules__portfolio_snapshot__models__AccountType"]
      /** Cashvalue */
      cashValue: string
      /** Investmentvalue */
      investmentValue: string
      /** Liabilitiesvalue */
      liabilitiesValue: string
      /** Name */
      name: string
      /** Outputcurrency */
      outputCurrency: string
      /** Positioncount */
      positionCount: number
      /** Snapshotid */
      snapshotId: string
      /** Totalvalue */
      totalValue: string
      /** Unrealizedpnlvalue */
      unrealizedPnlValue: string
    }
    /** DashboardAssetTypeAllocationResponse */
    DashboardAssetTypeAllocationResponse: {
      /** Accountcount */
      accountCount: number
      /** Allocationpct */
      allocationPct: string
      assetType: components["schemas"]["AssetType"]
      /** Positioncount */
      positionCount: number
      /** Value */
      value: string
    }
    /** DashboardSnapshotResponse */
    DashboardSnapshotResponse: {
      /** Accounts */
      accounts: components["schemas"]["DashboardAccountCardResponse"][]
      /** Assettypeallocations */
      assetTypeAllocations: components["schemas"]["DashboardAssetTypeAllocationResponse"][]
      /** Calculationversion */
      calculationVersion: number
      /** Currency */
      currency: string
      granularity: components["schemas"]["app__modules__portfolio_snapshot__models__SnapshotGranularity"]
      summary: components["schemas"]["DashboardSnapshotSummaryResponse"]
      /** Timestamp */
      timestamp: string
      /** Toppositions */
      topPositions: components["schemas"]["DashboardTopPositionResponse"][]
    }
    /** DashboardSnapshotSummaryResponse */
    DashboardSnapshotSummaryResponse: {
      /** Accountcount */
      accountCount: number
      /** Assetsvalue */
      assetsValue: string
      /** Cashvalue */
      cashValue: string
      /** Feesvalue */
      feesValue: string
      /** Investmentaccountcount */
      investmentAccountCount: number
      /** Investmentcostbasis */
      investmentCostBasis: string
      /** Investmentvalue */
      investmentValue: string
      /** Liabilitiesvalue */
      liabilitiesValue: string
      /** Liabilityaccountcount */
      liabilityAccountCount: number
      /** Netdepositsvalue */
      netDepositsValue: string
      /** Positioncount */
      positionCount: number
      /** Realizedpnlvalue */
      realizedPnlValue: string
      /** Taxesvalue */
      taxesValue: string
      /** Totalvalue */
      totalValue: string
      /** Unrealizedpnlvalue */
      unrealizedPnlValue: string
    }
    /** DashboardTopPositionResponse */
    DashboardTopPositionResponse: {
      /** Accountid */
      accountId: string
      /** Allocationpct */
      allocationPct: string
      /** Assetid */
      assetId: string
      assetType: components["schemas"]["AssetType"]
      /** Listingid */
      listingId: string
      /** Name */
      name: string
      /** Symbol */
      symbol: string
      /** Unrealizedpnl */
      unrealizedPnl: string
      /** Value */
      value: string
      /** Valuecurrency */
      valueCurrency: string
    }
    /** ErrorDetail */
    ErrorDetail: {
      /** Code */
      code: string
      /** Message */
      message: string
      /** Request Id */
      request_id?: string | null
    }
    /** ErrorResponse */
    ErrorResponse: {
      error: components["schemas"]["ErrorDetail"]
    }
    /**
     * ExactAccountSnapshotRequest
     * @description One explicit account identity and optional snapshot lineage guard.
     */
    ExactAccountSnapshotRequest: {
      /** Accountid */
      accountId: string
      /** Snapshotid */
      snapshotId?: string | null
    }
    /**
     * ExactPortfolioSnapshotSetRequest
     * @description Complete explicit selector set shared by portfolio and dashboard APIs.
     */
    ExactPortfolioSnapshotSetRequest: {
      /** Accounts */
      accounts: components["schemas"]["ExactAccountSnapshotRequest"][]
      /** Calculationversion */
      calculationVersion: number
      /** Currency */
      currency: string
      granularity: components["schemas"]["SnapshotGranularity-Input"]
      /**
       * Timestamp
       * Format: date-time
       */
      timestamp: string
    }
    /** HTTPValidationError */
    HTTPValidationError: {
      /** Detail */
      detail?: components["schemas"]["ValidationError"][]
    }
    /** HoldingRebuildResponse */
    HoldingRebuildResponse: {
      /** Account Id */
      account_id: string
      /** Created */
      created: number
      /** Deleted */
      deleted: number
      /** Rebuilt At */
      rebuilt_at: string | null
      /** Replayed */
      replayed: boolean
      /** Total */
      total: number
      /** Updated */
      updated: number
    }
    /** HoldingSummary */
    HoldingSummary: {
      /** Account Currency */
      account_currency: string
      /** Account Id */
      account_id: string
      /** Account Name */
      account_name: string | null
      /** Asset Type */
      asset_type: string
      /** Avg Buy Price */
      avg_buy_price: number
      /** Cost Value */
      cost_value: number
      /** Cost Value Account Currency */
      cost_value_account_currency: number
      /** Currency */
      currency: string
      /** Id */
      id: string
      /** Listing Id */
      listing_id: string | null
      /** Name */
      name: string | null
      /** Quantity */
      quantity: number
      /** Symbol */
      symbol: string
    }
    /** ImportBatchCreateRequest */
    ImportBatchCreateRequest: {
      /** Checksum */
      checksum: string
      /** File Encoding */
      file_encoding?: string | null
      /** File Size */
      file_size?: number | null
      /** Filename */
      filename: string
      source: components["schemas"]["ImportSource"]
    }
    /** ImportBatchResponse */
    ImportBatchResponse: {
      /** Account Id */
      account_id: string
      /** Checksum */
      checksum: string
      /** Completed At */
      completed_at: string | null
      /**
       * Created At
       * Format: date-time
       */
      created_at: string
      /** File Encoding */
      file_encoding: string | null
      /** File Size */
      file_size: number | null
      /** Filename */
      filename: string
      /** Id */
      id: string
      /** Rows Imported */
      rows_imported: number | null
      /** Rows Skipped */
      rows_skipped: number | null
      /** Rows Total */
      rows_total: number | null
      source: components["schemas"]["ImportSource"]
      status: components["schemas"]["ImportStatus"]
    }
    /** ImportClassifyResponse */
    ImportClassifyResponse: {
      /** Batch Id */
      batch_id: string
      /** Rows Classified */
      rows_classified: number
      /** Rows Duplicate */
      rows_duplicate: number
      /** Rows Failed */
      rows_failed: number
      /** Rows Needs Review */
      rows_needs_review: number
      /** Rows Skipped */
      rows_skipped: number
      /** Rows Total */
      rows_total: number
      status: components["schemas"]["ImportStatus"]
    }
    /** ImportDeduplicateResponse */
    ImportDeduplicateResponse: {
      /** Batch Id */
      batch_id: string
      /** Rows Duplicate */
      rows_duplicate: number
      /** Rows Failed */
      rows_failed: number
      /** Rows Needs Review */
      rows_needs_review: number
      /** Rows Total */
      rows_total: number
      /** Rows Unique */
      rows_unique: number
      status: components["schemas"]["ImportStatus"]
    }
    /** ImportNormalizeResponse */
    ImportNormalizeResponse: {
      /** Batch Id */
      batch_id: string
      /** Rows Failed */
      rows_failed: number
      /** Rows Needs Review */
      rows_needs_review: number
      /** Rows Normalized */
      rows_normalized: number
      /** Rows Total */
      rows_total: number
      status: components["schemas"]["ImportStatus"]
    }
    /** ImportParseResponse */
    ImportParseResponse: {
      /** Batch Id */
      batch_id: string
      /** Rows Failed */
      rows_failed: number
      /** Rows Pending */
      rows_pending: number
      /** Rows Total */
      rows_total: number
      status: components["schemas"]["ImportStatus"]
    }
    /** ImportPostResponse */
    ImportPostResponse: {
      /** Batch Id */
      batch_id: string
      /**
       * Completed At
       * Format: date-time
       */
      completed_at: string
      /** Replayed */
      replayed: boolean
      /** Rows Imported */
      rows_imported: number
      /** Rows Skipped */
      rows_skipped: number
      /** Rows Total */
      rows_total: number
      snapshot_refresh_status: components["schemas"]["ImportSnapshotRefreshStatus"]
      status: components["schemas"]["ImportStatus"]
    }
    /**
     * ImportSnapshotRefreshStatus
     * @enum {string}
     */
    ImportSnapshotRefreshStatus:
      | "created"
      | "replayed"
      | "not_required"
      | "unavailable"
      | "conflict"
    /**
     * ImportSource
     * @enum {string}
     */
    ImportSource: "raiffeisenbank" | "trading212" | "anycoin" | "manual"
    /**
     * ImportStatus
     * @enum {string}
     */
    ImportStatus:
      | "pending"
      | "processing"
      | "completed"
      | "failed"
      | "partially_completed"
      | "cancelled"
    /** ImportUploadResponse */
    ImportUploadResponse: {
      /** Batch Id */
      batch_id: string
      /** Checksum */
      checksum: string
      /** Idempotent */
      idempotent: boolean
      /** Size */
      size: number
      /** Stored */
      stored: boolean
    }
    /** LivenessResponse */
    LivenessResponse: {
      /** Service */
      service: string
      /**
       * Status
       * @constant
       */
      status: "ok"
    }
    /** MultiAccountPortfolioAccountResponse */
    MultiAccountPortfolioAccountResponse: {
      account: components["schemas"]["PortfolioSnapshotAccountResponse"]
      /** Positions */
      positions: components["schemas"]["PortfolioSnapshotPositionResponse"][]
      /** Snapshotid */
      snapshotId: string
      source: components["schemas"]["SnapshotSource"]
      summary: components["schemas"]["PortfolioSnapshotSummaryResponse"]
    }
    /** MultiAccountPortfolioResponse */
    MultiAccountPortfolioResponse: {
      /** Accounts */
      accounts: components["schemas"]["MultiAccountPortfolioAccountResponse"][]
      /** Calculationversion */
      calculationVersion: number
      /** Currency */
      currency: string
      granularity: components["schemas"]["app__modules__portfolio_snapshot__models__SnapshotGranularity"]
      summary: components["schemas"]["MultiAccountPortfolioSummaryResponse"]
      /** Timestamp */
      timestamp: string
    }
    /** MultiAccountPortfolioSummaryResponse */
    MultiAccountPortfolioSummaryResponse: {
      /** Accountcount */
      accountCount: number
      /** Cashvalue */
      cashValue: string
      /** Feesvalue */
      feesValue: string
      /** Investmentcostbasis */
      investmentCostBasis: string
      /** Investmentvalue */
      investmentValue: string
      /** Liabilitiesvalue */
      liabilitiesValue: string
      /** Netdepositsvalue */
      netDepositsValue: string
      /** Positioncount */
      positionCount: number
      /** Realizedpnlvalue */
      realizedPnlValue: string
      /** Taxesvalue */
      taxesValue: string
      /** Totalvalue */
      totalValue: string
      /** Unrealizedpnlvalue */
      unrealizedPnlValue: string
    }
    /** NetWorthSnapshotRecalculateResponse */
    NetWorthSnapshotRecalculateResponse: {
      /** Accountcount */
      accountCount: number
      /** Currency */
      currency: string
      granularity: components["schemas"]["app__db__models__enums__SnapshotGranularity"]
      /** Selectedaccountsnapshotcount */
      selectedAccountSnapshotCount: number
      /** Snapshotid */
      snapshotId: string
      /**
       * Status
       * @enum {string}
       */
      status: "created" | "replayed"
      /** Timestamp */
      timestamp: string
    }
    /** PortfolioSnapshotAccountResponse */
    PortfolioSnapshotAccountResponse: {
      /** Accountid */
      accountId: string
      accountType: components["schemas"]["app__modules__portfolio_snapshot__models__AccountType"]
      /** Currency */
      currency: string
      /** Name */
      name: string
    }
    /** PortfolioSnapshotPositionResponse */
    PortfolioSnapshotPositionResponse: {
      /** Allocationpct */
      allocationPct: string
      /** Assetid */
      assetId: string
      assetType: components["schemas"]["AssetType"]
      /** Costbasis */
      costBasis: string
      /** Costcurrency */
      costCurrency: string
      /** Listingid */
      listingId: string
      /** Name */
      name: string
      /** Nativecostbasis */
      nativeCostBasis: string
      /** Nativecostcurrency */
      nativeCostCurrency: string
      /** Nativevalue */
      nativeValue: string
      /** Nativevaluecurrency */
      nativeValueCurrency: string
      /** Pricecurrency */
      priceCurrency: string
      /** Priceperunit */
      pricePerUnit: string
      /** Pricetimestamp */
      priceTimestamp: string
      /** Quantity */
      quantity: string
      /** Symbol */
      symbol: string
      /** Unrealizedpnl */
      unrealizedPnl: string
      /** Value */
      value: string
      /** Valuecurrency */
      valueCurrency: string
    }
    /** PortfolioSnapshotResponse */
    PortfolioSnapshotResponse: {
      account: components["schemas"]["PortfolioSnapshotAccountResponse"]
      /** Calculationversion */
      calculationVersion: number
      /** Currency */
      currency: string
      granularity: components["schemas"]["app__modules__portfolio_snapshot__models__SnapshotGranularity"]
      /** Positions */
      positions: components["schemas"]["PortfolioSnapshotPositionResponse"][]
      /** Snapshotid */
      snapshotId: string
      source: components["schemas"]["SnapshotSource"]
      summary: components["schemas"]["PortfolioSnapshotSummaryResponse"]
      /** Timestamp */
      timestamp: string
    }
    /** PortfolioSnapshotSummaryResponse */
    PortfolioSnapshotSummaryResponse: {
      /** Cashvalue */
      cashValue: string
      /** Feesvalue */
      feesValue: string
      /** Investmentcostbasis */
      investmentCostBasis: string
      /** Investmentvalue */
      investmentValue: string
      /** Liabilitiesvalue */
      liabilitiesValue: string
      /** Netdepositsvalue */
      netDepositsValue: string
      /** Positioncount */
      positionCount: number
      /** Realizedpnlvalue */
      realizedPnlValue: string
      /** Taxesvalue */
      taxesValue: string
      /** Totalvalue */
      totalValue: string
      /** Unrealizedpnlvalue */
      unrealizedPnlValue: string
    }
    /** PortfolioSummary */
    PortfolioSummary: {
      /** Accounts */
      accounts: components["schemas"]["AccountSummary"][]
      /** Display Currency */
      display_currency: string
      /** Holdings */
      holdings: components["schemas"]["HoldingSummary"][]
      /** Total Cost */
      total_cost: number
      /** Warnings */
      warnings?: string[]
    }
    /** ReadinessDependencies */
    ReadinessDependencies: {
      /**
       * Database
       * @enum {string}
       */
      database: "available" | "unavailable"
    }
    /** ReadinessResponse */
    ReadinessResponse: {
      dependencies: components["schemas"]["ReadinessDependencies"]
      /**
       * Status
       * @enum {string}
       */
      status: "ready" | "not_ready"
    }
    /** RootResponse */
    RootResponse: {
      /** Endpoints */
      endpoints: string[]
      /** Service */
      service: string
      /** Version */
      version: string
    }
    /**
     * SnapshotGranularity
     * @description Persisted AccountSnapshot bucket alignment.
     * @enum {string}
     */
    "SnapshotGranularity-Input": "minute" | "hour" | "day" | "week" | "month"
    /** SnapshotRefreshAccountSelectionResponse */
    SnapshotRefreshAccountSelectionResponse: {
      /** Accountid */
      accountId: string
      /** Snapshotid */
      snapshotId: string
    }
    /**
     * SnapshotSource
     * @description Persisted AccountSnapshot creation source.
     * @enum {string}
     */
    SnapshotSource:
      | "import_event"
      | "price_refresh"
      | "holdings_recalculation"
      | "scheduled"
      | "manual_recalculation"
    /** UserSnapshotRefreshRecalculateResponse */
    UserSnapshotRefreshRecalculateResponse: {
      /** Accounts */
      accounts: components["schemas"]["SnapshotRefreshAccountSelectionResponse"][]
      /** Calculationversion */
      calculationVersion: number
      /** Createdaccountsnapshotcount */
      createdAccountSnapshotCount: number
      /** Currency */
      currency: string
      granularity: components["schemas"]["app__db__models__enums__SnapshotGranularity"]
      /** Networthsnapshotid */
      netWorthSnapshotId: string
      /**
       * Networthstatus
       * @enum {string}
       */
      netWorthStatus: "created" | "replayed"
      /** Refreshaccountcount */
      refreshAccountCount: number
      /** Replayedaccountsnapshotcount */
      replayedAccountSnapshotCount: number
      /** Reuseonlyaccountcount */
      reuseOnlyAccountCount: number
      /** Reusedaccountsnapshotcount */
      reusedAccountSnapshotCount: number
      /** Selectedaccountsnapshotcount */
      selectedAccountSnapshotCount: number
      /** Timestamp */
      timestamp: string
    }
    /** ValidationError */
    ValidationError: {
      /** Context */
      ctx?: Record<string, never>
      /** Input */
      input?: unknown
      /** Location */
      loc: (string | number)[]
      /** Message */
      msg: string
      /** Error Type */
      type: string
    }
    /**
     * AccountType
     * @enum {string}
     */
    app__db__models__enums__AccountType:
      | "bank"
      | "cash"
      | "savings"
      | "broker"
      | "exchange"
      | "crypto_wallet"
      | "credit_card"
      | "loan"
      | "mortgage"
    /**
     * SnapshotGranularity
     * @enum {string}
     */
    app__db__models__enums__SnapshotGranularity: "minute" | "hour" | "day" | "week" | "month"
    /**
     * AccountType
     * @description Account types represented by validated AccountSnapshot evidence.
     * @enum {string}
     */
    app__modules__portfolio_snapshot__models__AccountType:
      | "bank"
      | "cash"
      | "savings"
      | "broker"
      | "exchange"
      | "crypto_wallet"
      | "credit_card"
      | "loan"
      | "mortgage"
    /**
     * SnapshotGranularity
     * @description Persisted AccountSnapshot bucket alignment.
     * @enum {string}
     */
    app__modules__portfolio_snapshot__models__SnapshotGranularity:
      | "minute"
      | "hour"
      | "day"
      | "week"
      | "month"
  }
  responses: never
  parameters: never
  requestBodies: never
  headers: never
  pathItems: never
}
export type $defs = Record<string, never>
export interface operations {
  root__get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["RootResponse"]
        }
      }
    }
  }
  list_accounts_api_v1_accounts_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["AccountResponse"][]
        }
      }
    }
  }
  create_account_api_v1_accounts_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["AccountCreateRequest"]
      }
    }
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["AccountResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  accept_account_invite_api_v1_accounts_invites_accept_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["AccountInviteAcceptRequest"]
      }
    }
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["AccountInviteAcceptedResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  update_account_api_v1_accounts__account_id__patch: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["AccountUpdateRequest"]
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["AccountResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  archive_account_api_v1_accounts__account_id__archive_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["AccountResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  rebuild_holdings_api_v1_accounts__account_id__holdings_rebuild_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HoldingRebuildResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  list_import_batches_api_v1_accounts__account_id__imports_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ImportBatchResponse"][]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  create_import_batch_api_v1_accounts__account_id__imports_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["ImportBatchCreateRequest"]
      }
    }
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ImportBatchResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  get_import_batch_api_v1_accounts__account_id__imports__batch_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
        batch_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ImportBatchResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  classify_import_batch_api_v1_accounts__account_id__imports__batch_id__classify_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
        batch_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ImportClassifyResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  deduplicate_import_batch_api_v1_accounts__account_id__imports__batch_id__deduplicate_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
        batch_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ImportDeduplicateResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  upload_import_file_api_v1_accounts__account_id__imports__batch_id__file_put: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
        batch_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        "application/octet-stream": string
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ImportUploadResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  normalize_import_batch_api_v1_accounts__account_id__imports__batch_id__normalize_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
        batch_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ImportNormalizeResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  parse_import_batch_api_v1_accounts__account_id__imports__batch_id__parse_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
        batch_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ImportParseResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  post_import_batch_api_v1_accounts__account_id__imports__batch_id__post_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
        batch_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ImportPostResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  list_account_invites_api_v1_accounts__account_id__invites_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["AccountInviteResponse"][]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  create_account_invite_api_v1_accounts__account_id__invites_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["AccountInviteCreateRequest"]
      }
    }
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["AccountInviteCreatedResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  revoke_account_invite_api_v1_accounts__account_id__invites__invite_id__delete: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
        invite_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      204: {
        headers: {
          [name: string]: unknown
        }
        content?: never
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  list_account_members_api_v1_accounts__account_id__members_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["AccountMemberResponse"][]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  remove_account_member_api_v1_accounts__account_id__members__member_id__delete: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
        member_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      204: {
        headers: {
          [name: string]: unknown
        }
        content?: never
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  update_account_member_role_api_v1_accounts__account_id__members__member_id__patch: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
        member_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["AccountMemberRoleUpdateRequest"]
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["AccountMemberResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  restore_account_api_v1_accounts__account_id__restore_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["AccountResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  recalculate_account_snapshot_api_v1_accounts__account_id__snapshots_recalculate_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        account_id: string
      }
      cookie?: never
    }
    requestBody?: {
      content: {
        "application/json": components["schemas"]["AccountSnapshotRecalculateRequest"] | null
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["AccountSnapshotRecalculateResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  get_current_user_api_v1_auth_me_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["CurrentUserResponse"]
        }
      }
      /** @description Missing, invalid, or expired session token. */
      401: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ErrorResponse"]
        }
      }
      /** @description Authentication is not configured. */
      503: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ErrorResponse"]
        }
      }
    }
  }
  read_dashboard_snapshot_api_v1_dashboard_snapshot_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["ExactPortfolioSnapshotSetRequest"]
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["DashboardSnapshotResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  liveness_api_v1_health_live_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["LivenessResponse"]
        }
      }
    }
  }
  readiness_api_v1_health_ready_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ReadinessResponse"]
        }
      }
      /** @description Service Unavailable */
      503: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ReadinessResponse"]
        }
      }
    }
  }
  recalculate_net_worth_snapshot_api_v1_net_worth_snapshots_recalculate_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["NetWorthSnapshotRecalculateResponse"]
        }
      }
    }
  }
  get_portfolio_api_v1_portfolio_get: {
    parameters: {
      query?: {
        account_id?: string | null
      }
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["PortfolioSummary"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  read_portfolio_snapshot_api_v1_portfolio_accounts__account_id__snapshot_get: {
    parameters: {
      query: {
        timestamp: string
        granularity: components["schemas"]["SnapshotGranularity-Input"]
        currency: string
        calculationVersion: number
        snapshotId?: string | null
      }
      header?: never
      path: {
        account_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["PortfolioSnapshotResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  read_multi_account_portfolio_snapshot_api_v1_portfolio_snapshot_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["ExactPortfolioSnapshotSetRequest"]
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["MultiAccountPortfolioResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  recalculate_user_snapshot_refresh_api_v1_snapshot_refresh_recalculate_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["UserSnapshotRefreshRecalculateResponse"]
        }
      }
    }
  }
}
