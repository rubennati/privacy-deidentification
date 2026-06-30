# Quality Gates

A change is ready when:

- Scope is clear and limited; change is reviewable and documented.
- `make lint`, `make typecheck`, `make test` pass.
- Input validation and security-relevant logic are covered by tests.
- No secrets in the repo; config via environment variables.
- Routing/state files updated when needed.
- No direct commits to `main`.
