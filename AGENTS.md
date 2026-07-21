# Codex Local Instructions

Read this file before answering or changing code in this repository.

## Project Sources Of Truth

- [`!docs/`](!docs/) contains the complete current architecture and technical documentation of the project.
- [`!planning/`](!planning/) contains the complete product and implementation design, roadmap, scope, architectural decisions, and backlog.
- [`CHATGPT/`](CHATGPT/) contains the instructions, workflow, and templates to use when designing, planning, implementing, or reviewing changes with ChatGPT.
- `memory/codex_rules.md` contains persistent repository-specific working rules.

Treat these folders as the entry points. Do not add links to their individual documents here. Their internal indexes and documents own all more detailed navigation so that `AGENTS.md` remains a stable, short repository guide.

## Required Reading

Before working on a task:

1. Read `memory/codex_rules.md`.
2. Read the relevant parts of [`!docs/`](!docs/) for the current architecture and technical constraints.
3. Read the relevant parts of [`!planning/`](!planning/) for the intended design, accepted decisions, current scope, and roadmap.
4. Follow [`CHATGPT/`](CHATGPT/) for the appropriate design, planning, implementation, and review workflow.

When architecture or design is unclear or inconsistent, resolve and document it in the appropriate source folder before making a large implementation decision. Keep detailed cross-references inside `!docs/`, `!planning/`, or `CHATGPT/`, not in this file.

## Working Rules

- Keep the current application working while changes are introduced in small, reversible steps.
- Do not duplicate domain rules across TypeScript, Python, and Rust without explicit boundaries and parity tests.
- Keep database ownership and migrations aligned with the documented architecture and accepted decisions.
- Be explicit when code is temporary scaffolding rather than the target architecture.
- Do not introduce a new framework or architectural direction without first recording the decision in the relevant documentation or planning folder.

## Verification

For current TypeScript code, prefer:

- `npx.cmd tsc --noEmit`
- `npm.cmd test`
- `npm.cmd run lint`

Avoid `npm run build` while `next dev` is running because the `.next` cache has repeatedly caused missing chunk and runtime errors.
