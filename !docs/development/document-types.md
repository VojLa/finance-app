# Document types

Type: reference
Status: current
Owns: concise rules for choosing a documentation file type
Code: documentation roots
Update when: a type or owner changes

| Type | Owns |
| --- | --- |
| README | navigation one level down |
| Project/domain map | subsystem routing |
| Domain | business meaning and source of truth |
| Module | non-obvious runtime boundary |
| Flow | one cross-domain sequence |
| Invariant | one exact enforceable rule family |
| Testing | risk-to-evidence mapping |
| Runbook | safe repeatable operation or recovery |
| ADR | decision context and rationale in `!planning` |
| User guide | implemented user-visible workflow |
| Generated inventory | exhaustive deterministic facts |
| Historical evidence | point-in-time audit, not current instruction |

One fact has one owner. Other files link to it rather than copying it.
