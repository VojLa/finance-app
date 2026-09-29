# Market evidence flow

Type: flow
Status: current
Owns: exact provider identity and untrusted payload to persisted price/FX evidence
Code: asset aliases, market data, price/FX providers and evidence writers
Update when: provider identity, selection, validation or persistence changes

1. A valuation or history plan declares the exact price/FX observations it needs,
   including the provider's explicit price quote currency separately from the
   acquisition/listing cost currency.
2. An exact active provider alias selects the external identity; no ticker inference or
   provider discovery occurs in the finance workflow.
3. The selected provider transport fetches a bounded payload.
4. Provider-specific parsing and common validation reject malformed, stale, future,
   wrong-direction or conflicting evidence.
5. The writer persists observation, source identity, timestamp and applicable lineage.
6. Valuation/history reselects persisted evidence under its cutoff and publication
   rules. Price-value and cost-basis currencies retain separate lineage and each
   requires its own direct conversion to the account/output currency; a missing
   requirement remains unavailable.

Transport failure is retryable but never authorizes a synthetic rate or price.
Operator alias changes follow the [provider runbook](../../operations/provider-identity.md).
