# Releasing

Two things are released:

- **The Android APK.** It is signed with the release key, built for
  arm64-v8a, and attached to a GitHub release for each tag `vX.Y.Z`.
- **The backend.** It is deployed by hand with Docker Compose on a machine you
  control. There is no release artifact for it.

Version rules are in `AGENTS.md` (Versioning). Plans are in `ROADMAP.md`.

## 1. Prepare the release PR

1. Bump the version in all five places. They must be equal, and
   `tests/test_version.py` checks them:
   - `VERSION`
   - `shared/pyproject.toml`
   - `backend/pyproject.toml`
   - `client/pyproject.toml`
   - `__version__` in `client/src/kivy_calendar/__init__.py`
2. Add a `CHANGELOG.md` entry under the new version. The GitHub release notes
   are taken from this section.
3. Update `ROADMAP.md` to say what shipped.
4. Open a PR into `main`. Run the checks in `docs/architecture.md`.
5. The user reviews and merges the PR. Nothing is pushed to `main` directly.

A release changes the version. Docs-, test- and CI-only changes keep the
version and add no CHANGELOG entry.

## 2. The release key

The release key is a PKCS12 keystore kept outside the repository. It was
created with:

```sh
keytool -genkeypair -v -keystore ~/keys/kivycalendar-release.keystore -storetype PKCS12 -alias kivycalendar -keyalg RSA -keysize 4096 -validity 10000
```

- Never commit the keystore or its password. `.gitignore` ignores `*.keystore`
  and `*.jks`, but keep the file outside the repository folder anyway.
- Keep a backup of the keystore file and its password in a password manager.
- Every release must be signed with this same key. Installed copies can only be
  updated by an APK signed with the key they were installed with.
- Losing the key is covered under Troubleshooting.

## 3. Build a signed APK on your own machine

Set the signing variables in your own terminal. Read the password with
`read -rs` so it stays out of the shell history:

```sh
export P4A_RELEASE_KEYSTORE="$HOME/keys/kivycalendar-release.keystore"
export P4A_RELEASE_KEYALIAS=kivycalendar
read -rs P4A_RELEASE_KEYSTORE_PASSWD && echo
export P4A_RELEASE_KEYSTORE_PASSWD
export P4A_RELEASE_KEYALIAS_PASSWD="$P4A_RELEASE_KEYSTORE_PASSWD"
```

The key password is the same as the keystore password. Then build:

```sh
android/build.sh android release
```

`android/buildozer.spec` sets `android.release_artifact = apk`. The default is
an `.aab`, which only Google Play accepts. `build.sh` removes older APKs and
AABs from `android/bin/` first, so the folder keeps only this build.

Phone builds are `arm64-v8a`. Do not build a release for `x86_64`; that is only
for the emulator.

Check the signature and compare the key fingerprint with the keystore:

```sh
SDK="$HOME/.buildozer/android/platform/android-sdk/build-tools/37.0.0"
"$SDK/apksigner" verify --print-certs android/bin/*.apk
keytool -list -v -keystore "$HOME/keys/kivycalendar-release.keystore" -alias kivycalendar
```

`apksigner` prints the SHA-256 digest of the signer certificate in lowercase
hex, without colons. `keytool` prints `SHA256:` in uppercase with colons. Remove
the colons and compare the two values ignoring case. They must match.

## 4. Switching from a debug build (one time)

Debug APKs are signed with the laptop's `~/.android/debug.keystore`. A release
APK has a different signature, so Android will not install it over a debug
build. Uninstall the debug build once:

```sh
adb uninstall io.github.wanday.kivycalendar
adb install android/bin/*.apk
```

You can also uninstall from the phone's app settings. Events stay in the
phone's calendar. Only the app's own settings are reset, and the app asks for
calendar access again on the first start. After this, each release installs
over the previous one.

## 5. Publish a release (CI)

The workflow is `.github/workflows/release.yml`. It runs in two ways:

- **On a tag `vX.Y.Z`.** The tag must equal `VERSION` (the tag has a `v` in
  front, `VERSION` does not). The workflow decodes the keystore from the
  repository secrets, builds `arm64-v8a` only, checks the signature with
  `apksigner`, and creates a GitHub release. The APK is named
  `kivycalendar-<version>-arm64-v8a.apk`, and the notes are the CHANGELOG
  section for that version.
- **By hand (workflow_dispatch), as a dry run.** It builds and signs the APK and
  uploads it as a workflow artifact. It creates no release, so it is safe to
  repeat. GitHub only offers the Run workflow button once the workflow is on
  `main`.

The workflow fails if a secret is empty or the APK has no v2 signature, so it
never publishes an unsigned APK. The decoded keystore is deleted at the end of
every run. Only the Android SDK and NDK are cached (`~/.buildozer`); the build
tree is rebuilt each time, so a run takes about an hour or more. The release
job needs `contents: write`: if it fails with a permission error, allow it
under Settings, Actions, General, Workflow permissions.

Repository secrets (GitHub: Settings, Secrets and variables, Actions):

| Secret | Value |
| --- | --- |
| `RELEASE_KEYSTORE_BASE64` | The keystore file as one line of base64: `base64 -w0 ~/keys/kivycalendar-release.keystore` |
| `RELEASE_KEYSTORE_PASSWORD` | The keystore password |
| `RELEASE_KEY_ALIAS` | `kivycalendar` |

To publish, after the release PR is merged:

```sh
git switch main && git pull
git tag vX.Y.Z
git push origin vX.Y.Z
```

Watch the run under the Actions tab. When it finishes, the APK is on the
Releases page. Do not move a tag that already has a release. Publish the next
version instead.

## 6. Deploy the backend

The backend runs in Docker Compose (`docker/compose.yml`, `docker/Dockerfile`).
CI builds the image on pushes to `main` and on pull requests, but does not
publish it.

1. Copy the example file and fill it in:
   ```sh
   cp .env.example .env
   ```
   Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` and
   `BACKEND_API_TOKEN`. Set `BACKEND_BIND_IP` to the VPN interface address of
   the host. `.env` is never committed, and `.dockerignore` keeps it out of the
   image.
2. Get the refresh token once, if you do not have one. Export
   `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, then run the helper from the
   repository root. The README ("Google Calendar credentials") lists the
   details:
   ```sh
   PYTHONPATH=backend/src:shared/src python -m google_calendar.auth
   ```
   Copy the printed `GOOGLE_REFRESH_TOKEN` into `.env`.
3. Start the backend from the repository root:
   ```sh
   docker compose --env-file .env -f docker/compose.yml up -d --build
   ```
   `--env-file .env` makes Compose read `BACKEND_BIND_IP` from the root `.env`.
4. Check it from a machine on the VPN. `GET /health` needs no token:
   ```sh
   curl http://<BACKEND_BIND_IP>:8000/health
   ```

To update, run `git pull` and the same `up -d --build` command.

Security rules:

- Never make the backend reachable from the public internet, and never set
  `BACKEND_BIND_IP` to `0.0.0.0`. The container listens on all interfaces
  inside its own network. The host address is what limits access.
- The bearer token travels over plain HTTP. Reach the backend only through the
  VPN, or put a TLS reverse proxy in front of it.

Data: the `backend_data` volume (at `/data` in the container) holds the cache
and the retry queue. The cache can be rebuilt with `POST /sync`. Queued writes
cannot be rebuilt, so do not remove the volume (`docker compose down -v`) while
writes are queued.

While the Google Cloud app is in Testing, Google refresh tokens expire weekly
(`ROADMAP.md`). When requests start failing with `auth_error`, run the helper
again, replace `GOOGLE_REFRESH_TOKEN` in `.env`, and run the `up -d` command
again so the container picks up the new value.

## Troubleshooting

### Signature mismatch on install

Android will not install the APK over the installed app. `adb` reports
`INSTALL_FAILED_UPDATE_INCOMPATIBLE`.

- The installed copy is a debug build, or was signed with another key. Uninstall
  it once, then install the release APK (see section 4).
- The APK was signed with the wrong key. Compare the SHA-256 values from
  section 3. If they differ, check that `P4A_RELEASE_KEYSTORE` points to the
  release keystore and `P4A_RELEASE_KEYALIAS` is `kivycalendar`, then rebuild.

### The tag does not match VERSION

The release workflow fails when the tag is not `v` followed by `VERSION`.

1. Check `VERSION` on the commit you tagged.
2. If the workflow did not create a release, delete the wrong tag, locally and
   on GitHub:
   ```sh
   git tag -d vX.Y.Z
   git push origin :refs/tags/vX.Y.Z
   ```
3. Fix the version through a PR, merge it, and tag the merged commit again.

If a release already exists for the tag, do not reuse the tag. Publish the next
version.

### The keystore is lost

Installed copies can only be updated by an APK signed with the same key. Without
the key, no new release can update an existing install.

- Restore the keystore file and its password from the password manager backup.
  Record the SHA-256 fingerprint from `keytool -list -v` in the same note, so a
  restored file can be checked.
- If the keystore and the backup are both gone, a new key is the only option.
  Every user then has to uninstall the app once and install the new APK. Events
  stay in the phone's calendar. Replace the three repository secrets with the
  new key's values.
- If only the password is lost, the keystore cannot be used, and no recovery
  method is known. Keep the password in the password manager with the file.
