# Changelog

All notable changes to Kivy Calendar. Versions follow the rules in
`AGENTS.md` (Versioning); planned versions are in `ROADMAP.md`.

## [Unreleased]

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
