# Android build

The standalone Android version of Kivy Calendar. It is meant to read and write
the phone's own calendar store (Android `CalendarContract`), with Android's
account sync carrying changes to Google Calendar: no server, no Google sign-in
and no credentials in the app.

**Status (0.6.1):** the app asks for calendar access, lists the events of
every visible calendar on the phone (a year back to a year ahead), and
creates, edits, moves and deletes single events. Occurrences of repeating
events are read-only. Free times come from the phone's events. Sync asks
Android to sync the phone's accounts, and unsynced changes are marked. A
List | Week | Month switcher adds week and month grid views. The build is
checked on a real phone (arm64) and on the emulator (x86_64). See `ROADMAP.md`.

Decided: minimum Android 8.0 (API 26), sideloaded APK only (no Google Play),
editing whole recurring series is out of scope for the first release.

## Files

| File | Purpose |
| --- | --- |
| `buildozer.spec` | APK settings: package `io.github.wanday.kivycalendar`, API 34, min API 26, arm64-v8a (phones; x86_64 for the emulator, see below), `READ_CALENDAR`, `WRITE_CALENDAR` and `READ_SYNC_STATS` (granted at install, no prompt; no internet permission). The version is read from `kivy_calendar.__version__`. |
| `build.sh` | Copies `client/src/kivy_calendar`, the shared packages from `shared/src` and `src/phone_calendar` into `app/` (generated, git-ignored), then runs Buildozer. Removes old APKs first. |
| `main.py` | Entry point: imports the shared code once (logged as `[KivyCalendar] shared code imported`), then starts the app. |
| `src/phone_calendar/` | The phone's calendar as the app's service: `store.py` (reads `Calendars`/`Instances` and writes `Events` rows through pyjnius), `provider.py` (`AndroidCalendarProvider`, the shared `CalendarProvider`), `service.py` (`PhoneCalendarService`, the screens' `CalendarService` plus the access gate), `permissions.py`, `account_sync.py` (the Sync button: asks Android to sync each account). |
| `tests/` | Desktop tests for `phone_calendar` with a fake calendar store (`fakes.py`); part of the normal `pytest` run. |
| `pyproject.toml` | ruff and mypy settings for `src/` (not a package). |
| `tools/pkg-config` | Hides this PC's pkg-config packages from Android compiles; without it Kivy picks up the desktop SDL2 headers and the build fails. |
| `assets/` | App icon and splash screen: SVG sources and the PNGs rendered from them (see below). |
| `res/values-v31/styles.xml` | Added to the APK's resources (`android.add_resources = res`): gives the Android 12+ launch screen the app's background colour. |

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
android/build.sh                       # phone (arm64) debug APK -> android/bin/ (old APKs are removed)
APP_ANDROID_ARCHS=x86_64 android/build.sh   # the same for the emulator
adb install -r android/bin/kivycalendar-*-debug.apk
adb shell monkey -p io.github.wanday.kivycalendar -c android.intent.category.LAUNCHER 1
adb logcat -s python                   # the app's Python and Kivy log
```

Type-check the Android code with `(cd android && mypy src)`.

## Icon and splash screen

The SVGs in `assets/` are the sources; the PNGs next to them are what
`buildozer.spec` uses. Buildozer reads these paths relative to `android/`, so
`build.sh` does not copy them.

| File | What it is |
| --- | --- |
| `icon.svg` / `icon.png` | The full icon: three week columns of event blocks and a coral "now" line on a white rounded tile. 512×512 (`icon.filename`); Android 8+ only uses it where the adaptive icon is not supported. |
| `icon_foreground.svg` / `.png` | Adaptive icon foreground: the blocks and line without the tile, on transparent, scaled to 0.75 about the centre so they stay inside the 66/108 safe zone. 432×432 (`icon.adaptive_foreground.filename`). |
| `icon_background.svg` / `.png` | Adaptive icon background: plain white. 432×432 (`icon.adaptive_background.filename`). |
| `presplash.svg` / `.png` | Kivy's presplash: the icon (with a `#DCE9F3` border) at 128 dp and "Kivy Calendar" in Inter SemiBold 28 dp below it, on transparent. 1080×1080 (`presplash.filename`). |

The launcher masks the adaptive icon to its own shape (circle, squircle,
rounded square); the white background fills the shape and the blocks sit in
the middle. python-for-android shows the presplash with `FIT_CENTER` on
`android.presplash_color` (`#F4F9FD`), so the square image is scaled to the
screen width: on a 1080 px wide phone (about 420 dpi) it is drawn 1:1, the
icon at 128 dp. The wordmark in `presplash.svg` is already a path, so
rendering does not need Inter installed; the original `<text>` element is in
a comment in the file.

Android 12+ first shows its own launch screen (the adaptive icon in a circle)
before the presplash. `res/values-v31/styles.xml` sets its background to
`#F4F9FD` by redefining `KivySupportCutout`, the activity theme that
python-for-android 2026.05.09 generates; check that file when changing
`p4a.branch` or `android.display_cutout`.

To regenerate the PNGs after changing an SVG (Inkscape 1.4):

```sh
cd android/assets
inkscape icon.svg -w 512 -h 512 -o icon.png
inkscape icon_foreground.svg -w 432 -h 432 -o icon_foreground.png
inkscape icon_background.svg -w 432 -h 432 -o icon_background.png
inkscape presplash.svg -w 1080 -h 1080 -o presplash.png
```

To change the wordmark, put a `<text>` element back in `presplash.svg` and
convert it to a path again with the app's Inter fonts available, e.g. with a
fontconfig file that adds `client/src/kivy_calendar/fonts` as a `<dir>`:

```sh
FONTCONFIG_FILE=/path/to/fonts.conf inkscape presplash-text.svg \
    --export-text-to-path --export-plain-svg --export-filename=presplash.svg
```

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

The default build is for phones (`arm64-v8a`); `APP_ANDROID_ARCHS=x86_64`
builds for the emulator. Each arch has its own build folder, so switching
between them does not rebuild the other. One APK with both archs is not
possible yet: python-for-android 2026.05.09 breaks its pip when it installs
the Python packages for the second arch. To install on a phone, turn on USB debugging in its
Developer options, connect it by USB, accept the prompt, and check that
`adb devices` lists it as `device`.

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

## Syncing

- The Sync button asks Android to sync each phone account that has
  calendars (manual and expedited), waits until Android reports it is done or
  30 seconds pass, then reloads the list. Waiting needs `READ_SYNC_STATS`
  (a normal permission, granted at install with no prompt). A failure to
  start the sync shows as a one-line error; a failure to check progress only
  stops the wait.
- Calendars with account type `LOCAL` never sync, so they are skipped.
- "Not synced yet" on an event card means the change is saved on the phone
  but has not reached the account yet (`Events.dirty`). Android uploads it on
  its own sync; Sync does it now.
- The emulator test calendars have no real sync service, so checking the
  upload to Google needs a test Google account on a device.

## Known issues

- The APK also ships `setuptools`, which the app does not need.
- Layout sizes are in `dp` (fonts in `sp`) so they scale with screen
  density; use `dp()` for any new pixel size in the screens.
- On a slow software-rendered emulator, Android may show "System UI isn't
  responding" while the app starts; choose Wait.
