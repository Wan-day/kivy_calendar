# Android build

The standalone Android version of Kivy Calendar. It is meant to read and write
the phone's own calendar store (Android `CalendarContract`), with Android's
account sync carrying changes to Google Calendar: no server, no Google sign-in
and no credentials in the app.

**Status (0.1.0):** the APK builds and runs on the emulator with in-memory
sample events (`InMemoryCalendarService`); nothing is saved yet. The phone
calendar arrives in 0.2.0 (see `ROADMAP.md`).

Decided: minimum Android 8.0 (API 26), sideloaded APK only (no Google Play),
editing whole recurring series is out of scope for the first release.

## Files

| File | Purpose |
| --- | --- |
| `buildozer.spec` | APK settings: package `io.github.wanday.kivycalendar`, API 34, min API 26, x86_64 (emulator) for now, no permissions yet. The version is read from `kivy_calendar.__version__`. |
| `build.sh` | Copies `client/src/kivy_calendar` and the shared packages from `shared/src` into `app/` (generated, git-ignored), then runs Buildozer. |
| `main.py` | Entry point: imports the shared code once (logged as `[KivyCalendar] shared code imported`), then starts the app. |
| `tools/pkg-config` | Hides this PC's pkg-config packages from Android compiles; without it Kivy picks up the desktop SDL2 headers and the build fails. |

Planned: `AndroidCalendarProvider` (implements `calendar_provider.CalendarProvider`
through pyjnius) and a `LocalCalendarService` for the screens.

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
android/build.sh                       # debug APK -> android/bin/*.apk
adb install -r android/bin/kivycalendar-*-x86_64-debug.apk
adb shell monkey -p io.github.wanday.kivycalendar -c android.intent.category.LAUNCHER 1
adb logcat -s python                   # the app's Python and Kivy log
```

The first build takes about an hour on a small machine; later builds reuse the
cache and take minutes. `android/build.sh android clean` starts over.

To install on a phone, add `arm64-v8a` to `android.archs` in `buildozer.spec`
(`arm64-v8a, x86_64`); it roughly doubles build time and APK size.

## Known issues

- Fixed pixel sizes are not scaled by screen density, so on a phone the text
  is too large for its boxes (fonts use `sp`, layout sizes plain pixels).
  Fix planned for 0.1.1: wrap layout sizes in Kivy's `dp()`.
- The APK also ships `setuptools`, which the app does not need.
- On a slow software-rendered emulator, Android may show "System UI isn't
  responding" while the app starts; choose Wait.
