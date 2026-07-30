# Step 5K final coordinated snapshot-refresh audit

## Audit method

This document is the traceability record for the final 5K audit. A contract is
marked `PASS` only after the named test has been inspected for the stated
invariant and the recorded test command has completed successfully. A test
name by itself is not treated as evidence.

The matrix began unverified. The final state below records only completed
evidence. Test names appear in each contract row; their
exact file, test type, command result and isolated PostgreSQL result are in the
verification ledger following the matrix.

## Traceability matrix

| Contract ID | Owner module | Production files | Unit tests | PostgreSQL tests | Public API tests | Expected invariant | Observed result | Status |
|---|---|---|---|---|---|---|---|---|
| 5K-A-01 | `snapshot_refresh.plan` | `snapshot_refresh/plan.py` | `test_empty_active_account_set_still_builds_final_target`, `test_mixed_investment_liability_roles_and_currencies_are_complete` | — | — | Every active account is represented; empty coverage still declares an exact zero-dependency NetWorth target. | Named test(s) passed in focused unit ledger U1. | PASS |
| 5K-A-02 | `snapshot_refresh.plan` | `snapshot_refresh/plan.py` | `test_consistently_archived_account_is_excluded`, `test_contradictory_or_malformed_archive_state_fails_closed` | — | — | Consistently archived accounts are excluded; contradictory archive state fails closed. | Named test(s) passed in focused unit ledger U1. | PASS |
| 5K-A-03 | `snapshot_refresh.plan` | `snapshot_refresh/plan.py` | `test_each_active_unsupported_account_type_invalidates_plan`, `test_supported_and_unsupported_mix_returns_no_partial_plan` | — | — | Broker, exchange, crypto-wallet, credit-card, loan and mortgage are complete; bank, cash and savings invalidate the whole plan. | Named test(s) passed in focused unit ledger U1. | PASS |
| 5K-A-04 | `snapshot_refresh.plan` | `snapshot_refresh/plan.py` | `test_role_maps_to_exact_refresh_capability`, `test_malformed_active_membership_fails_closed`, `test_duplicate_active_membership_identity_fails_closed` | — | — | Owner/admin/editor map to refresh, viewer maps to reuse-only, and incomplete or duplicate membership evidence fails. | Named test(s) passed in focused unit ledger U1. | PASS |
| 5K-A-05 | `snapshot_refresh.plan` | `snapshot_refresh/plan.py` | `test_output_currency_is_user_base_currency_not_account_currency`, `test_invalid_plan_metadata_fails_closed`, `test_postgresql_integer_maximum_is_valid` | — | — | User base currency owns output currency; IDs, timestamps, source/recalculation and calculation version are canonical. | Named test(s) passed in focused unit ledger U1. | PASS |
| 5K-A-06 | `snapshot_refresh.plan` | `snapshot_refresh/plan.py` | `test_permutation_is_equal_and_ordering_and_counts_remain_exact`, `test_all_contracts_are_frozen_and_inputs_are_not_mutated`, `test_plan_module_has_no_database_writer_api_or_clock_imports` | — | — | Plan construction is pure, deterministic, immutable and input-order independent. | Named test(s) passed in focused unit ledger U1. | PASS |
| 5K-B-01 | `snapshot_refresh.evidence_service` | `snapshot_refresh/evidence_service.py`, `snapshot_refresh/repository.py` | `test_active_coherent_caller_transaction_is_required`, `test_coherent_isolation_levels_succeed` | `test_repeatable_read_membership_race_is_one_old_then_new_view` | — | Caller owns REPEATABLE READ/SERIALIZABLE and isolation is established before persisted reads. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-B-02 | `snapshot_refresh.evidence_service` | `snapshot_refresh/evidence_service.py`, `snapshot_refresh/repository.py` | `test_persisted_base_currency_reaches_plan_unchanged_once`, `test_persisted_role_maps_through_5ka_exactly_once` | `test_user_base_currency_controls_reuse_and_mixed_refresh` | — | Persisted User owns currency; persisted Account/AccountMember rows are mapped once and 5K-A remains policy owner. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-B-03 | `snapshot_refresh.evidence_service` | `snapshot_refresh/evidence_service.py`, `snapshot_refresh/repository.py` | `test_refresh_only_never_queries_existing_snapshots`, `test_mixed_partition_is_complete_ordered_and_disjoint` | `test_mixed_owner_and_viewer_partition_and_empty_user` | — | Refresh/reuse partition exactly matches the plan and viewer is never promoted to a writer target. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-B-04 | `snapshot_refresh.evidence_service` | `snapshot_refresh/evidence_service.py`, `snapshot_refresh/repository.py` | `test_exact_viewer_snapshot_succeeds_without_financial_validation`, `test_malformed_reuse_snapshot_identity_or_metadata_fails` | `test_viewer_account_currency_snapshot_does_not_cover_user_currency`, `test_snapshot_version_and_source_metadata` | — | Viewer coverage uses one exact timestamp/granularity/User-currency/version key with no fallback or source priority. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-B-05 | `snapshot_refresh.evidence_service` | `snapshot_refresh/evidence_service.py`, `snapshot_refresh/repository.py` | `test_service_is_transaction_neutral_and_output_is_frozen` | `test_no_autoflush_no_write_sql_and_caller_rollback` | — | Evidence selection is read-only, transaction-neutral and returns no ORM rows. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-C1-01 | `snapshots.account_projection` | `snapshots/account_projection.py` | `test_mixed_currency_broker_converts_actual_native_evidence_to_output_currency`, `test_cash_account_converts_native_balances_to_distinct_output_currency`, `test_mixed_currency_liability_converts_scalar_and_preserves_native_breakdown` | — | — | Account and output currencies remain distinct; aggregates use output currency and native evidence remains native. | Named test(s) passed in focused unit ledger U1. | PASS |
| 5K-C1-02 | `snapshots.account_projection` | `snapshots/account_projection.py` | `test_same_currency_values_require_no_fx_evidence`, `test_mixed_currency_broker_rejects_missing_reverse_chained_and_extra_rates`, `test_fx_evidence_fail_closed_matrix` | — | — | Only exact direct consumed FX is accepted; reverse, chained, future, missing, duplicate and unused evidence fail. | Named test(s) passed in focused unit ledger U1. | PASS |
| 5K-C1-03 | `snapshots.account_projection` | `snapshots/account_projection.py` | `test_empty_mixed_currency_account_requires_no_synthetic_fx_rate`, `test_account_currency_difference_alone_does_not_require_fx` | — | — | Empty mixed-currency evidence does not require a synthetic Account-currency rate. | Named test(s) passed in focused unit ledger U1. | PASS |
| 5K-C2-01 | `snapshots.evidence_service` | `snapshots/evidence_service.py`, `snapshots/evidence_repository.py` | `test_omitted_output_currency_is_structurally_equal_to_explicit_account_currency`, `test_explicit_output_currency_keeps_snapshot_and_event_time_rates_separate` | `test_persisted_mixed_currency_investment_uses_snapshot_and_event_time_fx` | — | Persisted direct FX uses snapshot time for valuation and event time for historical metrics. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-C2-02 | `snapshots.evidence_service` | `snapshots/evidence_service.py`, `snapshots/evidence_repository.py` | `test_direct_persisted_rate_failure_matrix`, `test_mixed_currency_liability_selects_and_audits_direct_snapshot_rate` | `test_persisted_output_currency_rate_failures_write_nothing`, `test_persisted_liability_converts_to_output_currency_read_only` | — | Missing, reverse, chained, future or ambiguous persisted rates fail closed; liability remains native and converts directly. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-C2-03 | `snapshots.evidence_service` | `snapshots/evidence_service.py`, `snapshots/evidence_repository.py` | `test_complete_result_is_frozen` | `test_persisted_cash_output_currency_conversion_is_exact_and_read_only` | — | Evidence is immutable/read-only and audit IDs equal exactly consumed FX rows. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-C3-01 | `snapshots.persistence_projection` | `snapshots/persistence_projection.py` | `test_mixed_currency_investment_maps_native_and_converted_physical_fields`, `test_output_currency_changes_snapshot_and_item_identity_only_at_currency_boundary` | `test_mixed_investment_projection_round_trips_exact_physical_rows`, `test_output_currency_is_a_distinct_physical_unique_identity` | — | Physical currency and deterministic snapshot/item identity include output currency while native item fields remain unchanged. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-C3-02 | `snapshots.persistence_projection` | `snapshots/persistence_projection.py` | `test_mixed_currency_liability_maps_one_direct_rate_and_native_breakdown`, `test_fully_repaid_mixed_currency_liability_retains_direct_rate_and_audit` | `test_mixed_liability_projection_round_trips_without_synthetic_items` | — | Liability audit is complete; mixed currency uses one direct rate and explicit zero remains real evidence. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-C3-03 | `snapshots.persistence_projection` | `snapshots/persistence_projection.py` | `test_breakdowns_use_sorted_fixed_scale_decimal_strings`, `test_exchange_rate_json_is_versioned_sorted_and_auditable`, `test_inputs_are_not_mutated_outputs_are_frozen_and_json_is_stable` | — | — | JSONB breakdowns and FX audit are canonical, fixed-scale, deterministic and immutable. | Named test(s) passed in focused unit ledger U1. | PASS |
| 5K-C3-04 | `snapshots.persistence_projection` | `snapshots/persistence_projection.py` | `test_physical_row_contracts_match_all_and_only_sqlalchemy_columns` | `test_physical_postgresql_snapshot_contract_matches_final_5k_audit` | — | Projection performs no DB/ORM construction and matches existing physical columns without migration. | Named tests and source inspection passed in U1, S1 and PG-FINAL. | PASS |
| 5K-C4-01 | `snapshots.writer` | `snapshots/writer.py`, `snapshots/writer_repository.py` | `test_created_composes_evidence_projection_and_persistence_once`, `test_projection_identity_mismatch_fails_before_replay` | `test_create_exact_snapshot_and_fresh_session_replay` | — | Writer owns one transaction, locks complete physical identity before evidence, and validates projection identity. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-C4-02 | `snapshots.writer` | `snapshots/writer.py`, `snapshots/writer_repository.py` | `test_exact_replay_is_read_only`, `test_every_physical_field_mismatch_is_conflict` | `test_metadata_conflict_and_persisted_corruption_are_not_repaired` | — | Exact replay is read-only and every immutable physical mismatch conflicts without repair/delete. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-C4-03 | `snapshots.writer` | `snapshots/writer.py`, `snapshots/writer_repository.py` | `test_snapshot_lock_scope_includes_output_currency_and_milliseconds` | `test_account_and_output_currency_snapshots_coexist_and_replay_independently` | — | Lock/replay identity is account, timestamp, output currency and granularity; distinct currencies coexist. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-C4-04 | `snapshots.writer` | `snapshots/writer.py`, `snapshots/writer_repository.py` | `test_mixed_currency_liability_lock_order_and_replay_identity` | `test_new_liability_observation_waits_and_retry_conflicts`, `test_new_mixed_liability_fx_waits_and_retry_conflicts` | — | Liability and FX evidence locks stabilize a coherent write without lock-order inversion. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-C4-05 | `snapshots.writer` | `snapshots/writer.py`, `snapshots/writer_repository.py` | `test_flush_and_reload_failures_roll_back_outer_transaction` | `test_item_flush_failure_rolls_back_snapshot_and_clean_retry_succeeds` | — | Creation failure rolls back snapshot and items; no partial physical identity remains. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-C4-06 | `snapshots.writer` | `snapshots/writer.py`, `snapshots/writer_repository.py` | — | `test_same_identity_concurrency_creates_once_and_replays_after_lock_wait`, `test_same_identity_different_metadata_creates_once_then_conflicts` | — | Concurrent exact writes converge created/replayed; changed evidence creates/conflicts with no duplicate. | Named test passed in its isolated PostgreSQL ledger entry. | PASS |
| 5K-C5-01 | `snapshots.manual_service` | `snapshots/api.py`, `snapshots/models.py`, `snapshots/manual_service.py` | `test_request_model_accepts_optional_exact_output_currency`, `test_explicit_output_currency_is_forwarded_exactly_once` | `test_manual_output_currency_creates_and_replays_currency_separated_investment_rows` | `test_endpoint_openapi_contract_has_optional_body_and_authentication` | Missing body, `{}`, JSON null and explicit null preserve Account currency; explicit canonical output passes unchanged. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-C5-02 | `snapshots.manual_service` | `snapshots/api.py`, `snapshots/models.py`, `snapshots/manual_service.py` | `test_request_model_rejects_noncanonical_or_extra_input`, `test_write_roles_authorize_then_call_writer_once_with_idle_session` | `test_persisted_write_roles_create_replay_and_next_bucket`, `test_hidden_account_matrix_creates_nothing` | `test_response_contract_rejects_internal_evidence` | Validation, role authorization and concealed account boundary are fail-closed; writer receives an idle session and one bucket. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-D1-01 | `net_worth.evidence_service` | `net_worth/evidence_service.py` | `test_none_required_identities_preserves_unconstrained_selection`, `test_explicit_empty_required_identities_accepts_exact_empty_user`, `test_invalid_required_identities_fail_before_repository_access` | `test_explicit_empty_guard_builds_exact_zero_for_empty_user` | — | `None` preserves discovery, `()` means exact zero, and explicit lineage is immutable/canonical/unique. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-D1-02 | `net_worth.evidence_service` | `net_worth/evidence_service.py` | `test_required_account_set_must_exactly_match_active_accounts`, `test_required_snapshot_identity_must_match_selected_snapshot` | `test_explicit_guard_rejects_empty_missing_extra_and_substituted_accounts`, `test_explicit_guard_rejects_different_snapshot_for_correct_account` | — | Caller lineage cannot narrow, substitute or replace current persisted coverage. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-D1-03 | `net_worth.writer` | `net_worth/writer.py` | `test_projection_dependency_mismatch_fails_before_replay_or_insert`, `test_retry_attempts_preserve_exact_dependency_guard` | `test_guard_mismatch_fails_before_physical_replay_and_does_not_repair`, `test_membership_drift_invalidates_precomputed_dependency_guard` | — | Exact guard survives all SERIALIZABLE retries and fails before replay/insert when projection or persisted coverage drifts. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-D2-01 | `snapshot_refresh.executor` | `snapshot_refresh/executor.py`, `snapshot_refresh/executor_repository.py` | `test_invalid_command_fails_before_io`, `test_operation_order_commands_lineage_and_counts_are_exact`, `test_repository_emits_exact_repeatable_read_statement` | `test_mixed_refresh_reuse_create_and_fresh_session_replay` | — | Coverage uses one committed REPEATABLE READ phase before deterministic writers and preserves User-owned currency. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-D2-02 | `snapshot_refresh.executor` | `snapshot_refresh/executor.py` | `test_mixed_refresh_and_reuse_never_writes_viewer_target`, `test_malformed_account_result_stops_before_next_stage`, `test_duplicate_snapshot_identity_fails_before_net_worth` | `test_mixed_refresh_reuse_create_and_fresh_session_replay` | — | Every refresh target is called once, viewer never invokes writer, and result/lineage identities are exact and unique. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-D2-03 | `snapshot_refresh.executor` | `snapshot_refresh/executor.py` | `test_created_then_failed_run_can_resume_with_replay` | `test_partial_account_failure_commits_prefix_and_exact_replay_resumes`, `test_failure_after_account_stage_keeps_commits_for_resume` | — | Partial AccountSnapshot commits survive; retry replays completed work and resumes without compensation or duplicates. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-D2-04 | `snapshot_refresh.executor` | `snapshot_refresh/executor.py` | `test_malformed_net_worth_result_fails_closed` | `test_d1_guard_rejects_membership_drift_and_same_count_substitution` | — | NetWorth receives exact ordered lineage once and current coverage drift blocks final write. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-E1-01 | `snapshot_refresh.manual_service` | `snapshot_refresh/api.py`, `snapshot_refresh/manual_service.py`, `snapshot_refresh/models.py`, `snapshot_refresh/version.py` | `test_exact_executor_command_uses_principal_and_one_bucket`, `test_commit_finishes_before_executor_factory_receives_idle_session` | `test_principal_isolation_uses_only_current_user` | `test_openapi_contract_has_no_body_or_selectors_and_requires_auth` | Principal is the only public input; auth transaction closes before one executor call with one UTC minute bucket and shared version. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-E1-02 | `snapshot_refresh.manual_service` | `snapshot_refresh/manual_service.py`, `snapshot_refresh/models.py` | `test_executor_errors_map_to_generic_application_errors`, `test_result_maps_only_safe_summary` | `test_missing_viewer_coverage_is_generic_and_writes_nothing`, `test_physical_conflict_is_generic_and_does_not_repair` | `test_response_rejects_internal_extra_fields` | State/conflict map to generic 409 and no user/account/lineage/FX/financial evidence leaks. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-E1-03 | `snapshot_refresh.manual_service` | `snapshot_refresh/manual_service.py` | `test_dependency_transaction_leak_rolls_back_as_runtime_error` | `test_empty_user_creates_and_replays_zero_account_net_worth`, `test_mixed_create_and_fresh_session_replay`, `test_concurrent_requests_converge_without_duplicate_rows`, `test_partial_failure_commits_prefix_and_retry_resumes` | — | Empty, mixed role/currency, concurrent and partial-failure paths are exact replay-safe and leave sessions idle. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-E1-04 | `snapshot_refresh.manual_service`, `snapshot_refresh.executor` | `snapshot_refresh/api.py`, `snapshot_refresh/manual_service.py`, `snapshot_refresh/executor.py` | — | `test_viewer_only_user_reuses_exact_snapshot_without_writer_creation`, `test_role_revocation_between_auth_and_coverage_is_detected` | coordinated manual endpoint | A viewer-only user consumes exactly one existing snapshot without a writer-created replacement, and a role revocation committed after authentication but before protected coverage is detected before snapshot writes. | Both endpoint tests passed against real PostgreSQL in PG-FINAL. | PASS |
| 5K-E2-01 | `imports.posting_service` | `imports/posting_service.py` | `test_success_posts_rows_in_locked_order_and_finalizes_once`, `test_imported_row_with_ambiguous_persisted_target_fails_closed` | `test_investment_import_rebuilds_holdings_and_creates_then_replays_snapshots`, `test_partially_completed_batch_refreshes_only_imported_targets` | `test_post_import_batch_endpoint_is_thin_and_stable` | Canonical import commits first and persisted imported rows have exactly one target with exact transaction/investment counts. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-E2-02 | `imports.post_processing_service` | `imports/post_processing_service.py`, `imports/post_processing_repository.py` | `test_investment_import_rebuilds_then_executes_and_audits`, `test_transaction_only_import_skips_holding_but_executes`, `test_replayed_batch_still_rebuilds_and_executes` | `test_investment_import_rebuilds_holdings_and_creates_then_replays_snapshots` | `test_post_import_batch_endpoint_is_thin_and_stable` | Post-processing is post-commit, Holdings uses exact completed-at, snapshots use its minute floor with source import-event and recalculation false. | Named tests passed in unit ledger U1 and PG-E2. | PASS |
| 5K-E2-03 | `imports.post_processing_service` | `imports/post_processing_service.py` | `test_holding_unavailable_preserves_import_result_and_skips_executor`, `test_known_snapshot_failure_is_http_success_status` | `test_holding_failure_preserves_committed_import_and_replay_recovers`, `test_missing_price_preserves_import_and_holdings_then_replay_completes`, `test_missing_fx_preserves_committed_stages_then_replay_completes` | `test_post_import_batch_reports_known_post_processing_failure_as_http_200` | Known Holding/state/conflict failures preserve committed import and map to truthful HTTP 200 outcome; replay resumes. | Named tests passed in unit ledger U1 and PG-E2. | PASS |
| 5K-E2-04 | `imports.post_processing_repository` | `imports/post_processing_repository.py` | `test_audit_lock_scope_is_deterministic_and_signed_bigint_safe` | `test_concurrent_investment_post_processing_is_exact_and_deduplicated`, `test_concurrent_import_post_endpoint_requests_converge` | — | ImportLog is generic deterministic audit, advisory-locked and not job state; replay/concurrency creates no duplicate ID. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-E2-05 | `imports.post_processing_service` | `imports/post_processing_service.py` | `test_zero_import_is_not_required_without_post_processing` | `test_zero_import_batch_is_post_processing_noop`, `test_supported_investment_import_with_other_unsupported_account_is_unavailable` | — | Zero-import is a no-op; unsupported whole-user coverage fails refresh without rolling back import/Holding. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-E2-06 | `imports.post_processing_service` | `imports/post_processing_service.py` | — | `test_immutable_snapshot_conflict_preserves_existing_snapshot_without_repair`, `test_two_financially_different_batches_in_same_minute_conflict_without_time_shift` | — | Immutable same-minute conflicts do not update/delete snapshots or shift time; canonical import remains committed. | Named test passed in its isolated PostgreSQL ledger entry. | PASS |
| 5K-E2-07 | `imports.api` | `imports/api.py`, `imports/models.py` | `test_post_import_batch_endpoint_is_thin_and_stable`, `test_import_post_response_rejects_internal_post_processing_fields` | `test_import_post_endpoint_principal_isolation_prevents_post_processing` | `test_post_import_batch_openapi_contract` | Existing authenticated endpoint remains thin, concealed and free of internal target/snapshot/lineage data. | Named tests passed in unit ledger U1 and the applicable isolated PostgreSQL ledger entry. | PASS |
| 5K-X-01 | cross-entry immutable identity | snapshot and import orchestration | — | `test_manual_and_import_refresh_same_bucket_preserve_immutable_identity` | same named endpoint test | Manual and import refresh in one bucket preserve the first immutable identity and never time-shift, update or delete. | Named cross-entry test passed in PG-FINAL. | PASS |
| 5K-X-02 | cross-domain lineage | executor + NetWorth writer | `test_mixed_refresh_and_reuse_never_writes_viewer_target` | `test_mixed_refresh_reuse_create_and_fresh_session_replay`, `test_mixed_create_and_fresh_session_replay`, `test_viewer_only_user_reuses_exact_snapshot_without_writer_creation` | `test_mixed_create_and_fresh_session_replay` | Owner/editor/viewer produces two writes, one reuse identity, exact ordered three-account lineage and one replayable NetWorth row. | Named tests were inspected and passed in U1, PG-D2, PG-E1 and PG-FINAL. | PASS |
| 5K-X-03 | cross-domain drift | executor + NetWorth writer | `test_malformed_net_worth_result_fails_closed` | `test_d1_guard_rejects_membership_drift_and_same_count_substitution`, `test_partial_account_failure_commits_prefix_and_exact_replay_resumes` | — | Coverage drift after committed account writes blocks NetWorth; restored state replays account rows and creates no duplicate. | Named tests were inspected and passed in U1 and PG-D2. | PASS |
| 5K-X-04 | shared version boundary | `snapshot_refresh.version` | `test_calculation_version_mismatch_fails_before_clock_and_executor` | `test_coordinated_version_mismatch_fails_before_snapshot_writes` | same named manual/import endpoint test | Account/NetWorth version mismatch prevents snapshot writes; E1 is generic 409 and committed E2 import is HTTP 200 unavailable without version leakage. | Named tests passed in U1 and PG-FINAL. | PASS |
| 5K-X-05 | zero-lineage boundary | executor + NetWorth writer | `test_empty_active_account_set_still_builds_final_target` | `test_empty_user_creates_zero_net_worth_and_replays`, `test_empty_user_creates_and_replays_zero_account_net_worth` | `test_empty_user_creates_and_replays_zero_account_net_worth` | Explicit `()` produces no AccountSnapshot, one structural-zero NetWorth row, empty lineage and exact replay. | Named tests were inspected and passed in U1, PG-D2, PG-E1 and PG-NWW. | PASS |
| 5K-PG-01 | physical PostgreSQL schema | database schema | schema metadata tests | final physical-schema audit | — | Physical types, precision, JSONB, FKs, unique keys, indexes and delete behavior match contracts; no 5K migration/job table exists. | Direct PostgreSQL catalog assertions passed in PG-FINAL. | PASS |
| 5K-API-01 | public schemas | snapshot-refresh and imports API | `test_response_rejects_internal_extra_fields`, `test_import_post_response_rejects_internal_post_processing_fields` | `test_principal_isolation_uses_only_current_user`, `test_import_post_endpoint_principal_isolation_prevents_post_processing` | `test_openapi_contract_has_no_body_or_selectors_and_requires_auth`, `test_post_import_batch_openapi_contract` | Exact security/request/response contracts expose no undocumented selector, lineage, FX, financial breakdown or exception detail. | Named schema and endpoint tests passed in U1, PG-E1 and PG-E2. | PASS |
| 5K-TX-01 | transaction ownership | all 5K services | `test_service_is_transaction_neutral_and_output_is_frozen`, `test_created_path_owns_one_transaction_and_exact_operation_order`, `test_dependency_transaction_leaks_are_rolled_back_and_exposed`, `test_dependency_transaction_leak_is_rolled_back` | `test_no_autoflush_no_write_sql_and_caller_rollback`, `test_create_exact_snapshot_and_fresh_session_replay`, `test_partial_account_failure_commits_prefix_and_exact_replay_resumes` | — | Each domain owns its documented transaction; no hidden cross-domain transaction remains and leaked sessions fail internally after rollback. | Named tests and source ownership were inspected; tests passed in U1, PG-B, PG-C4 and PG-D2. | PASS |
| 5K-LOCK-01 | lock ordering | writers, import, Holding, audit | `test_snapshot_lock_scope_includes_output_currency_and_milliseconds`, `test_mixed_currency_liability_lock_order_and_replay_identity`, `test_advisory_lock_scope_and_hash_are_stable_and_namespaced`, `test_audit_lock_scope_is_deterministic_and_signed_bigint_safe` | `test_same_identity_concurrency_creates_once_and_replays_after_lock_wait`, `test_new_liability_observation_waits_and_retry_conflicts`, `test_concurrent_investment_post_processing_is_exact_and_deduplicated` | — | Advisory/table/row locks use stable scopes and non-inverted order; concurrency has no sleep-based correctness, deadlock or duplicate. | Named tests and production lock order were inspected; tests passed in U1, PG-C4 and PG-E2. | PASS |

## Session and transaction ownership

This finalized table is populated from production-source inspection and
verified test results.

| Service | Required incoming session state | Opens transaction | Isolation | Locks | Commits | Rolls back | Required outgoing state |
|---|---|---|---|---|---|---|---|
| `SnapshotRefreshEvidenceService` | Active caller-owned transaction | No | REPEATABLE READ or SERIALIZABLE | None | No | No | Caller transaction remains active |
| `AccountSnapshotEvidenceService` | Active writer-owned transaction | No | Writer-owned | Read-only selection | No | No | Caller transaction remains active |
| `AccountSnapshotWriter` | Idle | One outer transaction | READ COMMITTED | Account, snapshot advisory, type-specific evidence, replay row | Context commit | Context rollback | Idle |
| `NetWorthEvidenceService` | Active caller-owned transaction | No | REPEATABLE READ or SERIALIZABLE | None | No | No | Caller transaction remains active |
| `NetWorthSnapshotWriter` | Idle | One per bounded retry attempt | SERIALIZABLE | Snapshot advisory and replay row | Successful attempt | Failed attempt | Idle |
| `UserSnapshotRefreshExecutor` | Idle | One short coverage transaction; delegates later writes | REPEATABLE READ for coverage | Coverage reads; delegated writers own locks | Coverage and delegated domains | Leaked dependency transaction only | Idle |
| `ManualUserSnapshotRefreshService` | Auth read may be active | No domain write transaction; delegates executor | — | None | Closes auth read | Cleans leaked transaction | Idle |
| `ImportBatchPostingService` | Existing auth boundary state | One canonical posting transaction | Repository default | Batch, rows, deduplication and canonical target locks | Canonical import | Canonical import failure | Idle |
| `HoldingRebuildApplicationService` | Idle after authorization handoff | One rebuild transaction | Repository default | Account/rebuild advisory and canonical source locks | Rebuild | Rebuild failure | Idle |
| `ImportBatchPostProcessingService` | Existing auth boundary state | No cross-stage transaction; delegates each stage | — | None directly | Each domain independently | Cleans leaked dependency transaction | Idle |
| `ImportPostProcessingRepository` audit write | Idle before short audit operation | One audit transaction | Repository default | Deterministic audit advisory and existing log row | Audit | Audit failure | Idle |

## Lock-order inventory

| Path | Required lock order | Audit result |
|---|---|---|
| Refresh coverage | REPEATABLE READ snapshot; no explicit lock | PASS — source order inspected and applicable unit/PostgreSQL lock tests passed. |
| Investment AccountSnapshot | Account `FOR SHARE` → snapshot advisory lock → canonical ledger/Holding locks → PriceSnapshot/ExchangeRate table locks → evidence → replay row/insert | PASS — source order inspected and applicable unit/PostgreSQL lock tests passed. |
| Liability AccountSnapshot | Account `FOR SHARE` → snapshot advisory lock → LiabilityBalance table lock → market evidence lock only when FX is required → evidence → replay row/insert | PASS — source order inspected and applicable unit/PostgreSQL lock tests passed. |
| NetWorthSnapshot | SERIALIZABLE first statement → snapshot advisory lock → coherent evidence → replay row/insert | PASS — source order inspected and applicable unit/PostgreSQL lock tests passed. |
| Import posting | authorization/account → ImportBatch → ImportRows → deduplication → canonical target locks/writes | PASS — source order inspected and applicable unit/PostgreSQL lock tests passed. |
| Holding rebuild | authorization/account → rebuild advisory lock → canonical source rows → current Holding rows | PASS — source order inspected and applicable unit/PostgreSQL lock tests passed. |
| Import audit | deterministic audit advisory transaction lock → existing ImportLog `FOR UPDATE` → insert/compare | PASS — source order inspected and applicable unit/PostgreSQL lock tests passed. |

## Verification ledger

### Focused unit and public API matrix

`U1` ran the following exact files in one database-free pytest process:

- `backend/python/tests/test_snapshot_refresh_plan.py`
- `backend/python/tests/test_snapshot_refresh_evidence.py`
- `backend/python/tests/test_snapshot_refresh_executor.py`
- `backend/python/tests/test_snapshot_refresh_manual_service.py`
- `backend/python/tests/test_snapshot_refresh_manual_api.py`
- `backend/python/tests/test_account_snapshot_projection.py`
- `backend/python/tests/test_account_snapshot_evidence.py`
- `backend/python/tests/test_account_snapshot_persistence_projection.py`
- `backend/python/tests/test_account_snapshot_writer.py`
- `backend/python/tests/test_account_snapshot_manual_service.py`
- `backend/python/tests/test_net_worth_projection.py`
- `backend/python/tests/test_net_worth_evidence.py`
- `backend/python/tests/test_net_worth_writer.py`
- `backend/python/tests/test_net_worth_manual_service.py`
- `backend/python/tests/test_import_posting_service.py`
- `backend/python/tests/test_import_post_processing_service.py`
- `backend/python/tests/test_import_batches.py`

Result: **1026 passed, 0 failed, 0 skipped, 0 xfailed**. Every named unit
or OpenAPI test in the matrix is defined in one of these files and executed in
this result.

### Isolated PostgreSQL matrix

Each entry used a newly cloned current baseline database, ran as a separate
pytest process, and ended with zero failed, skipped and xfailed tests. All
ephemeral audit databases were then connection-terminated and dropped; the
final control query returned `remaining_databases=[]` and
`active_connections=0`.

| Ledger ID | PostgreSQL test file | Type | Result |
|---|---|---|---|
| PG-B | `backend/python/tests/test_snapshot_refresh_evidence_integration.py` | persisted coverage/race/read-only | 14 passed |
| PG-C2 | `backend/python/tests/test_account_snapshot_evidence_integration.py` | persisted output-currency/FX evidence | 19 passed |
| PG-C3 | `backend/python/tests/test_account_snapshot_persistence_projection_integration.py` | physical projection round trip | 3 passed |
| PG-C4 | `backend/python/tests/test_account_snapshot_writer_integration.py` | writer/replay/conflict/concurrency | 25 passed |
| PG-C5 | `backend/python/tests/test_account_snapshot_manual_endpoint_integration.py` | authorized account endpoint | 22 passed |
| PG-NWE | `backend/python/tests/test_net_worth_evidence_integration.py` | exact persisted lineage evidence | 20 passed |
| PG-NWW | `backend/python/tests/test_net_worth_writer_integration.py` | SERIALIZABLE writer/guard/concurrency | 37 passed |
| PG-D2 | `backend/python/tests/test_snapshot_refresh_executor_integration.py` | coordinated execution/resume/drift | 9 passed |
| PG-E1 | `backend/python/tests/test_snapshot_refresh_manual_endpoint_integration.py` | coordinated manual endpoint | 10 passed |
| PG-IP | `backend/python/tests/test_import_posting_integration.py` | canonical import transaction | 56 passed |
| PG-H | `backend/python/tests/test_holding_rebuild_integration.py` | Holding rebuild/locks/replay | 14 passed |
| PG-E2 | `backend/python/tests/test_import_post_processing_integration.py` | post-import recovery/conflict/concurrency | 13 passed |
| PG-FINAL | `backend/python/tests/test_snapshot_refresh_final_audit_integration.py` | cross-entry/version/viewer/revocation/catalog audit | 5 passed |

The named E2 proofs in PG-E2 are:

- `test_transaction_only_unsupported_account_preserves_committed_import`
- `test_investment_import_rebuilds_holdings_and_creates_then_replays_snapshots`
- `test_holding_failure_preserves_committed_import_and_replay_recovers`
- `test_missing_price_preserves_import_and_holdings_then_replay_completes`
- `test_missing_fx_preserves_committed_stages_then_replay_completes`
- `test_concurrent_investment_post_processing_is_exact_and_deduplicated`
- `test_partially_completed_batch_refreshes_only_imported_targets`
- `test_supported_investment_import_with_other_unsupported_account_is_unavailable`
- `test_immutable_snapshot_conflict_preserves_existing_snapshot_without_repair`
- `test_two_financially_different_batches_in_same_minute_conflict_without_time_shift`
- `test_concurrent_import_post_endpoint_requests_converge`
- `test_import_post_endpoint_principal_isolation_prevents_post_processing`
- `test_zero_import_batch_is_post_processing_noop`

The cross-entry additions in PG-FINAL are:

- `test_manual_and_import_refresh_same_bucket_preserve_immutable_identity`
- `test_coordinated_version_mismatch_fails_before_snapshot_writes`
- `test_viewer_only_user_reuses_exact_snapshot_without_writer_creation`
- `test_role_revocation_between_auth_and_coverage_is_detected`
- `test_physical_postgresql_snapshot_contract_matches_final_5k_audit`

### Source and boundary inspection

`S1` inspected the production transaction and lock calls in:

- `snapshot_refresh/evidence_service.py`, `repository.py`, `executor.py`,
  `executor_repository.py`, `manual_service.py`
- `snapshots/evidence_service.py`, `writer.py`, `writer_repository.py`
- `net_worth/evidence_service.py`, `writer.py`, `writer_repository.py`
- `imports/posting_service.py`, `post_processing_service.py`,
  `post_processing_repository.py`
- `holdings/orchestration.py`, `holdings/repository.py`

The observed order matches the two tables above. Broad exception handlers at
domain transaction boundaries only roll back and re-raise the original
unexpected exception; they do not classify it as normal unavailable state.
Concurrency tests poll PostgreSQL `pg_blocking_pids`/`wait_event_type`; no
fixed sleep is used as the correctness proof.

### Full quality and schema gates

- Full Python suite: **2030 passed, 395 environment-gated PostgreSQL skipped,
  0 failed, 0 xfailed**. Every gated 5K PostgreSQL module was separately run
  above with zero skips.
- Branch coverage: **89.16%**, above the repository 70% threshold.
- Ruff lint: passed; Ruff format check: 236 files passed.
- mypy: 231 source files, no issues.
- Frontend Vitest: 34 passed; ESLint: no warnings/errors; TypeScript:
  `npx.cmd tsc --noEmit` passed.
- Prisma validate/generate: passed.
- Frozen Prisma archive deployment verification: all three frozen migrations
  applied successfully to an empty isolated database.
- Migration policy/static schema tests: policy passed; 49 static tests passed.
- Alembic protected lifecycle: 1 passed.
- Head persistence and live SQLAlchemy parity: 2 passed.
- Migration runner/advisory lock: 3 passed.
- `database_migrate.py check/upgrade`, Alembic `current --check-heads`, Alembic
  `check`, head artifact, SQLAlchemy live parity and baseline verification:
  passed at `3g0001liabbal`.
- Empty-database canonical bootstrap through all revisions: passed, followed
  by schema artifact and SQLAlchemy parity checks.

## Physical PostgreSQL audit

PG-FINAL queried `information_schema.columns`, `pg_constraint`, `pg_indexes`
and live snapshot tables rather than relying on SQLAlchemy declarations.
Observed results:

- the public catalog contains exactly 32 base tables and 28 PostgreSQL enums;
- all snapshot/audit timestamps are naive `TIMESTAMP(3)`;
- MONEY columns are `NUMERIC(18,6)`, item quantity/cost/native columns are
  `NUMERIC(28,10)`, and allocation is `NUMERIC(8,4)`;
- native breakdown and exchange-rate fields are JSONB;
- AccountSnapshot→Account and AccountSnapshotItem→AccountSnapshot delete
  actions are CASCADE, item→listing is RESTRICT, and NetWorth→User is RESTRICT;
- unique indexes are exactly AccountSnapshot
  `(accountId,timestamp,currency,granularity)`, AccountSnapshotItem
  `(snapshotId,listingId)`, and NetWorthSnapshot
  `(userId,timestamp,currency,granularity)`;
- the expected account/user/source/audit indexes and `ImportLog(id)` primary
  key exist;
- live duplicate-group queries returned zero for all three physical
  identities;
- forbidden `SnapshotRefreshJob`, `SnapshotRefreshExecution` and
  `ImportPostProcessingJob` tables are absent;
- current revision is `3g0001liabbal`; frozen Prisma archive, revision artifact
  and SQLAlchemy/live parity all match;
- no migration, DDL, enum, ORM model or job-state table was added by this
  audit.


## Intentional limitations

- Bank, cash and savings AccountSnapshots remain unsupported and fail the
  complete coordinated refresh.
- Same-minute financially different work may conflict with an immutable
  snapshot; timestamps are never shifted and existing rows are never repaired.
- Post-import failures do not compensate a committed canonical import.
- `ImportLog` is audit evidence, not persisted execution state.
- No scheduler, worker, queue or background execution is part of 5K.
