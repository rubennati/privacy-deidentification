# Claude Code Notes

This file is a thin pointer. The source of truth for all AI tools is `AGENTS.md` at the
project root.

Use the shared `.ai/` workspace as the primary coordination source. Start with:

- `.ai/index.md`
- `.ai/state.md`
- `.ai/routing.md`

Run quality checks via the `Makefile` (`make lint`, `make typecheck`, `make test`). For
commit, push, and merge rules see the "Approval" section in `AGENTS.md`.
