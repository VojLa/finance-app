# Delegated context policy

The primary orchestrator discovers authority once and gives each bounded worker the
smallest context capsule that can support its acceptance criteria. Repository access
is not permission to scan the repository.

## Conversation capsule

Always spawn bounded workers with `fork_turns: "none"`. Summarize only:

- the observable user outcome;
- explicit user or product decisions that affect this worker;
- the worker's non-goals and dependencies;
- one unresolved question, when the assignment is a decision consultation;
- the acceptance criteria the worker must prove.

Exclude greetings, commentary, full tool output, successful logs, obsolete attempts,
unrelated user requests, and hidden reasoning. If exact wording matters, include the
smallest relevant user quote in the manifest instead of chat history.

## Documentation capsule

The primary may use maps and generated inventories to find owners. A normal worker
capsule contains exact paths to:

1. `memory/codex_rules.md`;
2. one current domain owner or one invariant/flow document;
3. zero to two additional accepted decisions or cross-cutting invariants;
4. target source files and directly related tests;
5. one focused verification command.

These are defaults, not a correctness ceiling. A genuinely cross-domain worker may
receive more documents only when the primary names each path and explains why one
worker must reconcile them. Never assign `!docs/`, `!planning/`, `ChatGPT/`, a whole
domain directory, or an unbounded diff as reading scope.

Generated inventories are discovery tools for the primary. Give a worker the exact
inventory fragment or resolved paths, not the complete inventory, unless exhaustive
inventory validation is itself the worker's sole read-only task.

Historical `ChatGPT/` files are excluded by default. Include one exact historical
record only when the assignment is to verify provenance or a past acceptance claim;
label it historical and also name the current owner.

## Role-specific scope

- **Scout:** read-only search in named roots with an exact query/file filter and a
  maximum result count; returns candidate paths and evidence. It opens file content
  only when the manifest explicitly permits it and does not produce a broad
  architecture interpretation.
- **Implementer:** exact write files, imported contracts needed by those files, and
  directly related tests. New files require exact allowed paths, not a whole writable
  directory.
- **Tester:** exact behavior/contract, target test location, implementation diff
  summary, and command; no unrelated production scan.
- **Reviewer:** original criteria, changed-file manifest, focused diff, directly
  coupled contract/invariant, and verification summary; no full initiative history.

## Expansion and follow-up

The manifest may pre-allowlist up to two exact additional read-only paths for
imported contracts or adjacent tests. The worker reports every opened expansion and
reason. A worker may identify a different candidate path but must return `BLOCKED`
without opening it. It also stops before another domain, another decision family, or
write-scope expansion; the primary then decides whether to authorize a follow-up,
split the task, or escalate.

Reuse an existing worker only for the same initiative, acceptance criteria, and
bounded workstream; a similar domain alone is not sufficient. A follow-up contains
only changed files, new failure evidence, remaining criteria, and the requested
delta. Do not replay the original prompt, old logs, or unchanged documentation.

## Acceptance check

The primary rejects a handoff that omits consumed/expanded context, reads broad
history without authorization, changes files outside ownership, or claims acceptance
without evidence. Context efficiency never overrides correctness: when more context
is necessary, expand it explicitly or split the task rather than letting the worker
discover without bounds.
