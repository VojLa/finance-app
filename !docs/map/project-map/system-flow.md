# System dependency flow

```text
Identity → Accounts
Accounts → Cash / Imports / Investments
Imports → canonical writers → Holdings
Canonical finance + market evidence → Valuation
Valuation → Portfolio / Dashboard
Canonical finance + historical evidence → Portfolio history
```

These arrows describe data dependency, not permission to bypass Python
authorization or a domain service boundary. Detailed dependencies are owned by
the [individual domain maps](../domain-map/README.md).
