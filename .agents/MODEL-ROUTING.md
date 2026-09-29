# Model routing

Use the least expensive model that can satisfy the acceptance criteria. Size and
risk are separate: size determines decomposition; risk determines decision and
review strength. Risk overrides size.

## Default roles

| Role | Preferred model and effort | Use for |
| --- | --- | --- |
| Primary acceptance owner | `gpt-6-sol`, medium | triage, dependency order, synthesis, acceptance, and ordinary coordination |
| Cheap bounded worker | `gpt-6-luna`, low | search, inventory, mechanical edits, formatting, known commands, deterministic docs |
| Focused bounded worker | `gpt-6-luna`, medium | clear S implementation, known regression tests, small diff review |
| Standard implementation worker | `gpt-6-sol`, medium | one M slice, normal debugging, integration tests, contract-aligned implementation |
| Risk-focused implementer or reviewer | `gpt-6-sol`, high | closed high-risk invariants, narrow decisions, independent review of risky diffs |
| Difficult decision consultant | `gpt-6-sol`, xhigh | unresolved architecture, auth, money, schema, data-loss, or concurrency decision after a focused high-effort attempt |
| Exceptional consultant | `gpt-6-astra`, high | one narrowly scoped decision or review that remains unresolved after Sol xhigh, or a credible active P0/security/data-loss emergency needing immediate independent scrutiny |

If a named model is unavailable, choose the closest capability role. Do not silently
upgrade an entire initiative to Astra because one subproblem is difficult. A skill
cannot switch the already-running primary model; select Sol when creating the task.

## Routing rules

1. Keep Sol medium as the primary orchestrator for ordinary initiatives.
2. Use Luna only when the task has exact scope, known authority, binary criteria,
   and a deterministic verification command.
3. Use Sol for synthesis, ambiguous local debugging, M implementation, and any
   task that must reconcile more than one layer.
4. A closed high-risk invariant may be implemented with Sol high and independently
   reviewed by a separate Sol high worker. Risk alone does not require Astra.
5. An unresolved high-risk decision gets a narrow Sol high consultation before code
   changes. Move to Sol xhigh only if that leaves a material decision unresolved.
6. Use Astra only with a written escalation packet naming the remaining question,
   Sol's evidence, and why another Sol pass is insufficient. A credible active P0,
   security, or data-loss emergency may go straight to a narrow Astra consultation.
   Return ordinary implementation and acceptance to Sol or Luna afterward.
7. For a bounded worker, explicitly choose the model and effort with
   `fork_turns: "none"`; otherwise a worker may inherit an Astra primary.

## Delegation cost controls

- Do not delegate an obvious XS/S task merely to use a cheaper model.
- Run at most two workers concurrently by default and only for independent work.
- Give every bounded worker a curated manifest with `fork_turns: "none"`, including
  workers using the same model as the primary.
- Do not send whole docs trees, entire successful logs, or unbounded diffs.
- Reuse a worker for a delta review or follow-up in the same scope; send only the
  changed-file list, new evidence, and remaining criteria.
- Prefer one narrow consultation plus Sol implementation over an Astra-owned epic.

## Escalation gates

Escalate only when at least one is true:

- current sources of truth conflict or an accepted decision is missing;
- a minimal reproduction or failing assertion remains unexplained after the prompt
  and scope were narrowed;
- a worker identifies a plausible P0/P1 security, money, schema, data-loss, or
  concurrency defect;
- implementation requires a product choice or material scope expansion;
- a high-risk acceptance review finds a blocker.

Do not escalate formatting, a known dependency issue, broad context confusion, or a
routine test failure before isolating the evidence. Every escalation uses
`templates/ESCALATION-PACKET.md`; never retry the same broad prompt unchanged.

## Evaluation

Before changing the default routing policy, compare representative tasks: one docs
XS, one clear S fix, one ordinary M slice, one integration diagnosis, one money/auth
case, and one schema/concurrency decision. Measure accepted completion, escaped
defects, retries, tokens, latency, and Astra usage. Lower cost counts as an improvement
only when the same acceptance checks pass.
