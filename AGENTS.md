# AGENTS.md


## Project

This repo is a scheduling app built on top of Google Calendar, using the Python programming language and the Kivy framework for the GUI.

The app creates and displays events but never replaces the calendar: every event ends up in the user's calendar account, so it shows up everywhere even when the app is off.

It ships as two builds from this one repository:
- Desktop / self-hosted (exists today): the Kivy client talks only to a Python backend over the home VPN/LAN. The backend holds the Google credentials, syncs and caches events, and exposes an API.
- Android (planned, standalone): the Kivy app reads and writes the phone's own calendar store (Android `CalendarContract`) in-process. Android's account sync carries changes to Google Calendar. No server, no Google sign-in, no credentials. Sideloaded APK only; minimum Android 8.0 (API 26).

Both builds share the calendar logic in `shared/` and the screens in `client/`; only the layer that talks to a calendar differs.


## Layout

- shared/src/: code both builds use. `core` (errors, config, SQLite helper), `domain` (models, time zones), `slots` (free-slot search), `calendar_provider` (the provider interface). No FastAPI, Google client or backend imports here.
- backend/src/: API, Google Calendar provider and OAuth helper, sync, local cache, retry queue. Desktop/self-hosted only.
- client/src/: Kivy screens, theme and widgets, HTTP client for the backend. No calendar logic here.
- android/: Android calendar provider, in-process calendar service, `buildozer.spec` (planned).
- tests/: tests for shared/ and backend/, one folder per module; client tests live in client/tests/.
- docker/: Dockerfile and Compose files for deploying the backend.

## Conventions

All builds:
- Language and version: Python 3.14 with type hints (check Kivy, buildozer and python-for-android support for the version before changing it).
- Error handling rule: return errors, do not throw across module boundaries.
- Naming and style: follow ruff and mypy (the configs in each pyproject.toml).
- Match the style of the file you are editing over any general preference.
- Add or update a test for every behavior change.
- Calendar logic (time zones, recurrence, free-slot finding) lives in shared/ or in a provider, never in the screens.
- Store times with explicit IANA time zone names. Never use naive datetimes.
- Calendar failures (offline, rate limit, permission denied) must produce an error result, never a crash.

Desktop / self-hosted build:
- The client stays thin and talks only to the backend.
- Google is the source of truth. The local cache is disposable and must be rebuildable by re-syncing.
- Writes go to Google first. Show an event as saved only after Google confirms it.
- Use a client-generated event ID for every create so a retry cannot make duplicate events.
- Keep custom event data in Google extended properties; the database is only a cache.

Android build:
- The phone's calendar store is the source of truth; Android syncs it with each account. There is no backend and no local cache of events.
- Writes go to the phone's calendar store and count as saved once it accepts them; Android uploads them later.
- Android assigns event IDs. Store the app's own ID in `UID_2445` so a repeated save finds the event instead of duplicating it.
- Extended properties are not available (only sync adapters may write them); do not depend on them.
- Request only `READ_CALENDAR` and `WRITE_CALENDAR`; no internet permission.
- Calendar access runs off the UI thread.

## Versioning

The app version lives in `VERSION` (major.minor.patch, started at 0.0.1) and is repeated in `shared/`, `backend/` and `client/` `pyproject.toml`; a test keeps them equal.

- 0.0.x (patch): small changes that don't change the app as a whole, e.g. an extra button or a bug fix.
- 0.x.0 (minor): a new feature, e.g. a new calendar view. Resets the patch number.
- x.0.0 (major): something big changes, e.g. a whole new provider or a public release. Resets minor and patch.
- Every PR that changes the app's behavior bumps the version in all four files by the rule above and adds its entry to `CHANGELOG.md` under that version. Docs-, test- or CI-only PRs keep the version and add nothing.
- Planned versions up to 1.0.0 are in `ROADMAP.md`; keep it in step when a version ships or the plan changes.

## Agent workflow

- When creating subagents for coding tasks, give them just enough context to complete the task.
- Each distinct change is recorded in its own commit.
- When working on a specific part of the app, use its own feature branch.
- Pull requests are the delivery mechanism: the agent opens PRs for feature branches and does not merge or push to `main`; the user is the final entity who checks, reviews and accepts PRs.

## Boundaries

Always:
- Read a file before you edit it.
- Keep changes to what the task asks for; mention other problems you notice instead of fixing them.
- Run the tests, ruff and mypy before calling a task done.
- Keep the desktop build and its tests working when changing shared/ or client/.

Ask first:
- Adding a dependency.
- Changing a public API (backend endpoints the client uses, or the `CalendarProvider` interface in shared/), a database schema, CI configuration, Google OAuth scopes, or Android permissions.
- Deleting files.

Never:
- Commit secrets, or read `.env` files, credentials, or token files (Google client secret, refresh tokens, backend API token, Android signing keystore and its passwords).
- Run tests or scripts against a real personal calendar. Use mocks, the fake calendar store, or a dedicated test calendar on an emulator.
- Make the backend reachable from the public internet or bind it to all interfaces.
- Push to `main`, force-push, or rewrite history.
- Edit generated files: `dist/, *.lock, .buildozer/, bin/`. Change the generator instead.

## More detail, loaded only when needed

- Android build plan and status: `android/README.md`
- Architecture: `docs/architecture.md` (to be written)
- Release process (APK build, backend deploy): `docs/releasing.md` (to be written)
- Subdirectory rules live in their own AGENTS.md, e.g. `backend/AGENTS.md` or `client/AGENTS.md`; the closest file to the code wins.
