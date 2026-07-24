# 5G-B – Canonical investment posting foundation

## Metadata

- Milestone: `0.1 - Architecture Locked`
- Parent: `5G - canonical posting`
- Dependency: Step 5G-A, merged as `385e83ae14e45d91644cd471197f57dd2c3e98b6`
- B1 merged as `89d1bd37e5aeabd6a06c06060e70766755f0a43f`
- Source of truth: persisted investment posting intents and canonical SQLAlchemy asset/ledger models
- Size: XL before splitting

## Goal

Consume a validated schema-version-1 `investment_event` posting intent and create one
canonical `InvestmentEvent` with its required `InvestmentMovement` rows exactly once.
Asset and listing identity must be resolved conservatively, the import row must retain its
audit payload, and the writer must participate in the caller-owned transaction later
provided by 5G-C.

## Why 5G-B is split

Investment posting contains three independent risk domains:

1. financial event and movement semantics;
2. global `Asset` and provider-specific `AssetListing` identity resolution;
3. database insertion, import-row linkage and exact replay.

Combining them would make review too broad and would hide whether a failure came from
financial mapping, identity resolution or persistence. Step 5G-B is split into:

- **5G-B1 – deterministic investment posting plan** — merged
  - re-derive and validate the persisted investment intent;
  - harden successful intents so every successful target is postable without inference;
  - build immutable event, asset-resolution and ordered movement plans;
  - validate exact `QUANTITY` and `TIMESTAMP` representability;
  - no asset, listing, event or movement database writes.
- **5G-B2 – conservative asset and listing resolution**
  - resolve existing provider listings first;
  - resolve a unique compatible ISIN asset when no provider listing exists;
  - create an asset/listing pair only from sufficient canonical evidence;
  - serialize provider-symbol and optional ISIN identities with deterministic advisory locks;
  - fail closed on ambiguity or conflicting identity;
  - no investment event creation and no import-row transition.
- **5G-B3 – investment event and movement writer**
  - combine a B1 plan with a B2 resolution;
  - create one event and its deterministic movement set;
  - mark one locked import row as `imported` and set only
    `created_investment_event_id`;
  - support exact replay over the event, movements and resolved identities;
  - no public endpoint and no batch finalization.

5G-C remains the only owner of the public batch `/post` endpoint, authorization, batch
locks, whole-batch commit/rollback and terminal counters.

## Canonical input boundary

An investment writer may act only on a row whose persisted workflow state is exact:

```text
batch.status = processing
row.status = pending or exact imported replay
normalized_data is an object
deduplication = {schema_version: 1, status: unique}
posting_intent.schema_version = 1
posting_intent.target = investment_event
deduplication_key is present
validation_errors = null
error_message = null
```

First posting requires both created IDs to be null. Exact replay requires:

```text
row.status = imported
created_transaction_id = null
created_investment_event_id is present
```

All other combinations fail closed.

The stored intent is untrusted JSONB. Every B1/B3 path must copy normalized data, remove
only `deduplication` and `posting_intent`, re-run the pure classifier, serialize with
`model_dump(mode="json")`, and require exact equality with the stored intent.

## Canonical investment model

One import row creates at most one root `InvestmentEvent`. The event owns a deterministic
set of movements. Movement direction and kind come only from the canonical action and
explicit provider evidence.

Initial event families:

- buy;
- sell;
- dividend;
- interest;
- cash deposit;
- cash withdrawal;
- currency conversion;
- asset transfer with explicit direction;
- fee;
- staking reward;
- airdrop.

A successful plan must never invent:

- transfer direction;
- asset symbol;
- listing currency;
- quantity;
- cash amount;
- fee;
- realized profit or loss;
- exchange semantics from free text.

## Ordered movement semantics

The B1 plan uses a stable tuple order. B3 inserts movements in that order and compares
replay by canonical movement signatures because the inherited schema has no ordinal
column.

Base order:

1. primary asset movement when present;
2. primary cash movement when present;
3. second conversion cash leg when present;
4. explicit fee movement last.

Movement families:

- buy: asset in, cash out, optional fee out;
- sell: asset out, cash in, optional fee out;
- dividend: cash in linked to the source asset, optional fee out;
- interest: cash in, optional fee out;
- cash deposit: cash in, optional fee out;
- cash withdrawal: cash out, optional fee out;
- currency conversion: source cash out, destination cash in, optional fee out;
- asset transfer: one explicitly directed asset movement, optional fee out;
- fee: one fee out movement;
- staking reward: asset in, optional valuation, optional fee out;
- airdrop: asset in, optional valuation, optional fee out.

Realized P/L is event metadata for a sell and is not an independent cash movement.

## Asset and listing ownership

Asset identity is global canonical data. A provider listing is the strongest reusable
identity available for an import source.

Initial provider mapping:

```text
trading212 -> PriceSource.broker, exchange = trading212
anycoin    -> PriceSource.exchange, exchange = anycoin
```

B2 must prefer an exact provider/provider-symbol/currency listing. A plan without a listing
currency may reuse that provider symbol only when exactly one listing exists across all
currencies. When no provider listing exists, one unique compatible ISIN asset may be reused.
Global symbol alone is never sufficient to merge two assets.

Unknown explicit asset type hints map conservatively to `AssetType.other`; they must not be
inferred from an ISIN prefix or a company name. Anycoin canonical assets are crypto.

The inherited schema permits nullable and non-unique identity fields. B2 must therefore:

- lock `provider + provider_symbol` without currency;
- additionally lock canonical ISIN when present;
- acquire all advisory locks in deterministic sorted order;
- fail closed on multiple same-ISIN assets or multiple currency-less provider candidates;
- require explicit listing and asset currency evidence before creating a listing;
- never update existing assets/listings to reconcile a conflict.

A migration is not part of B2 unless implementation proves an unavoidable invariant that
cannot be enforced with transaction advisory locking and inherited unique constraints.

## Exact database representability

Before any entity mutation, every value must be exactly representable by its target column:

- event and movement timestamps use canonical `TIMESTAMP`;
- quantity, price, value, fee and realized P/L use canonical `QUANTITY`;
- no path uses `float`;
- no database rounding, truncation or overflow is accepted.

The posting intent remains stored unchanged for audit even when some provider evidence,
such as an optional exchange rate, is not represented by a dedicated canonical column.
Such evidence may be ignored only when the canonical event remains fully reconstructable
from stored movements and the unchanged posting intent.

## Caller-owned transaction

B2 and B3 participate in a transaction owned by 5G-C or a test. They must not commit or
roll back.

B2 may add or validate:

- zero or one asset;
- zero or one provider listing.

B3 may add or validate:

- one investment event;
- its expected movement set;
- one import-row transition.

Neither may change batch status or counters.

## Exact replay

An imported investment row must resolve its referenced event and compare:

- event identity, account, source, type, date and import-batch linkage;
- external/order IDs, description and realized P/L fields;
- exact movement count and canonical movement signatures;
- expected asset/listing links and compatible canonical identity;
- null archived/deleted fields;
- unchanged import JSONB and deduplication key.

Missing or mismatched canonical history is corruption. Never repair it in place.

## Global exclusions

All 5G-B substeps exclude:

- public `/post` endpoint;
- authorization and batch finalization;
- holdings and snapshots;
- transfer pairing;
- category or counterparty inference;
- reporting-currency conversion;
- historical entity repair;
- background workers;
- raw-data purge.

## Verification

Each substep requires focused unit tests. B1 includes PostgreSQL composition tests that
reload classified rows and prove zero entity writes. B2 and B3 require real PostgreSQL
persistence, rollback, retry, ambiguity and concurrency tests.

5G-B is complete only after B1, B2 and B3 are merged and both Trading212 and Anycoin
successful intents can be posted or exactly replayed without batch finalization.