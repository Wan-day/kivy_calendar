# kivy_calendar

A calendar app to track things easier

## Status

Early stage — scaffolding in progress.

- **Backend**: package skeleton under `backend/src/` (API, Google Calendar integration, sync, cache, retry queue) with tooling configured (FastAPI, ruff, mypy, pytest). No API implemented yet.
- **Client**: not started.
- **Tests**: minimal smoke test.

## Planned

- FastAPI backend exposing the calendar/scheduling API
- Google Calendar sync (Google is source of truth)
- Kivy client
- Docker deployment
- CI/CD via GitHub Actions

## Tech stack

- Python 3.14
- FastAPI (backend), Kivy (client)
- SQLite (local cache)
- Docker, GitHub Actions
