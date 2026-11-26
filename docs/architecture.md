# Architecture

Kivy Calendar ships as two builds from one repository. Both use the same
screens and calendar rules. Only the layer that talks to a calendar differs.

- **Android** (the product): the app reads and writes the phone's own calendar
  store (Android `CalendarContract`). Android's account sync carries changes to
  the account. There is no server, no sign-in and no internet permission.
- **Desktop / self-hosted**: the Kivy client talks to a FastAPI backend over
  HTTP. The backend holds the Google credentials and talks to Google Calendar.

The rules for each build are in `AGENTS.md`.

## Packages

| Path | Contents | Build |
| --- | --- | --- |
| `shared/src/core` | Error types and `Result`, settings from environment variables, SQLite helper | Both |
| `shared/src/domain` | Event and calendar models, curated time zones | Both |
| `shared/src/slots` | Free-slot search over a `CalendarProvider` | Both |
| `shared/src/calendar_provider.py` | The `CalendarProvider` protocol | Both |
| `client/src/kivy_calendar` | Kivy app, screens, theme, the `CalendarService` protocol, the backend client, the in-memory service, grid and filter logic | Both |
| `backend/src` | `api` (FastAPI routes, bearer token), `sync` (write-through service), `cache` (SQLite), `retry` (queue and worker), `google_calendar` (Google provider, OAuth helper, fake provider) | Desktop only |
| `android/src/phone_calendar` | `store` (calendar store), `provider` (`AndroidCalendarProvider`), `service` (`PhoneCalendarService`), `permissions`, `account_sync` | Android only |
| `android/` | `main.py` entry point, `build.sh`, `buildozer.spec`, icon and splash assets | Android only |
| `tests/`, `client/tests/`, `android/tests/` | Tests for `shared` and `backend`, the client, and `phone_calendar` (with a fake store) | Development |

`shared/` has no FastAPI, Google or Kivy imports. The backend is not part of
the APK.

## What goes into the APK

`android/build.sh` copies these into `android/app/` before Buildozer runs:

- `android/main.py`, as the entry point.
- `client/src/kivy_calendar`.
- `shared/src/core`, `shared/src/domain` and `shared/src/slots`, whole
  packages.
- `shared/src/calendar_provider.py`.
- `android/src/phone_calendar`.

`android/buildozer.spec` adds the Python packages the shared models need
(pydantic, pydantic-core, and tzdata, so `zoneinfo` has a time zone database).

Nothing from `backend/` is copied, so the APK has no FastAPI or Google code.

## Two interfaces

There are two interfaces. Keep them apart.

**`CalendarService`** (`client/src/kivy_calendar/service.py`) is what the
screens call. It has `list_events`, `list_calendars`, `list_time_zones`,
`create_event`, `update_event`, `delete_event`, `sync` and `find_free_slots`.
Implementations raise `ServiceError` for failures the user should see.

A second protocol, **`AccessGate`**, is for a service that needs permission
first. It has `has_access`, `request_access` and `open_settings`. The app
shows the permission screen while `has_access` is false.

**`CalendarProvider`** (`shared/src/calendar_provider.py`) is what the sync
service, the free-slot search and the Android service use. It has
`create_event`, `update_event`, `move_event`, `list_calendars`,
`delete_event`, `get_event` and `list_events`. Each call returns a `Result`
and does not raise across the module boundary. The event id is set by the
client before the call, so a retried create cannot make a duplicate.

`AndroidCalendarProvider` also has `accounts()` and `unsynced_event_ids()`.
The Android service uses them for the Sync button and the "Not synced yet"
tags. They are not part of the protocol.

### Implementations

| Class | Interface | Used by | Talks to |
| --- | --- | --- | --- |
| `BackendClient` (`client/src/kivy_calendar/api.py`) | `CalendarService` | Desktop (default) | The backend HTTP API, with a bearer token |
| `PhoneCalendarService` (`android/src/phone_calendar/service.py`) | `CalendarService`, `AccessGate` | Android | `AndroidCalendarProvider` |
| `AndroidCalendarProvider` (`android/src/phone_calendar/provider.py`) | `CalendarProvider` | Android | A `CalendarStore` |
| `JniCalendarStore` (`android/src/phone_calendar/store.py`) | `CalendarStore` | Android | Android's `ContentResolver`, through pyjnius |
| `InMemoryCalendarService` (`client/src/kivy_calendar/memory_service.py`) | `CalendarService` | Any build with `KIVY_CALENDAR_SERVICE=memory` | Nothing. Sample events, lost when the app closes |
| `GoogleCalendarProvider` (`backend/src/google_calendar/google_provider.py`) | `CalendarProvider` | Backend | Google Calendar API v3 |
| `FakeCalendarProvider` (`backend/src/google_calendar/fake.py`) | `CalendarProvider` | Backend tests and local development | Memory |
| `UnavailableCalendarProvider` (`backend/src/api/unavailable_provider.py`) | `CalendarProvider` | Backend when Google is not configured | Nothing. Returns errors |

`choose_service()` in `client/src/kivy_calendar/service.py` picks the service:

1. `KIVY_CALENDAR_SERVICE=memory` selects the in-memory service in any build.
2. On Android, `phone_calendar.create_service()` is used.
3. Otherwise `BackendClient` is used. With no `BACKEND_API_TOKEN` the app still
   starts and shows a configuration message.

## Data flow

**Android save.** The form calls `PhoneCalendarService.create_event`. The
provider inserts the row into the phone's calendar with the app's id in
`uid2445`. A repeated save with the same id updates that row, so no copy is
added. The app then shows "Saved on the phone. Android syncs it to your
account." Android uploads the change later.

**Desktop save.** The form calls `BackendClient`, which sends `POST /events`.
`SyncService` writes to Google first and then to the cache. If Google is
unreachable, the write goes to the SQLite retry queue and the response is
`202`. The cache is not changed until Google confirms.

## Screens

- `screens/main.py`: the main screen, with a List, Week and Month switch under
  the header, Refresh and Sync, and the New event button.
- `screens/week.py`: Monday to Sunday, with an all-day strip and a 24-hour grid
  that opens at 07:00.
- `screens/month.py`: a Monday-first month grid with event chips.
- `screens/add_event.py`: create and edit form.
- `screens/permission.py`: asks for calendar access on Android until it is
  granted.
- `screens/date_picker.py` and `screens/time_picker.py`: the date and time
  pickers used by the form.
- `event_list.py` (in `screens/`): the virtual list behind the List view.
- `grid_layout.py`, `filtering.py` and `formatting.py`: logic with no Kivy
  imports, so the tests can run without a display.

The screens only use `CalendarService`. Calendar rules (time zones, recurrence,
free-slot search) live in `shared/` or in a provider, not in the screens.

## Kivy findings

These come from the code and the CHANGELOG. Read the code before changing
them.

- **Sizes.** Use `dp()` for lengths and `sp()` for font sizes. Without them,
  text overflows on phones (CHANGELOG 0.1.1).
- **Back key.** Android's Back and desktop's Escape both arrive as key 27 on
  `Window.on_keyboard`. `BackKeyHandler` (`back_key.py`) returns `True`, so Kivy
  does not close the app. It closes a popup, then a dropdown, then the keyboard,
  then leaves the form. On the main screen it moves the app to the background.
- **Pausing.** `on_pause` returns `True`. Returning `False` makes Kivy finish
  the activity.
- **Resuming.** After the app was in the background, Android may have dropped
  the GL context, and the window can stay black. `on_resume` redraws now and
  again after `RESUME_REDRAW_DELAY` (0.3 s), and reloads the events
  (`app.py`).
- **Window size.** On desktop the window is forced to 420 by 760. On Android
  and iOS the device size is used (`apply_window_size`).
- **Keyboard height.** On Android `Window.keyboard_height` reads 0, so the form
  assumes 40 % of the window for the keyboard (`keyboard.py`).
- **Scrolling.** On slow frames, Kivy's `ScrollEffect` can fling the content to
  the opposite end. `SteadyScrollEffect` (`scroll_effect.py`) fixes this. Use
  its `halt()` to move content in code.
- **Long lists.** `VirtualList` (`event_list.py`) builds only the cards near the
  visible part, 500 dp above and below it. The rest are built as the list
  scrolls, so 1,000 events open quickly (CHANGELOG 0.5.2).
- **pyjnius calls are slow.** Each call to the phone is a round trip of about
  0.1 ms. `read_rows` (`store.py`) reads each cell with one `getString` call.
- **Java exceptions.** pyjnius raises `JavaException`. The provider turns it
  into a `Result`. A `SecurityException` becomes `PERMISSION_DENIED`
  (`provider.py`).
- **Launch screen.** The presplash is drawn with `FIT_CENTER` on the app
  background colour. On Android 12 and later, `res/values-v31/styles.xml`
  redefines `KivySupportCutout` so the system launch screen uses the same
  colour. Check that file when `p4a.branch` changes.
- **Time zones.** Android stores all-day events as UTC midnights in the `UTC`
  zone. Timed events keep their start and end zones.

## Known gaps

- The phone's calendar window is a year back to a year ahead. Week and month
  views only have events in that window.
- Repeating events are read-only on Android. Series editing is out of scope
  before 1.0.0 (`ROADMAP.md`).
- Google refresh tokens expire weekly while the Google Cloud app is in Testing
  (`ROADMAP.md`).

## Tests and checks

Run from the repository root:

```sh
python -m pip install ./shared ./backend pytest httpx mypy ruff
pytest
ruff check .
mypy shared/src backend/src tests
(cd client && mypy src)
(cd android && mypy src)
```

The client and Android tests need a display. See `README.md` for the Xvfb
command. Android tests use a fake calendar store and never touch a real
calendar.
