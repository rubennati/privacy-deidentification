# Architecture Domain

- Two services orchestrated by Docker Compose: `frontend` (nginx; serves the SPA and
  reverse-proxies `/api` to the backend) and `backend` (FastAPI).
- Single external entry point: `http://localhost:8080`. The backend is reachable only on
  the internal compose network (least exposure).
- Layer separation: presentation (frontend) ↔ API/business (backend) ↔ storage (volume).
  Business logic knows no HTTP details beyond the API layer.
- External systems (storage now; DB/queue later) sit behind a service/adapter.
- Record major structural decisions as ADRs under `docs/adr/`.
