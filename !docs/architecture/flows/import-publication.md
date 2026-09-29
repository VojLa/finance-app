# Import publication

Type: flow
Status: current
Owns: untrusted upload to published finance evidence sequence
Code: imports, jobs, canonical writers, holdings and snapshot refresh
Update when: import stage, retry or publication boundary changes

Register → upload → parse → normalize → deduplicate → classify → canonical post →
Holding rebuild → market-backed refresh → atomic publication. Durable jobs own
leases and retries. Unsupported rows remain issues; incomplete work stays behind
the last complete baseline.
