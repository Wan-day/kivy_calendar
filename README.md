# kivy_calendar

A calendar app to track things easier

## Status

Version **0.0.1** (see `VERSION`). Changes per version are in
[CHANGELOG.md](CHANGELOG.md); the plan up to the 1.0.0 Android release is in
[ROADMAP.md](ROADMAP.md).

The backend, the FastAPI calendar API, a basic runnable Kivy client, a Docker
Compose deployment, and CI are implemented. A standalone Android build that
uses the phone's own calendar instead of the backend is planned (`android/`).

## Layout

| Folder | What it holds |
| --- | --- |
| `shared/src/` | Calendar logic both builds use: `core` (errors, config, SQLite helper), `domain` (event and calendar models, time zones), `slots` (free-slot search) and `calendar_provider` (the provider interface). No FastAPI or Google imports. |
| `backend/src/` | Desktop/self-hosted backend: FastAPI API, Google Calendar provider and OAuth helper, sync service, cache, retry queue. |
| `client/src/` | Kivy app: screens, theme, and the HTTP client for the backend. |
| `android/` | Android build (planned): Android calendar provider, in-process service, `buildozer.spec`. |
| `tests/` | Tests for `shared` and `backend`, by module. Client tests live in `client/tests/`. |
| `docker/` | Dockerfile and Compose file for the backend. |

- **Backend**: domain event model, SQLite cache, durable retry queue drained by
  a background retry worker, Google Calendar provider (calendars, events, moves),
  free-slot search, OAuth credential helper, a write-through sync service, and a
  FastAPI app behind bearer-token auth.
- **Client**: Kivy app (`client/src/kivy_calendar`) in a light-blue theme with
  the bundled Inter font. It has an event list grouped by day (name and date
  filters, sort, Refresh, Sync) and an add/edit form with calendar and time
  zone dropdowns, a month date picker, an hour-and-minute time sheet,
  "Suggest a free time", and delete confirmation. Tap an event to edit or
  delete it.
- **Deployment**: Docker Compose file for the backend (`docker/`).
- **CI**: GitHub Actions runs ruff, mypy, backend and client tests, and a Docker
  build.
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

`GOOGLE_CALENDAR_ID` is the default calendar for new events. It defaults to
`primary`; point development and test runs at a dedicated test calendar rather
than the real primary calendar. The backend discovers every selected calendar
the account can read through Google's `calendarList` API, so Work and shared
calendars are read as well. New events go to `GOOGLE_CALENDAR_ID`, while edits
and deletes target the calendar the event came from. Only owner and writer
calendars are offered as save or move targets (`GET /calendars`). Calendars
named after an email address are hidden unless they are the primary calendar or
`GOOGLE_CALENDAR_ID`.

To obtain the refresh token once, export the client id and secret and run the
local browser helper from the repository root:

```sh
PYTHONPATH=backend/src:shared/src python -m google_calendar.auth
```

Copy the printed `GOOGLE_REFRESH_TOKEN` into `.env`. The helper requests
`https://www.googleapis.com/auth/calendar.events` and
`https://www.googleapis.com/auth/calendar.calendarlist.readonly`; it does not
use a public web redirect.

If you already have a refresh token from an older version of the app, you
**must** re-run the helper and replace `GOOGLE_REFRESH_TOKEN`. A token created
before the calendar-list scope was added does not carry it, so `GET /calendars`,
`POST /sync`, and `POST /slots/free` fail with `auth_error` (401) until the new
scope is granted. The backend log names the missing
`calendar.calendarlist.readonly` scope.

The backend returns generic error messages to clients, so check its log for the
detail. If it logs `Google Calendar is not configured: missing Google OAuth
environment variables: ...`, the backend process did not receive those
variables. Export `.env` in the same shell that starts the server and restart
it; editing `.env` has no effect on a running process. A `401` with
`authentication failed` means the bearer token is missing or does not match the
backend's `BACKEND_API_TOKEN`; the log says which (`missing bearer token` or
`invalid bearer token`). The client and backend must use the same
`BACKEND_API_TOKEN`.

## Configuration

| Variable | Read by | Default | Purpose |
| --- | --- | --- | --- |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` | backend | none | OAuth credentials for Google calls (see above) |
| `GOOGLE_CALENDAR_ID` | backend | `primary` | Default calendar for new events |
| `GOOGLE_CALENDAR_TIME_ZONE` | backend | `UTC` | IANA zone used for all-day event boundaries |
| `BACKEND_API_TOKEN` | backend, client | none | Bearer token; must match on both sides |
| `RETRY_WORKER_INTERVAL_SECONDS` | backend | `30` | Seconds between retry cycles; `0` disables the worker |
| `KIVY_CALENDAR_DB_PATH` | backend | `$XDG_DATA_HOME/kivy_calendar/kivy_calendar.db` (else `~/.local/share/...`) | SQLite file for the cache and retry queue |
| `KIVY_CALENDAR_API_BASE_URL` | client | `http://localhost:8000` | Backend URL |
| `BACKEND_BIND_IP` | Docker Compose | `127.0.0.1` | Host IP the backend port is published on |

## Running the backend

Install the backend into the project virtual environment, then start it on
loopback with the Google variables and `BACKEND_API_TOKEN` exported (see the
credentials and configuration sections):

```sh
python -m pip install ./shared ./backend
PYTHONPATH=backend/src:shared/src uvicorn api.main:app --host 127.0.0.1 --port 8000
```

## Running the client

The Kivy client talks to the backend over HTTP. Install it into the project
virtual environment:

```sh
python -m pip install -e ./client
```

Point it at the running backend and give it the same API token the backend
expects:

```sh
export BACKEND_API_TOKEN=...
export KIVY_CALENDAR_API_BASE_URL=http://127.0.0.1:8000
python -m kivy_calendar
```

`KIVY_CALENDAR_API_BASE_URL` defaults to `http://localhost:8000`. Without
`BACKEND_API_TOKEN` the window still opens, but it shows a configuration
message instead of the event list.

The main screen's **Refresh** (circular arrow) reloads the backend's cache.
**Sync** (down arrow) asks the backend to rebuild its cache from Google first.
Events are grouped under day headings; an event in progress is tinted and
marked **Now**. The **From** and **To** chips open a month picker, with
**Clear** to remove the date.

In the event form, the calendar and time zone dropdowns are filled from the
backend. The time zones come from `GET /timezones`. **Starts** and **Ends** each
have a date chip and a time chip. The date chip opens a month picker. The time
chip opens a sheet with an hour grid (`00`-`23`) and that hour's minutes in
5-minute steps; it opens at the current value, and the current hour has a coral
outline. Picking a new start date or time moves the end to keep the duration
(all-day events keep the same number of days). Each time is read in its own
time zone, so the chosen zone decides the instant. **Suggest a free time** fills
in the first free slot in the next 7 days.

## Backend API

The FastAPI backend serves the calendar API. Unless noted, endpoints expect an
`Authorization: Bearer <BACKEND_API_TOKEN>` header.

- `GET /health` (unauthenticated)
- `GET /calendars`: the calendars events can be saved to, primary first
- `GET /timezones`: curated IANA zones with `name`, `label`, and
  `utc_offset_minutes` at request time (DST-aware)
- `GET /events`: cached events, ordered by start time
- `GET /events/{event_id}`: one cached event; `?calendar_id=` picks the calendar
- `POST /events`: create in Google, then cache (201)
- `PATCH /events/{event_id}`: update in Google, then cache. `?source_calendar_id=`
  names the calendar the event is in now; the body's `calendar_id` is where it
  ends up, so a different value moves it
- `DELETE /events/{event_id}`: delete in Google and drop the cached copy (204);
  `?calendar_id=` picks the calendar
- `POST /sync`: rebuild the cache from Google; returns `{"synced": <count>}`
- `POST /slots/free`: find free windows for a new event

The API cache is keyed by calendar and event id, so the same id can exist in
several calendars. A `GET`, `PATCH`, or `DELETE` that names no calendar for an
id cached in several returns `400 invalid_argument`. Pass `calendar_id` or
`source_calendar_id` to disambiguate.

The interactive docs (`/docs`, `/redoc`) and the schema (`/openapi.json`) are
disabled and return `404`.

### Errors

Failures are returned as structured JSON error bodies with a generic message.
Upstream detail (Google error bodies, URLs, file paths) is logged server-side
only:

```json
{"error": {"code": "not_found", "message": "not found"}}
```

| Code | HTTP status |
| --- | --- |
| `invalid_argument` | 400 |
| `auth_error` | 401 |
| `permission_denied` | 403 |
| `not_found` | 404 |
| `already_exists`, `invalid_state` | 409 |
| `invalid_event` | 422 |
| `upstream_error` | 503 |
| `storage_error` | 500 |

A Google `403` with a rate-limit or quota reason is `upstream_error`. Other
`403` responses are `permission_denied`.

### Queued writes

When Google is unreachable (`upstream_error`), a create, update, or delete is
queued for retry instead of failing. The response is `202`, with the event body
and `"status": "queued"` for create and update. A delete returns
`{"status": "queued"}`. A queued event is not cached until Google confirms it.
Permanent failures (`invalid_argument`, `auth_error`, `permission_denied`,
`not_found`, `already_exists`) are never queued.

### Retry worker

A background task in the backend process replays queued writes every
`RETRY_WORKER_INTERVAL_SECONDS` seconds (default `30`). Setting it to `0`, or a
negative value, disables the worker, and queued writes are then not replayed.
Blank or unparseable values use the default. A failed replay waits
exponentially longer before the next try, starting at 30 seconds, doubling, and
capped at one hour. After 5 attempts the job stops. The queue lives in the
SQLite database, so queued writes survive restarts.

### Sync and the cache

The cache changes only through successful writes and `POST /sync`. Nothing
re-syncs automatically. `POST /sync` replaces the whole cache with Google's
events from 60 days ago to 365 days ahead. A failed sync leaves the existing
cache untouched.

### Free-slot search

`POST /slots/free` takes `duration_minutes` (at least 1), `window_start`,
`window_end` (both timezone-aware ISO 8601), and `time_zone` (IANA, default
`UTC`). It reads Google directly for that window, not the cache, and returns
free slots as datetimes in `time_zone`. Events marked transparent ("free") in
Google never block time. Timed events otherwise block. All-day events block only
when they are opaque and on a writable calendar.

## Running the backend with Docker

```sh
cp .env.example .env   # fill in the values
docker compose --env-file .env -f docker/compose.yml up -d --build
```

Run it from the repository root. `--env-file .env` makes Compose read
`BACKEND_BIND_IP` from the root `.env`. Without it, Compose looks for a `.env`
next to the compose file (`docker/.env`) and the port stays on `127.0.0.1`. A
`BACKEND_BIND_IP` exported in the shell overrides the file.

The port is published only on `BACKEND_BIND_IP` (default `127.0.0.1`); never
set it to `0.0.0.0`. The container listens on all interfaces inside its own
network, so the host publish address is what limits access. The container runs
as an unprivileged user (`app`, uid 10001). The cache and retry queue live in the
`backend_data` named volume at `/data`. `.dockerignore` keeps `.env`, databases,
and credential files out of the build context. The bearer token travels over
plain HTTP, so reach the backend only through the VPN or a TLS reverse proxy.

## Known limitations

- Timed events with a non-zero UTC offset and no IANA zone (some events created
  by other clients) are skipped by sync and never cached, so `GET /events/{id}`
  returns `404` for them.
- Recurring events are expanded by Google into one event per occurrence. The
  cache holds only the sync window, so occurrences outside it are not cached
  until a sync covers them.
- Google `401` responses and OAuth refresh failures are permanent `auth_error`s.
  Google `429`, `5xx`, and rate-limit `403` responses are retryable
  `upstream_error`s. Writes hitting them are queued; reads return `503`.

## Development

Install the backend with its test and lint tools, then run the checks from the
repository root:

```sh
python -m pip install ./shared ./backend pytest httpx mypy ruff
pytest
ruff check .
mypy shared/src backend/src tests
```

Client tests need a display. CI runs them under a virtual X server:

```sh
python -m pip install ./client pytest
cd client && SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 KIVY_NO_ARGS=1 KIVY_NO_CONSOLELOG=1 xvfb-run -a -s "-screen 0 1280x1024x24" pytest
```

`.github/workflows/ci.yml` runs ruff, mypy, backend tests, client tests under
Xvfb, and a Docker image build on pushes to `main` and on pull requests.

## Tech stack

- Python 3.14
- FastAPI (backend), Kivy (client)
- Google Calendar API v3
- SQLite (local cache and retry queue)
- Docker, GitHub Actions
