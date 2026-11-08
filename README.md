# kivy_calendar

A calendar app to track things easier

## Status

The backend foundations are implemented; the client has not started.

- **Backend**: domain event model, SQLite cache, durable retry queue, Google
  Calendar provider (list/create/patch/delete), OAuth credential helper, and a
  write-through sync service. The FastAPI app currently exposes only `/health`;
  the calendar API endpoints are still planned.
- **Client**: not started.
- **Tests**: backend unit tests use an in-memory fake provider and never call
  Google or touch a real calendar.

## Google Calendar credentials

The backend authenticates a single Google account with a Desktop-app OAuth
client. Keep `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and
`GOOGLE_REFRESH_TOKEN` in an untracked `.env` file (see `.env.example`); never
commit them.

The app does **not** load `.env` itself. Export the variables into the backend
process environment, for example:

```sh
set -a
. ./.env
set +a
```

or supply them through your deployment tool.

`GOOGLE_CALENDAR_ID` selects the calendar the backend reads and writes. It
defaults to `primary`; point development and test runs at a dedicated test
calendar rather than the real primary calendar.

To obtain the refresh token once, export the client id and secret and run the
local browser helper from the repository root:

```sh
PYTHONPATH=backend/src python -m google_calendar.auth
```

Copy the printed `GOOGLE_REFRESH_TOKEN` into `.env`. The helper requests only
`https://www.googleapis.com/auth/calendar.events` and does not use a public web
redirect.

## Known limitations

- All-day events are not supported yet. `list_events` skips them and `get_event`
  returns `INVALID_EVENT`.
- Google allows timed events whose ISO `dateTime` carries only an offset. A zero
  offset is mapped to `UTC`; an event with a non-zero offset and no IANA
  `timeZone` cannot be mapped, so `list_events` skips it and `get_event`
  returns `INVALID_EVENT`. Events created by other clients without an explicit
  zone may therefore be skipped.
- Google `403` responses are treated as retryable upstream errors. `401` and
  OAuth refresh failures are permanent authentication errors.

## Planned

- FastAPI endpoints for the calendar/scheduling API
- Kivy client
- Docker Compose deployment
- CI/CD via GitHub Actions

## Tech stack

- Python 3.14
- FastAPI (backend), Kivy (client)
- SQLite (local cache)
- Docker, GitHub Actions
