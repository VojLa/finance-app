# Identity bridge

Type: flow
Status: current
Owns: browser-session to Python-principal handoff
Code: NextAuth, server adapters and `app/auth/`
Update when: session, token or protected identity changes

Browser session → server adapter → short-lived internal token → FastAPI token
validation → Python principal → account authorization. Internal tokens and
backend diagnostics never reach the browser.
