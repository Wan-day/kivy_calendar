# Roadmap to 1.0.0

**1.0.0** is the first release that is usable day to day on an Android phone:
the standalone Android build with the starting feature set, mostly complete
but still in need of polish. The current version is in `VERSION`; what each
released version contained is in `CHANGELOG.md`.

Version rules (full text in `AGENTS.md`, Versioning):

- **0.0.x**: small changes that don't change the app as a whole, such as a
  button or a bug fix.
- **0.x.0**: a new feature, such as a new calendar view.
- **x.0.0**: something big changes, such as a whole new provider or a public
  release.

The Android provider is a "big change", but it only becomes usable once its
pieces are all in place. Its parts therefore land as 0.x features, and the
major bump to 1.0.0 marks the moment the Android build is usable.

## Overview

| Version | Theme | Builds affected |
| --- | --- | --- |
| 0.0.1 | Current: self-hosted desktop app, shared layout | Desktop |
| 0.0.x | Fixes and small improvements, any time | Desktop, later both |
| 0.1.0 | Calendar service interface and Android build spike | Both |
| 0.2.0 | Android: read the phone's calendars and events | Android |
| 0.3.0 | Android: create, edit, delete and move events | Android |
| 0.4.0 | Android: Sync and free-time suggestions | Android |
| 0.5.0 | Week and month grid views | Both |
| 0.5.1 | Icon, splash and phone layouts | Android |
| 0.5.2 | Performance with 1,000 events | Both |
| 0.6.0 | Release pipeline and docs | Both |
| 0.6.1 | Phone polish leftovers | Android |
| 0.7.0 | Repeating events on Android | Android |
| 0.9.0 | Release candidate | Android |
| 1.0.0 | Android build usable with the starting feature set | Android |

## 0.0.x: fixes and small improvements

Patch releases can ship between any of the versions below. Known candidates:

- ~~Show the app version in the app~~ (done in 0.0.2).
- ~~0.1.1: scale layout sizes with screen density (`dp()`), so text fits its
  boxes on phones~~ (done in 0.1.1).
- Drop `setuptools` from the APK (python-for-android adds it).
- ~~A create queued while offline on an empty list still shows "No events yet"~~ (done in 0.0.3).
- ~~`create_event` with a `recurring_event_id` inserts a new event instead of
  editing the occurrence~~ (done in 0.0.3: rejected; occurrences are updated).
- ~~Event validation edge case when the default start falls in a skipped
  daylight-saving hour~~ (done in 0.0.3).
- ~~Fix the existing client mypy errors and add client type-checking to CI~~
  (done in 0.0.3; client tests are not type-checked yet).

## 0.1.0: calendar service interface and Android build spike

- The Kivy screens talk to a calendar service interface instead of
  `BackendClient` directly; `BackendClient` becomes the desktop
  implementation.
- `android/buildozer.spec`: the app builds as an APK and opens on an emulator
  with an in-memory service.
- Answer the packaging risks: does python-for-android support the project's
  Python version and `pydantic-core`? If not, pick a supported Python and move
  the domain models from pydantic to dataclasses here.

Done when: the desktop build works unchanged and an APK installs and opens on
an emulator.

**Shipped in 0.1.0:** `CalendarService` interface with `BackendClient` and an
`InMemoryCalendarService` (also on desktop with `KIVY_CALENDAR_SERVICE=memory`);
`android/` build with Buildozer. python-for-android 2026.5.9 builds Python
3.14.2 and has a pydantic-core recipe, so no Python downgrade or dataclass move
is needed: the shared models import on the emulator (pinned pydantic 2.12.3).
Found on the emulator: layout sizes are not density-scaled (0.1.1).

## 0.2.0: Android, read side

- Calendar permission request with an explanation, and a screen for when it is
  refused.
- `AndroidCalendarProvider` reads `Calendars` and `Instances`; recurring
  events show as their individual occurrences.
- Event list, filters and the calendar dropdown work on a device.
- A fake calendar store so the Android provider is tested on desktop.

Done when: an emulator with a test Google account shows its events in the app.

**Shipped in 0.2.0:** permission screen (Allow access, Open app settings after
a refusal); `AndroidCalendarProvider` over `Calendars`/`Instances` with a fake
store for desktop tests; the list, filters and calendar dropdown on the
emulator, checked with a local test calendar (no Google account; see
`android/README.md`). Also already working: free-time suggestions from the
phone's events (planned for 0.4.0) and new events defaulting to the phone's
time zone. Saving shows "not available yet" until 0.3.0.

## 0.3.0: Android, write side

- Create, edit, delete and move events between calendars.
- All-day events and per-event time zones stored the way Android expects.
- Duplicate protection through `UID_2445`.
- Recurring occurrences open read-only (series editing is out of scope).

Done when: changes made in the app appear in Google Calendar on the web after
Android syncs.

**Shipped in 0.3.0:** create, edit, move and delete single events in the
phone's calendar, with duplicate protection through `uid2445`, all-day events
as UTC midnights and per-end time zones; repeating occurrences open read-only.
Checked on the emulator with local test calendars; checking the Google
Calendar website needs a test Google account on the device.

## 0.4.0: Android, Sync and free time

- **Sync** asks Android to sync the calendar accounts now, then reloads.
- "Suggest a free time" runs on the phone's own data.
- Status messages say "Saved on phone" until Android has synced.

Done when: every feature of the desktop app works on Android.

**Shipped in 0.4.0:** Sync requests a manual, expedited sync for each phone
account with calendars (LOCAL calendars skipped), waits until Android reports
it finished or 30 s pass, then reloads. After a save or delete the message says
Android syncs it, and event cards with an unsynced change (`Events.dirty`,
non-LOCAL calendars) show "Not synced yet". Free time from the phone's events
already shipped in 0.2.0. The emulator check uses calendars without a real sync
service, so uploading to Google itself still needs a test Google account on a
device.

## 0.5.0: week and month grid views

- A week view and a month view that show events in a grid, like Google
  Calendar, next to the existing day-grouped list.
- Switching between list, week and month; tapping an event opens it; tapping
  an empty slot starts a new event there.
- Built on the shared theme and the month logic already in the date picker.

Done when: both views work on desktop and Android.

**Shipped in 0.5.0:** a List | Week | Month switcher (List is the default) that
slides between views, with the same header in each; the From/To chips and sort
live in the list. The week view runs Monday to Sunday with an all-day strip, a
24-hour grid opening at 07:00 that follows the finger without coasting, and
side-by-side blocks for overlaps and a current-time line. The month view is a
Monday-first grid with event chips and "+N", which opens that week. Tapping an
event opens it; tapping an empty week slot (rounded down to 30 minutes) or a
month day (09:00) starts a new event there. Both grids use the device's local
time zone, apply the name filter and show no count; on Android they only have
the loaded window (30 days back to 180 ahead; a year each way since 0.6.1).
The phone APK is arm64-v8a (`APP_ANDROID_ARCHS=x86_64` for the emulator).
Checked on a real phone (Nothing Phone (3a), Android 15) and on the emulator.

## 0.5.1: icon, splash and phone layouts

Pulled forward from 0.6.0.

**Shipped in 0.5.1:** the app icon (week blocks and a coral "now" line, with an
adaptive icon for Android 8+) and a splash screen on the app's light
background, also used for Android 12+'s own launch screen. The Back button
closes dialogs, dropdowns, the keyboard and the event form before it moves
the app to the background. The focused form field stays above the keyboard,
and returning to the app redraws it and reloads the events.

## 0.5.2: performance with 1,000 events

The performance check from 0.6.0.

**Shipped in 0.5.2:** the list builds only the cards near the screen, so 1,000
events fill it in about 0.1 s on desktop (3 to 7 s before), and the phone read
makes one call per cell instead of two (about 2.5 s down to 1.7 s for 1,009
events on the software-emulated emulator). On a real phone (Nothing Phone (3a),
51 events) a cold start reaches a drawn list in 2.5 to 2.9 s, about 2 s of it
Python and Kivy starting. The 1,000-event read was only measured on the
emulator, because test data is not added to a real calendar. Not done yet:
overlapping the first calendar query (0.1 to 0.8 s) with Kivy's start.

## 0.6.0: release pipeline and docs

Planned as 0.7.0; moved up because most of the phone polish shipped in 0.5.1
and 0.5.2.

- CI builds a signed APK (keystore kept out of git) and attaches it to a
  GitHub release for each tag.
- `docs/architecture.md` and `docs/releasing.md`, which `AGENTS.md` already
  points to.
- README section for installing the APK.

Done when: tagging a version produces a downloadable APK.

**Shipped in 0.6.0:** release builds are APKs signed with the release key
(checked locally with a throwaway key: v2 signature, matching fingerprint).
`.github/workflows/release.yml` builds, signs and verifies the arm64-v8a APK on
a `vX.Y.Z` tag that matches `VERSION` and publishes it with the CHANGELOG
notes; run by hand it is a dry run. The first real run happens after merging,
because GitHub only runs workflows from `main`.

## 0.6.1: phone polish leftovers

- New events show the zone name (e.g. "Europe/Prague") while existing events
  show the city (e.g. "Berlin").
- The list's scrollbar overlaps the cards.
- The "Synced N events" message is replaced as soon as the list reloads.
- Outdated docstrings from before the phone service (`memory_service.py`,
  `android/main.py`, `screens/add_event.py`).

Done when: the app feels like a phone app on a real device, not a resized
desktop window.

**Shipped in 0.6.1 so far:** the phone's calendar window is a year back to a
year ahead (was 30 days back to 180 ahead), so the grids reach older events.

## 0.7.0: repeating events on Android

Planned as "not before 1.0.0"; moved in at the user's request.

- New events can repeat: everyday rules (daily, weekly on the start's
  weekday, monthly on its day or nth weekday, yearly) and custom rules (every
  N days, weeks, months or years; chosen weekdays; ending on a date or after
  N times).
- Saving or deleting an occurrence asks which occurrences it applies to:
  this event, this and following events, or all events.
- Rules set in other apps that the form cannot show are kept unchanged.

Done when: a series can be created, changed and deleted with each choice on a
real phone, and the changes sync to Google.

**Shipped in 0.7.0:** `shared/src/domain/recurrence.py` models the rules; the
Android provider writes series, exceptions and splits, and the form has a
Repeat row and the "which occurrences?" question. Checked against Android 16
on a phone (a local test calendar): exceptions to a series that has not synced
hide the whole series, so those get an `exdate`; updates to a series must send
all of its expansion columns. The desktop backend still changes one
occurrence at a time.

**0.7.1** fixes what the first test on a phone found: the grey screen after
the keyboard closes (Android's default focus highlight on SDL's surface), the
keyboard covering the custom repeat dialog's buttons, off-center numbers in
that dialog, and long rules cut off in the Repeat row.

## 0.9.0: release candidate

- Feature freeze: only fixes from here to 1.0.0.
- Daily use on a real phone for at least a week; everything found becomes a
  0.9.x fix.

Done when: no known bug blocks everyday use.

## 1.0.0: usable on Android

- Signed APK published as a GitHub release, sideloaded (no Google Play).
- Minimum Android 8.0 (API 26); only `READ_CALENDAR` and `WRITE_CALENDAR`
  permissions.
- Starting feature set: list, week and month views; create, edit, delete and
  move events; repeating events; all-day events and time zones; calendar
  choice; free-time suggestions; Sync.

## Not planned before 1.0.0

- Google Play publishing, iOS, widgets, notifications and reminders.
- Desktop only: the Google reconnect pop-up from the "Google re-authorization
  on Sync" analysis. It would help the self-hosted build, whose Google tokens
  expire weekly while the Google Cloud app is in Testing, and can be scheduled
  as a 0.x feature whenever it is wanted.
