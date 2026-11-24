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
| 0.6.0 | Phone polish | Android |
| 0.7.0 | Release pipeline and docs | Both |
| 0.9.0 | Release candidate | Android |
| 1.0.0 | Android build usable with the starting feature set | Android |

## 0.0.x: fixes and small improvements

Patch releases can ship between any of the versions below. Known candidates:

- Show the app version in the app (for example under the title).
- A create queued while offline on an empty list still shows "No events yet".
- `create_event` with a `recurring_event_id` inserts a new event instead of
  editing the occurrence.
- Event validation edge case when the default start falls in a skipped
  daylight-saving hour.
- Fix the 25 existing client mypy errors and add client type-checking to CI.

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

## 0.2.0: Android, read side

- Calendar permission request with an explanation, and a screen for when it is
  refused.
- `AndroidCalendarProvider` reads `Calendars` and `Instances`; recurring
  events show as their individual occurrences.
- Event list, filters and the calendar dropdown work on a device.
- A fake calendar store so the Android provider is tested on desktop.

Done when: an emulator with a test Google account shows its events in the app.

## 0.3.0: Android, write side

- Create, edit, delete and move events between calendars.
- All-day events and per-event time zones stored the way Android expects.
- Duplicate protection through `UID_2445`.
- Recurring occurrences open read-only (series editing is out of scope).

Done when: changes made in the app appear in Google Calendar on the web after
Android syncs.

## 0.4.0: Android, Sync and free time

- **Sync** asks Android to sync the calendar accounts now, then reloads.
- "Suggest a free time" runs on the phone's own data.
- Status messages say "Saved on phone" until Android has synced.

Done when: every feature of the desktop app works on Android.

## 0.5.0: week and month grid views

- A week view and a month view that show events in a grid, like Google
  Calendar, next to the existing day-grouped list.
- Switching between list, week and month; tapping an event opens it; tapping
  an empty slot starts a new event there.
- Built on the shared theme and the month logic already in the date picker.

Done when: both views work on desktop and Android.

## 0.6.0: phone polish

- Real phone layouts: no fixed window size, on-screen keyboard never covers
  the focused field, the back button closes dialogs and screens.
- App icon, name and splash screen.
- Performance check: a filled list in under 3 s with about 1,000 events.

Done when: the app feels like a phone app on a real device, not a resized
desktop window.

## 0.7.0: release pipeline and docs

- CI builds a signed APK (keystore kept out of git) and attaches it to a
  GitHub release for each tag.
- `docs/architecture.md` and `docs/releasing.md`, which `AGENTS.md` already
  points to.
- README section for installing the APK.

Done when: tagging a version produces a downloadable APK.

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
  move events; all-day events and time zones; calendar choice; free-time
  suggestions; Sync.

## Not planned before 1.0.0

- Editing whole recurring series.
- Google Play publishing, iOS, widgets, notifications and reminders.
- Desktop only: the Google reconnect pop-up from the "Google re-authorization
  on Sync" analysis. It would help the self-hosted build, whose Google tokens
  expire weekly while the Google Cloud app is in Testing, and can be scheduled
  as a 0.x feature whenever it is wanted.
