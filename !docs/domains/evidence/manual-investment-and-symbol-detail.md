## Manual investment command and symbol detail

Type: historical
Status: historical
Owns: milestone evidence for manual investments and symbol detail
Code: investment and portfolio UI implementation at the recorded milestone
Update when: evidence is archived or replaced by a newer record

R11-G defines one Python-owned manual command for buy, sell, dividend,
interest, staking reward, deposit, withdrawal, fee, currency conversion, and
airdrop. The command validates a complete economic shape, creates no empty
event, and requires both direct legs of a currency conversion. Public money and
quantity values remain exact fixed-scale strings.

The idempotency key is serialized with an advisory lock. A first execution
creates deterministic event/movement identities, increments the account's
canonical revision, and rebuilds Holdings from active canonical history in the
same transaction. An exact replay returns the existing result; a changed
payload conflicts. Database failure rolls back event, movements, revision, and
Holding changes together. Snapshot/current readiness runs only after commit and
its explicit unavailable/conflict state does not make the canonical command
ambiguous; retrying the same command can safely retry readiness.

The symbol-detail read returns positions and active event history only from
accounts accessible to the principal. It performs no provider request, market
evidence write, snapshot selection, valuation fallback, or TypeScript
calculation.
