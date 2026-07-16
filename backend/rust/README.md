# Rust Engines

Target role:

- Deterministic calculation cores.
- No frontend or Next.js concerns.
- Prefer pure functions with explicit inputs and outputs.
- Python/FastAPI should orchestrate data loading, call Rust, and persist results.

Initial target engines:

- Ledger replay.
- Daily account snapshot builder.
- Historical portfolio calculations.
- Large import normalization where TypeScript/Python becomes too slow.

Run tests:

```powershell
cd backend/rust
cargo test
```

