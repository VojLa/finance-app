# Runtime configuration

Type: runbook
Status: current
Owns: environment-variable families, validation and secret boundaries
Code: `.env.example`, Docker Compose, Python settings and Python API server config
Update when: a runtime setting is added, removed or changes validation

| Family                    | Variables                                                                                              | Authority                                                                                                    |
| ------------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| Python core               | `ENVIRONMENT`, `DATABASE_URL`, `LOG_LEVEL`, `LOG_JSON`, `DOCS_ENABLED`                                 | Pydantic settings; production fails closed                                                                   |
| Identity bridge           | `INTERNAL_AUTH_SECRET`, issuer, audience and clock skew; Next token TTL                                | shared secret is server-only and at least 32 characters                                                      |
| Next transport            | `PYTHON_BACKEND_URL`, `PYTHON_API_TIMEOUT_MS`                                                          | validated server-only URL and bounded timeout                                                                |
| Browser session           | `NEXTAUTH_URL`, `NEXTAUTH_SECRET`                                                                      | NextAuth server configuration                                                                                |
| Market providers          | CoinGecko/Twelve Data/Yahoo base URLs, timeouts, response limits, user agents and API keys             | HTTPS credential-free base URLs; keys remain secret; CoinGecko demo and Pro keys are mutually exclusive       |
| Market selection          | `MARKET_EVIDENCE_SOURCE_MODE`                                                                          | production requires `canonical`; `local_free` is non-production fixture behavior                             |
| Durable jobs              | enabled, poll, lease, heartbeat and shutdown-grace settings                                            | validated bounds; heartbeat must be shorter than lease                                                       |
| Portfolio history runtime | `PORTFOLIO_HISTORY_RUNTIME_ENABLED`, worker ID/poll/lease/heartbeat, scheduler poll and shutdown grace | one atomic worker+scheduler flag; enabled startup requires the 3r schema and exact configured market sources |

Start from `.env.example`; never commit `.env`. Do not create a
`NEXT_PUBLIC_*` alias for backend URLs, internal tokens or provider/database secrets.
Docker Compose supplies development defaults and enables one API worker; tests should
keep background jobs disabled unless the suite owns the worker lifecycle.

Keep `PORTFOLIO_HISTORY_RUNTIME_ENABLED=false` for an existing local database until
the explicitly staged 3r migration has completed. Enabling it starts both the durable
history worker and scheduler; startup fails closed if the database or provider graph
is incomplete. Production must explicitly enable this runtime because there is no
separate history-worker deployment.

Production requires a database, JSON logging, disabled API docs, a valid internal auth
secret, a Twelve Data key and canonical market mode. Invalid production configuration
stops startup. Verify Python validation with `test_settings.py` and Next transport
validation with `src/modules/python-api/server/config.test.ts`.

For a long-range CoinGecko crypto backfill, set only
`COINGECKO_PRO_API_KEY` to an Analyst-or-higher server-side key. The historical
factory then uses the fixed `https://pro-api.coingecko.com/api/v3/coins` base and
sends the secret only as `x-cg-pro-api-key`. Without a key it retains the public
base; with only `COINGECKO_DEMO_API_KEY` it retains that base and sends
`x-cg-demo-api-key`. Setting both keys is an invalid configuration. Neither key
belongs in a URL, query string, browser variable, command argument or log.
