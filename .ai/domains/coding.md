# Coding Domain

- Backend: Python 3.12, FastAPI, Pydantic. Type hints required on public APIs; `ruff` +
  `mypy` (strict) must pass. Functions small and single-purpose.
- Frontend: React + TypeScript (strict), Vite, Tailwind. ESLint must pass. No
  `dangerouslySetInnerHTML` without justification.
- Validate input at the trust boundary (file type/size), server- and client-side.
- Structured JSON logging; never log file contents or PII.
- Keep changes small and testable. Security-relevant logic is test-driven.
