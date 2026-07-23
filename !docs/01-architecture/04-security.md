# Security

## Authentication and authorization

Protected FastAPI endpoints require `Authorization: Bearer <token>`. The service
accepts only a short-lived HS256 token from the trusted Next.js session bridge.
It validates the signature, issuer, audience, `iat`, `exp`, and non-empty
subject before opening a database session, then resolves the subject against
`User`. Token configuration is controlled by `INTERNAL_AUTH_SECRET`,
`INTERNAL_AUTH_ISSUER`, `INTERNAL_AUTH_AUDIENCE`, and
`INTERNAL_AUTH_CLOCK_SKEW_SECONDS`.

Account authorization is enforced server-side on every account-scoped operation:

- `owner` can manage members and invitations; ownership cannot be assigned or
  removed through member APIs.
- `owner`, `admin`, and `editor` may create import batches, upload, parse,
  normalize, and run duplicate detection.
- any membership can read an accessible account, its imports, and its portfolio.
- archived accounts are absent from normal access; lifecycle operations have an
  explicit archived-account path.

The current Next.js UI has not yet implemented the issuing adapter for this
Python bridge, so its legacy routes remain separate. Do not treat a browser
session cookie as a FastAPI credential.

## Imports and sensitive data

Raw imports are stored outside the database in `IMPORT_STORAGE_ROOT`, defaulting
to `.data/imports`. Files are addressed by a SHA-256 hash of the batch id, are
written through a temporary file, and are published atomically after checksum
verification. This is local development storage, not a complete production
retention or encrypted-object-storage design. The schema has retention fields,
but no purge worker, deletion workflow, or GDPR anonymization implementation
exists yet.

Upload controls include a binary content-type requirement, a 1 GiB upload cap,
filename path-separator rejection, declared-size and SHA-256 checks, and a
64 MiB synchronous parser limit. The application must not log raw financial
payloads.

## Operational controls

Each request gets an `X-Request-ID`; a valid client UUID is reused, otherwise a
new UUID is generated. Structured logs include request metadata and duration but
exclude request bodies, cookies, authorization headers, and financial payloads.
Application errors return a stable envelope without tracebacks. In production,
startup requires a database URL, JSON logging, disabled interactive API docs,
and an internal authentication secret of at least 32 characters.

Secrets belong in environment configuration and must never be committed,
returned by endpoints, or printed in diagnostics.
