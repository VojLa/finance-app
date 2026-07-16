# Parser Contract

Parser responsibilities:

- Read source-specific rows.
- Normalize dates, currencies, quantities, amounts, fees, and identifiers.
- Emit parsed rows or parse issues.
- Preserve enough raw context to debug unsupported rows.

Parser output must be deterministic and covered by fixture tests.

