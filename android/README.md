# Android build

The standalone Android version of Kivy Calendar. It is meant to read and write
the phone's own calendar store (Android `CalendarContract`), with Android's
account sync carrying changes to Google Calendar: no server, no Google sign-in
and no credentials in the app.

**Status (0.3.0):** the app asks for calendar access, lists the events of
every visible calendar on the phone (30 days back to 180 days ahead), and
creates, edits, moves and deletes single events. Occurrences of repeating
events are read-only. Free times come from the phone's events. See
`ROADMAP.md`.

Decided: minimum Android 8.0 (API 26), sideloaded APK only (no Google Play),
editing whole recurring series is out of scope for the first release.

## Files

| File | Purpose |
| --- | --- |
| `buildozer.spec` | APK settings: package `io.github.wanday.kivycalendar`, API 34, min API 26, x86_64 (emulator) for now, `READ_CALENDAR` and `WRITE_CALENDAR` only. The version is read from `kivy_calendar.__version__`. |
| `build.sh` | Copies `client/src/kivy_calendar`, the shared packages from `shared/src` and `src/phone_calendar` into `app/` (generated, git-ignored), then runs Buildozer. Removes old APKs first. |
| `main.py` | Entry point: imports the shared code once (logged as `[KivyCalendar] shared code imported`), then starts the app. |
| `src/phone_calendar/` | The phone's calendar as the app's service: `store.py` (reads `Calendars`/`Instances` and writes `Events` rows through pyjnius), `provider.py` (`AndroidCalendarProvider`, the shared `CalendarProvider`), `service.py` (`PhoneCalendarService`, the screens' `CalendarService` plus the access gate), `permissions.py`. |
| `tests/` | Desktop tests for `phone_calendar` with a fake calendar store (`fakes.py`); part of the normal `pytest` run. |
| `pyproject.toml` | ruff and mypy settings for `src/` (not a package). |
| `tools/pkg-config` | Hides this PC's pkg-config packages from Android compiles; without it Kivy picks up the desktop SDL2 headers and the build fails. |

On a device the app uses `PhoneCalendarService`; `KIVY_CALENDAR_SERVICE=memory`
switches any build to in-memory sample events.

## One-time setup (Ubuntu)

1. System packages:
   ```sh
   sudo apt install -y git zip unzip openjdk-17-jdk autoconf automake libtool \
       libncurses-dev libffi-dev libssl-dev zlib1g-dev cmake pkg-config ccache
   ```
2. A Rust toolchain (`rustup`), needed for the pydantic-core recipe.
3. Buildozer in its own environment, outside the project's dependencies.
   `build.sh` expects it here (override with `BUILDOZER=/path/to/buildozer`):
   ```sh
   uv venv --python 3.14 ~/.local/share/kivy-calendar-buildozer
   uv pip install --python ~/.local/share/kivy-calendar-buildozer/bin/python \
       buildozer cython setuptools pip
   ```
4. For the emulator: the Android SDK command-line tools, then
   ```sh
   sdkmanager "platform-tools" "emulator" "system-images;android-34;google_apis;x86_64"
   avdmanager create avd -n pixel34 -k "system-images;android-34;google_apis;x86_64" -d pixel_6
   emulator -avd pixel34 -memory 2048 -no-snapshot-save -no-boot-anim -no-metrics
   ```

Buildozer downloads its own SDK, NDK and python-for-android
(`p4a.branch = v2026.05.09`: Python 3.14.2, Kivy 2.3.1, pydantic-core 2.41.4)
into `~/.buildozer` and `android/.buildozer/`.

## Build, install, run

```sh
android/build.sh                       # debug APK -> android/bin/ (old APKs are removed)
adb install -r android/bin/kivycalendar-*-x86_64-debug.apk
adb shell monkey -p io.github.wanday.kivycalendar -c android.intent.category.LAUNCHER 1
adb logcat -s python                   # the app's Python and Kivy log
```

Type-check the Android code with `(cd android && mypy src)`.

## A test calendar on the emulator

The emulator has no calendars until an account is added. Never use a personal
account for testing; create a local calendar and a few events instead (they
never sync anywhere):

```sh
adb shell content insert --uri "'content://com.android.calendar/calendars?caller_is_syncadapter=true&account_name=kivy-test&account_type=LOCAL'" \
  --bind account_name:s:kivy-test --bind account_type:s:LOCAL --bind name:s:kivy-test \
  --bind "calendar_displayName:s:'Test calendar'" --bind calendar_access_level:i:700 \
  --bind ownerAccount:s:kivy-test --bind visible:i:1 --bind sync_events:i:1 \
  --bind calendar_timezone:s:Europe/Berlin --bind isPrimary:i:1
# an event (times in epoch milliseconds; date +%s%3N gives "now")
adb shell content insert --uri content://com.android.calendar/events \
  --bind calendar_id:i:1 --bind "title:s:'Team standup'" \
  --bind dtstart:l:$(( $(date +%s) * 1000 + 3600000 )) \
  --bind dtend:l:$(( $(date +%s) * 1000 + 5400000 )) --bind eventTimezone:s:Europe/Berlin
```

To see the permission screen again: `adb shell pm revoke
io.github.wanday.kivycalendar android.permission.READ_CALENDAR`.

The first build takes about an hour on a small machine; later builds reuse the
cache and take minutes. `android/build.sh android clean` starts over.

To install on a phone, add `arm64-v8a` to `android.archs` in `buildozer.spec`
(`arm64-v8a, x86_64`); it roughly doubles build time and APK size.

## Writing to the phone's calendar

- New events get the app's own id in `uid2445`; saving the same new event
  again updates it instead of adding a copy.
- All-day events are stored as UTC midnights in the `UTC` zone, as Android
  requires; timed events keep their start and end zones.
- Changing an event's calendar copies it into the new calendar and deletes the
  original (Android ties an event to its account). If the delete fails, the
  copy is removed again.
- Repeating events can only be read; the form opens their occurrences
  read-only.

## Known issues

- The Back button (and Escape) closes the app instead of going back a screen,
  and after the app has been in the background the screen can stay black
  until it is restarted. Both are part of the phone polish in 0.6.0.
- The APK also ships `setuptools`, which the app does not need.
- Layout sizes are in `dp` (fonts in `sp`) so they scale with screen
  density; use `dp()` for any new pixel size in the screens.
- On a slow software-rendered emulator, Android may show "System UI isn't
  responding" while the app starts; choose Wait.
