[app]

title = Kivy Calendar
package.name = kivycalendar
package.domain = io.github.wanday

# android/build.sh copies the app code here before every build.
source.dir = app
source.include_exts = py,ttf,txt

# The version comes from the client, which a test keeps equal to VERSION.
version.regex = __version__ = ['"](.*)['"]
version.filename = %(source.dir)s/kivy_calendar/__init__.py

# python3 and kivy versions come from the pinned python-for-android release
# (Python 3.14.2, Kivy 2.3.1). pydantic 2.12.3 is the release that matches its
# pydantic-core 2.41.4 recipe; tzdata gives zoneinfo the time zone database,
# which Python cannot read from Android itself.
requirements = python3,kivy,pydantic==2.12.3,pydantic-core,annotated-types,typing-extensions,typing-inspection,tzdata

orientation = portrait
fullscreen = 0

# Icon and splash screen, rendered from the SVGs in assets/ (see README.md).
# Buildozer reads these paths relative to android/, so they are not copied
# into app/. Android 8+ uses the adaptive icon (white background, blocks in
# the safe zone); icon.png is the plain fallback.
icon.filename = assets/icon.png
icon.adaptive_foreground.filename = assets/icon_foreground.png
icon.adaptive_background.filename = assets/icon_background.png
# The presplash is transparent and drawn centred (FIT_CENTER) on
# presplash_color, the app's background.
presplash.filename = assets/presplash.png
android.presplash_color = #F4F9FD
# res/values-v31/styles.xml gives the Android 12+ launch screen the same
# background colour.
android.add_resources = res

# Calendar access and no internet. WRITE_CALENDAR is requested together with
# READ_CALENDAR so saving (0.3.0) does not ask the user a second time.
# READ_SYNC_STATS lets Sync wait until Android reports the account sync
# finished; it is a normal permission, granted at install with no prompt.
android.permissions = READ_CALENDAR, WRITE_CALENDAR, READ_SYNC_STATS

android.api = 34
android.minapi = 26
# arm64-v8a runs on phones. For the emulator build x86_64 instead with
# APP_ANDROID_ARCHS=x86_64 (Buildozer's override of this value). Don't list
# both: python-for-android 2026.05.09 breaks its pip when it installs the
# Python packages for a second arch in the same build.
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = False
# Sideloaded, not Google Play: a release build makes a signed .apk, which is
# what you install by hand. Buildozer's default for release is an .aab.
android.release_artifact = apk

# Same release that was checked for the Python, Kivy and pydantic versions.
p4a.branch = v2026.05.09

[buildozer]

log_level = 2
warn_on_root = 1
