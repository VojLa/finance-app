# Step Log Template

Use this optional record after each completed step to estimate future capacity from actual project data. Store persistent logs in a suitable planning issue, spreadsheet, or a dedicated log file only when the data is useful; do not create repository churn for every minor task.

```markdown
# <STEP_ID> - <STEP_TITLE> execution record

## Identification

- Date started: `<YYYY-MM-DD>`
- Date completed: `<YYYY-MM-DD>`
- Pull request: `<NUMBER>`
- Base SHA: `<SHA>`
- Final SHA: `<SHA>`
- Size class before implementation: `S / M / L / XL`
- Risk class: `normal / high`

## Scope

- Primary capability: `<ONE SENTENCE>`
- Layers affected: `<API / service / persistence / schema / frontend / tests / docs>`
- Public contract changed: `yes / no`
- Schema or migration changed: `yes / no`
- Security-sensitive: `yes / no`

## Agentic usage

Record values only when the interface exposes them clearly.

- Weekly agentic limit before ChatGPT design: `<PERCENT_REMAINING_OR_UNKNOWN>`
- After ChatGPT design/specification: `<PERCENT_REMAINING_OR_UNKNOWN>`
- After Codex implementation and local repair: `<PERCENT_REMAINING_OR_UNKNOWN>`
- After ChatGPT PR review: `<PERCENT_REMAINING_OR_UNKNOWN>`
- Estimated total usage for the step: `<PERCENTAGE_POINTS_OR_UNKNOWN>`

Do not claim precision below what the interface displays.

## Change size

- Files changed: `<COUNT>`
- Insertions: `<COUNT>`
- Deletions: `<COUNT>`
- Total changed lines: `<COUNT>`
- Initial ChatGPT/GitHub implementation lines, if applicable: `<COUNT_OR_NOT_APPLICABLE>`
- Codex repair lines, if measurable: `<COUNT_OR_UNKNOWN>`

## Validation effort

- Targeted test runs: `<COUNT>`
- Full quality-gate runs: `<COUNT>`
- Failed validation loops: `<COUNT>`
- Main causes of repairs:
  - `<typing / tests / architecture / missing behavior / formatting / environment / other>`

## Outcome

- Final status: `merged / ready / blocked / abandoned`
- ChatGPT review findings:
  - Blocker: `<COUNT>`
  - High: `<COUNT>`
  - Medium: `<COUNT>`
  - Low: `<COUNT>`
- CI result: `<PASS / FAIL / BLOCKED / NOT RUN>`

## Lessons for the next step

- What consumed unnecessary work: `<TEXT>`
- What should be moved into the reusable skill or AGENTS.md: `<TEXT>`
- What should be added to the next specification: `<TEXT>`
- Was the step sized correctly: `<YES / TOO LARGE / TOO SMALL>`
```

## Suggested comparison metrics

After several steps, compare steps within the same size and risk class:

- percentage points of agentic usage per completed step
- changed lines per percentage point, used only as a rough indicator
- repair lines as a share of final changed lines
- failed quality-gate runs per step
- findings discovered after Codex completion
- elapsed time from approved specification to green branch

A decreasing repair share and fewer review findings are stronger signals of workflow improvement than raw line throughput alone.
