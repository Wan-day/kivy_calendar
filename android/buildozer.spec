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

# Same release that was checked for the Python, Kivy and pydantic versions.
p4a.branch = v2026.05.09

[buildozer]

log_level = 2
warn_on_root = 1
