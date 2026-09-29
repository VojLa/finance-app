# Active Codex workflow

This directory is the only owner of current agent execution guidance.

## Routing

- `skills/finance-orchestrator/SKILL.md` — triage, delegation, acceptance, and escalation;
- `skills/finance-development/SKILL.md` — bounded implementation and review;
- `skills/finance-docs/SKILL.md` — documentation impact;
- `MODEL-ROUTING.md` — model and reasoning choices;
- `CONTEXT-POLICY.md` — documentation and conversation budgets for delegated work;
- `STEP-SIZING.md` — size, risk, and decomposition;
- `WORKFLOW.md` — initiative lifecycle and verification ladder;
- `templates/` — task, delegation, result, escalation, and acceptance contracts.

The recommended primary profile is `gpt-6-sol` with medium reasoning. That profile must
be selected when the Codex task starts; repository instructions cannot replace an
already-running primary model. The orchestrator may select different models for
bounded workers when the runtime supports model overrides.

`ChatGPT/` contains historical steps and audits. Historical records may explain why
a change happened, but they never override `.agents/`, current `!docs/`, accepted
`!planning/` decisions, runtime code, tests, OpenAPI, or Alembic evidence.
