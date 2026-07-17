# API Conventions

API direction:

- Next.js routes are temporary BFF/adapters.
- Python/FastAPI becomes the primary backend API.
- Rust is called by Python for heavy calculations.

Conventions:

- Keep response models explicit.
- Keep write paths transactional.
- Return parse/import warnings as structured issues.
