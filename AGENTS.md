# AGENTS.md


## Project

This repo is a self-hosted scheduling app built on top of Google Calendar, using the python programming language and kivy framework for the gui.

Google Calendar is the source of truth. The app creates and displays events but never replaces the calendar: every event is written to Google Calendar, so it shows up on the phone even when the app is off.

Two parts:
- Backend (Python): holds the Google credentials, syncs and caches events, exposes an API.
- Client (Python + Kivy): the gui, talks only to the backend, reachable over the home VPN/LAN.


## Layout

- backend/src/: API, Google Calendar integration, sync, local cache, retry queue
- client/src/: Kivy screens and widgets, API client. No calendar logic here.
- tests/: mirrors the src/ layout of each part
- docker/: Dockerfile and Compose files for deploying the backend

## Conventions

- Language and version: Python 3.14 with type hints (check Kivy and buildozer support for the version before changing it)
- Error handling rule: return errors, do not throw across module boundaries
- Naming rule: follow flake8 and mypy standard
- Match the style of the file you are editing over any general preference.
- Add or update a test for every behavior change.
- Calendar logic (time zones, recurrence, free-slot finding) lives in the backend only. The client stays thin.
- Google is the source of truth. The local cache is disposable and must be rebuildable by re-syncing.
- Writes go to Google first. Show an event as saved only after Google confirms it.
- Use a client-generated event ID for every create so a retry cannot make duplicate events.
- Store times with explicit IANA time zone names. Never use naive datetimes.
- Keep custom event data in Google extended properties; the database is only a cache.
- Google or network failures (offline, rate limit) must produce an error result and a retry, never a crash.

## Boundaries

Always:
- Read a file before you edit it.
- Keep changes to what the task asks for; mention other problems you notice instead of fixing them.
- Run the tests, flake8 and mypy before calling a task done.

Ask first:
- Adding a dependency.
- Changing a public API (backend endpoints the client uses), a database schema, CI configuration, or Google OAuth scopes.
- Deleting files.

Never:
- Commit secrets, or read `.env` files, credentials, or token files (Google client secret, refresh tokens, backend API token).
- Run tests or scripts against the real primary calendar. Use mocks or a dedicated test calendar.
- Make the backend reachable from the public internet or bind it to all interfaces.
- Push to `main`, force-push, or rewrite history.
- Edit generated files: `dist/, *.lock, .buildozer/, bin/`. Change the generator instead.

## More detail, loaded only when needed

- Architecture: `docs/architecture.md` (to be written)
- Release process (APK build, backend deploy): `docs/releasing.md` (to be written)
- Subdirectory rules live in their own AGENTS.md, e.g. `backend/AGENTS.md` or `client/AGENTS.md`; the closest file to the code wins.
