# Coding standards

Type: reference
Status: current
Owns: cross-language implementation constraints
Code: TypeScript, Python and Rust source
Update when: language or architecture rules change

- Keep HTTP and UI adapters thin; business rules belong to Python services.
- Use exact decimal financial values and explicit currency.
- Enforce authorization and account isolation in Python.
- Treat files and provider payloads as untrusted.
- Make transaction, idempotency and concurrency boundaries explicit.
- Do not hand-edit generated contracts or inventories.
- Avoid unrelated refactoring in a focused change.
