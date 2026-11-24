# Changelog

All notable changes to Kivy Calendar. Versions follow the rules in
`AGENTS.md` (Versioning); planned versions are in `ROADMAP.md`.

## [Unreleased]

## [0.0.3] - 2026-11-24

- Saving an event while Google is unreachable on an empty list now shows the
  "will sync automatically" notice instead of "No events yet".
- Creating an event that names an occurrence of a recurring series is
  rejected with `invalid_argument` (HTTP 400) instead of inserting a separate
  event in Google; occurrences are edited with an update.
- The new-event form's default start and end are always real times in the
  zone, also on daylight-saving change nights.
- The Kivy client type-checks with mypy (Kivy imports ignored), and CI runs
  it.

## [0.0.2] - 2026-11-24

- The main screen shows the app version next to the "Calendar" title.

## [0.0.1] - 2026-11-24

First tracked version: the self-hosted desktop app as merged in #30.

- Backend: FastAPI API behind a bearer token, Google Calendar provider with
  calendar list, events and moves, write-through sync service, SQLite cache,
  durable retry queue with a background worker, free-slot search, OAuth
  refresh-token helper.
- Client: Kivy app in a light-blue theme with the Inter font; event list
  grouped by day with name and date filters, sort, Sync and Refresh; add and
  edit form with calendar and time zone dropdowns, a month date picker, an
  hour-and-minute time sheet, "Suggest a free time" and delete confirmation.
- Layout: shared calendar logic in `shared/`, backend in `backend/`, client in
  `client/`, placeholder for the planned Android build in `android/`.
- Deployment and CI: Docker Compose for the backend; GitHub Actions runs ruff,
  mypy, backend and client tests, and a Docker build.
