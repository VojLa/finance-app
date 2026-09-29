# Historical execution evidence

Status: historical

`audits/`, `steps/`, and `history/` preserve point-in-time implementation prompts,
audit reports, and superseded working memory. They are useful for provenance but are
not current Codex instructions and may contain obsolete architecture, commands,
branches, model choices, or migration state.

Current agent guidance lives in [`.agents/`](../.agents/README.md). Current
implemented behavior lives in [`!docs/`](../!docs/README.md), future scope and
accepted decisions in [`!planning/`](../!planning/README.md), and persistent
repository rules in [`memory/codex_rules.md`](../memory/codex_rules.md).

When historical evidence conflicts with those sources, follow the current owner.
