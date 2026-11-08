# kivy_calendar

A calendar app to track things easier

## Status

Early stage — scaffolding in progress.

- **Backend**: package skeleton under `backend/src/` (API, Google Calendar integration, sync, cache, retry queue) with tooling configured (FastAPI, ruff, mypy, pytest). No API implemented yet.
- **Client**: not started.
- **Tests**: minimal smoke test.

## Google Calendar credentials

The backend authenticates a single Google account with a Desktop-app OAuth
client. Keep `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and
`GOOGLE_REFRESH_TOKEN` in an untracked `.env` file (see `.env.example`); never
commit them.

To obtain the refresh token once, export the client id and secret and run the
local browser helper from the repository root:

```sh
PYTHONPATH=backend/src python -m google_calendar.auth
```

Copy the printed `GOOGLE_REFRESH_TOKEN` into `.env`. The helper requests only
`https://www.googleapis.com/auth/calendar.events` and does not use a public
web redirect.

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
