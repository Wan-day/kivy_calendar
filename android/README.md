# Android build (planned)

This folder will hold the standalone Android version of Kivy Calendar. It reads
and writes the phone's own calendar store (Android `CalendarContract`) instead
of talking to the backend, and Android's account sync carries the changes to
Google Calendar. There is no server, Google sign-in or credentials in this
build.

Planned contents:

- `AndroidCalendarProvider`: implements `calendar_provider.CalendarProvider`
  from `shared/src` through pyjnius.
- `LocalCalendarService`: the in-process service the Kivy screens use instead
  of the HTTP `BackendClient`.
- `buildozer.spec`: APK build settings (minimum Android 8.0 / API 26,
  `READ_CALENDAR` and `WRITE_CALENDAR` permissions only).

The release is a sideloaded APK; Google Play is not a target for now. Editing
whole recurring series is out of scope for the first release.
