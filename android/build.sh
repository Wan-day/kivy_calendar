#!/usr/bin/env bash
# Build the Kivy Calendar APK with Buildozer.
#
# Copies the app code into android/app/ (generated, git-ignored), then runs
# Buildozer from android/. Extra arguments go to Buildozer; the default is a
# debug build:
#
#   android/build.sh                 # buildozer android debug
#   android/build.sh android clean   # any other buildozer command
#
# BUILDOZER defaults to the tool environment set up for this project; point it
# at another buildozer executable if yours lives elsewhere.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(dirname "$here")"
app="$here/app"
buildozer="${BUILDOZER:-$HOME/.local/share/kivy-calendar-buildozer/bin/buildozer}"

rm -rf "$app"
mkdir -p "$app"
cp "$here/main.py" "$app/main.py"
cp -r "$root/client/src/kivy_calendar" "$app/kivy_calendar"
for package in core domain slots; do
    cp -r "$root/shared/src/$package" "$app/$package"
done
cp "$root/shared/src/calendar_provider.py" "$app/calendar_provider.py"
find "$app" -name __pycache__ -type d -prune -exec rm -rf {} +

# Buildozer's own tools (Cython, its python-for-android) must be on PATH, and
# VIRTUAL_ENV tells Buildozer to install its helpers into that environment
# instead of with pip --user.
export VIRTUAL_ENV="$(dirname "$(dirname "$buildozer")")"
export PATH="$(dirname "$buildozer"):$PATH"
# android/tools/pkg-config hides this PC's packages from Android compiles;
# without it Kivy finds the desktop SDL2 headers and the build fails.
export PATH="$here/tools:$PATH"
# Android builds use JDK 17.
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}"

cd "$here"
if [ "$#" -eq 0 ]; then
    set -- android debug
fi
exec "$buildozer" "$@"
