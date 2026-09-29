# Frontend technical surfaces

Type: module
Status: current
Owns: mapping of Next.js pages, shared components and same-origin routes to domains
Code: `src/app/`, `src/components/`, `src/modules/`, `src/lib/`
Update when: a page group, shared component boundary or adapter surface changes

| Surface                                   | Owning domain or boundary                                                                      |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `/`, root layout and providers            | frontend platform shell                                                                        |
| `/login`, `/register`                     | identity and access                                                                            |
| `/accounts`, `/settings`                  | accounts/access and application settings                                                       |
| `/transactions`, `/categories`, `/budget` | cash flow                                                                                      |
| `/import`, `/imports`                     | import upload and durable job state                                                            |
| `/portfolio/add`, `/portfolio/[symbol]`   | investment command and instrument detail                                                       |
| `/portfolio`                              | portfolio snapshot and history read models                                                     |
| `/dashboard`                              | operational and snapshot-backed dashboard projections                                          |
| `src/app/api/**`                          | server-only identity/transport bridge mapped in [API routes](../../api/routes-and-adapters.md) |

Reusable presentation primitives live in `src/components/{forms,charts,layout,portfolio,tables,ui}`.
Domain-aware browser contracts and view models live in `src/modules`; general auth,
formatting, dates, validation and serialized-refresh utilities live in `src/lib`.
Pages and components may format exact server results but cannot query PostgreSQL,
authorize accounts or calculate missing finance.
