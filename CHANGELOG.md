# Changelog

All notable changes to Kivy Calendar. Versions follow the rules in
`AGENTS.md` (Versioning); planned versions are in `ROADMAP.md`.

## [Unreleased]

## [0.4.0] - 2026-11-24

- The Sync button on Android asks Android to sync each phone account that has
  calendars, then reloads the list when the sync is finished (or after 30
  seconds). Calendars that are only on the phone (LOCAL) are skipped. A failed
  sync shows a readable error.
- After saving or deleting on Android, the list says "Saved on the phone.
  Android syncs it to your account." (or "Deleted on the phone. ...").
- Event cards whose change has not reached the account yet show a "Not synced
  yet" tag. Calendars that are only on the phone never show it.
- Desktop is unchanged.

## [0.3.0] - 2026-11-24

- Android saves to the phone's calendar: create, edit and delete single
  events, and move them to another calendar by picking it in the form.
  Saving the same new event twice keeps one copy. All-day events and each
  end's time zone are stored the way Android expects.
- Occurrences of repeating events open read-only on Android, with a note to
  edit them in the phone's calendar app.
- The calendar and time-zone dropdown rows scale with screen density, and the
  All day switch fades when it is locked.
- The delete dialog says the event will be deleted from your calendar (it no
  longer names Google Calendar).

## [0.2.0] - 2026-11-24

- Android reads the phone's own calendars. On first start the app asks for
  calendar access (a screen with Allow access, and Open app settings after a
  refusal), then lists the events of every visible calendar on the phone from
  30 days back to 180 days ahead. Recurring events show as separate
  occurrences; cancelled ones and hidden calendars are left out.
- The calendar dropdown offers the phone calendars that accept new events,
  and "Suggest a free time" works from the phone's events.
- New events start in the phone's time zone on Android.
- Saving on Android shows "not available yet" until 0.3.0.
- The APK requests `READ_CALENDAR` and `WRITE_CALENDAR`.

## [0.1.1] - 2026-11-24

- Layout sizes scale with screen density: every fixed pixel size in the
  screens and theme (heights, widths, padding, spacing, corner radii, icon
  sizes and stroke widths) is in `dp`, so on phones text fits its rows and
  buttons. Desktop (density 1) looks the same.
- `android/build.sh` removes old APKs before building, so `android/bin/`
  holds only the current one.

## [0.1.0] - 2026-11-24

- The screens talk to a `CalendarService` interface. The HTTP `BackendClient`
  is the desktop implementation; `InMemoryCalendarService` keeps events in
  memory with sample data and needs no backend. Desktop can use it with
  `KIVY_CALENDAR_SERVICE=memory`; without a backend token the error now says
  so.
- Android build (`android/`): `buildozer.spec`, `build.sh` and an entry point.
  A debug APK for x86_64 builds with python-for-android 2026.5.9 (Python
  3.14.2, Kivy 2.3.1, pydantic 2.12.3) and runs on the emulator with sample
  events; the shared calendar models import on the device.
- Known issue: on phones, layout sizes are not scaled by screen density, so
  text overflows its boxes (fix planned for 0.1.1).

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
