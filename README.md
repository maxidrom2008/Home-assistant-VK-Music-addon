# VK Music Server

Standalone VK Music server for Home Assistant OS. It is independent from Music Assistant and does not modify or replace the existing Music Assistant VK Edition add-on.

## 1.0.0-rc.1 — Release candidate

This release candidate includes the initial standalone feature set, security hardening, and live playback events. It is intended for final Home Assistant OS validation before the stable 1.0.0 release. Real VK-account authorization and physical audio output must still be confirmed on the target installation.

## v0.1.2 — VK ID CAPTCHA integration

The authorization flow supports both CAPTCHA formats currently returned by VK:

- **Browser CAPTCHA (VK ID):** the server passes VK's redirect_uri to the pinned @vkid/captcha 2.0.0 browser widget. The user completes the real VK challenge in the Home Assistant panel; the widget returns success_token, which is immediately submitted with the original pending login request.
- **Legacy image CAPTCHA:** the server displays captcha_img and sends the entered answer as captcha_sid / captcha_key.
- **2FA:** SMS, app code, the last four digits of a verification call, and supported push/device approval are handled; VK chooses the verification channel.

Browser CAPTCHA links are one-use and short-lived. The panel can request a fresh link if a challenge expires or the browser tab was suspended. Links are only accepted from the HTTPS VK ID hosts id.vk.com and id.vk.ru; arbitrary redirect URLs are not opened. The VK ID CAPTCHA SDK is bundled into the add-on image, so the login page does not fetch a JavaScript SDK from an external CDN. The app does not use Selenium, headless browsers, automatic solvers or CAPTCHA bypasses.

## v0.1.1 — first VK integration slice

This checkpoint adds:
- VK login based on the same vkpymusic 4.0.2 request API used by the existing VK Edition project.
- Interactive legacy image CAPTCHA and verification challenges.
- Persistent token storage in /data/vk_music.sqlite3, with no one-day deletion timer in this application.
- Explicit token deletion from the Settings page or DELETE /api/v1/auth/token.
- Personal audio library, playlists and text search API.
- Server-side proxy for client audio streams. Temporary VK CDN URLs are resolved on the server and not returned to the browser.
- Home Assistant Ingress interface, protected by Home Assistant authentication.

**Token lifetime:** the add-on keeps the token until you remove it. It cannot force VK to keep the token valid forever; VK may revoke, expire, or restrict it independently. The add-on checks whether the saved token is currently accepted.

## Home Assistant media_player integration

The repository includes a companion custom integration at `custom_components/vk_music_server`.

**Manual installation (available now):** copy the folder `custom_components/vk_music_server` into `/config/custom_components/vk_music_server` on Home Assistant, then restart Home Assistant.

After connecting the VK account in the add-on panel, copy the **internal URL** shown under **Интеграция Home Assistant**. Add the VK Music Server integration from **Settings → Devices & services → Add integration** and paste that URL (for example, `http://<supervisor-hostname>:8099`). The integration creates a `media_player.vk_music_server` entity with playback, pause, stop, media browsing for the user's library and playlists, and native Home Assistant media search.

HACS package structure and metadata are included, but the project is not submitted to the default HACS catalog. Automated HACS validation skips the license and repository-topic checks until the repository owner chooses a source license and adds GitHub topics.

The internal URL is not published on a host port. The add-on allows API access from Home Assistant Core's host-network gateway and the Supervisor/Ingress proxy only; other add-on containers and LAN clients are rejected. The add-on reads its own hostname from `GET /addons/self/info` using the limited Supervisor token.

## Install the add-on

Add this repository to the Home Assistant Apps store:

`https://github.com/maxidrom2008/Home-assistant-VK-Music-addon`

The repository builds and publishes a multi-architecture GHCR image for `amd64` and `aarch64` after the test job succeeds. The add-on manifest points to `ghcr.io/maxidrom2008/vk-music-server` and the image tag is kept in sync with the manifest version.

**First publication:** check **Packages → vk-music-server → Package settings** in GitHub. If the newly created GHCR package is private, change its visibility to **Public** so Home Assistant can pull the image without registry credentials. The repository itself can retain its existing visibility.

After adding the repository, install **VK Music Server** from the Apps store and open its panel.

## Setup and disconnect

Open **VK Music** from the Home Assistant sidebar (or open the add-on's Ingress page). Enter your VK phone/email and password. Complete the CAPTCHA or verification challenge if VK asks for one.

Only the final access token and its User-Agent are persisted. Passwords and one-time verification data are held in memory during login and are not written to SQLite. In-memory login sessions are automatically removed after ten minutes and are also cleared on cancellation, replacement, failure or success.

When connected, the page shows the VK user ID and the time the token was saved. Use **Отключить VK и удалить сохранённый токен** to delete the saved token from add-on storage. The endpoint DELETE /api/v1/auth/token does the same.

Deleting the token from this add-on does not guarantee revocation inside VK. For complete revocation, also use the security/application settings in your VK account.

## API

All application endpoints are available through Home Assistant Ingress:

- GET /health
- GET /api/v1/status
- GET /api/v1/integration/info — returns the internal URL for the companion Home Assistant integration
- GET /api/v1/auth/status
- POST /api/v1/auth/start — JSON: {"login":"...","password":"..."}
- POST /api/v1/auth/challenge — JSON: {"challenge_id":"...","answer":"...","approved":false} (a verification code, image CAPTCHA answer, browser CAPTCHA success token, or `approved: true` after VK/MAX device approval)
- POST /api/v1/auth/challenge/refresh — JSON: {"challenge_id":"..."} (request a fresh browser CAPTCHA link)
- POST /api/v1/auth/token — JSON: {"access_token":"..."} (validates and stores an existing token)
- DELETE /api/v1/auth/challenge/{challenge_id} — discard an unfinished login
- DELETE /api/v1/auth/token
- GET /api/v1/library/tracks?limit=50&offset=0
- GET /api/v1/playlists?limit=50&offset=0
- GET /api/v1/playlists/{owner_id}_{playlist_id}/tracks?limit=50&offset=0
- GET /api/v1/search?q=...&limit=50&offset=0
- GET /api/v1/tracks/{owner_id}_{track_id}/stream
- GET /api/v1/playback/state
- POST /api/v1/playback/server/play — JSON: {"track_id":"owner_id_track_id"}
- POST /api/v1/playback/server/pause
- POST /api/v1/playback/server/resume
- POST /api/v1/playback/server/stop
- WebSocket: /api/v1/events — sends server.ready, auth.state and playback.state; send the text message ping to receive server.pong

Direct host-port publishing is intentionally disabled. API access is limited to the Home Assistant Core host-network gateway, the Supervisor/Ingress proxy, and loopback. Other add-on containers and LAN clients are rejected.

## Current limits

- The web panel includes personal-library browsing, playlist browsing and track playback, search, pagination, and browser playback through the server-side stream proxy. Playlist access keys stay inside the server. The browser JavaScript is checked in CI.
- A companion Home Assistant `media_player` integration is included in `custom_components/vk_music_server`; it can be installed manually as described above. A native mobile app is still a separate roadmap task.
- Server-side playback uses FFmpeg and the Home Assistant shared PulseAudio service. Select an output device in the add-on Audio settings; actual sound output depends on HAOS exposing a working sink.
- VK audio availability depends on the account and VK's API access rules. CAPTCHA appearance is controlled by VK.

## Local development

    python -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt
    pip install pytest
    cd app/web
    npm install --no-save --package-lock=false --no-audit --no-fund
    npm run build
    cd ../..
    VKMS_DATA_DIR=./data uvicorn app.main:app --host 0.0.0.0 --port 8099

Run checks:

    VKMS_DATA_DIR=./data pytest -q
    docker build --tag vk-music-server:local .

## Data and upgrades

The add-on maps /data persistently and requests the Home Assistant shared audio service. Choose the output device in the add-on Audio configuration. Database migrations preserve existing records; do not remove the add-on's data directory when updating. Keep Home Assistant backups. The SQLite file is created with restrictive file permissions where supported. Tokens are secrets: do not share database files or diagnostic backups publicly.

## Playback modes

1. **Client-side stream:** the web player and stream proxy supply audio bytes to browsers without exposing the temporary VK CDN URL.
2. **Server-side playback:** the server resolves the VK track URL internally and runs FFmpeg into the Home Assistant PulseAudio output. Play, pause, resume and stop endpoints are available. Select the desired output in the add-on's Audio settings. Hardware-specific output still needs to be tested on the target HAOS machine.

## License

No source license has been selected by the repository owner yet. Until then, the code is not offered under an OSI-approved open-source license.
