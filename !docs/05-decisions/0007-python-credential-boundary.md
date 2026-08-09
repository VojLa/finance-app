# 0007 Python owns credentials; NextAuth owns browser sessions

## Status

Accepted and implemented by R11-C.

## Decision

FastAPI is the only runtime allowed to read or write password hashes, verify
credentials, register users, and change passwords. NextAuth retains JWT session
management and maps the Python-authenticated user into the browser session.

Pre-session credential verification and registration require a short-lived internal
token with the dedicated `finance-app-next-auth-service` subject. Password changes
require the normal persisted-user principal. Browser Authorization and Cookie headers
are never forwarded as backend authority.

New passwords use bcrypt cost 12, have an explicit 72 UTF-8 byte maximum, and remain
compatible with existing bcryptjs hashes. Missing users and wrong passwords return the
same safe response and execute a bcrypt comparison. Request logs exclude bodies,
credentials, hashes, cookies, and authorization headers.

The local personal deployment uses the non-public Python network behind Next.js. A
shared ingress or distributed rate limiter is mandatory before public or multi-user
deployment; an in-process counter is intentionally not treated as sufficient.

## Contract

The detailed request and response models are generated from FastAPI OpenAPI. Next.js
keeps only server-only transport, exact field allowlisting, session checks, and Czech
presentation error mapping.
