# VK Music Server

Standalone VK Music server for Home Assistant OS. It is independent from Music Assistant and does not modify or replace the existing Music Assistant VK Edition add-on.

## v0.1.2 — VK ID CAPTCHA integration

The authorization flow supports both CAPTCHA formats currently returned by VK:

- **Browser CAPTCHA (VK ID):** the server passes VK's redirect_uri to the pinned @vkid/captcha 2.0.0 browser widget. The user completes the real VK challenge in the Home Assistant panel; the widget returns success_token, which is immediately submitted with the original pending login request.
- **Legacy image CAPTCHA:** the server displays captcha_img and sends the entered answer as captcha_sid / captcha_key.
- **2FA:** SMS, app code, the last four digits of a verification call, and supported push/device approval are handled; VK chooses the verification channel.

Browser CAPTCHA links are one-use and short-lived. The panel can request a fresh link if a challenge expires or the browser tab was suspended. Links are only accepted from the HTTPS VK ID hosts id.vk.com and id.vk.ru; arbitrary redirect URLs are not opened. The app does not use Selenium, headless browsers, automatic solvers or CAPTCHA bypasses.

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

## Setup and disconnect

Open **VK Music** from the Home Assistant sidebar (or open the add-on's Ingress page). Enter your VK phone/email and password. Complete the CAPTCHA or verification challenge if VK asks for one.

Only the final access token and its User-Agent are persisted. Passwords and one-time verification data are held in memory during login and are not written to SQLite. In-memory login sessions expire after ten minutes and are cleared on cancellation, replacement, failure or success.

When connected, the page shows the VK user ID and the time the token was saved. Use **Отключить VK и удалить сохранённый токен** to delete the saved token from add-on storage. The endpoint DELETE /api/v1/auth/token does the same.

Deleting the token from this add-on does not guarantee revocation inside VK. For complete revocation, also use the security/application settings in your VK account.

## API

All application endpoints are available through Home Assistant Ingress:

- GET /health
- GET /api/v1/status
- GET /api/v1/auth/status
- POST /api/v1/auth/start — JSON: {"login":"...","password":"..."}
- POST /api/v1/auth/challenge — JSON: {"challenge_id":"...","answer":"...","approved":false} (a verification code, image CAPTCHA answer, browser CAPTCHA success token, or `approved: true` after VK/MAX device approval)
- POST /api/v1/auth/challenge/refresh — JSON: {"challenge_id":"..."} (request a fresh browser CAPTCHA link)
- POST /api/v1/auth/token — JSON: {"access_token":"..."} (validates and stores an existing token)
- DELETE /api/v1/auth/challenge/{challenge_id} — discard an unfinished login
- DELETE /api/v1/auth/token
- GET /api/v1/library/tracks?limit=50&offset=0
- GET /api/v1/playlists?limit=50&offset=0
- GET /api/v1/search?q=...&limit=50&offset=0
- GET /api/v1/tracks/{owner_id}_{track_id}/stream
- GET /api/v1/playback/state
- POST /api/v1/playback/server/play — JSON: {"track_id":"owner_id_track_id"}
- POST /api/v1/playback/server/pause
- POST /api/v1/playback/server/resume
- POST /api/v1/playback/server/stop
- WebSocket: /api/v1/events

Direct host-port publishing is intentionally disabled. This server accepts Home Assistant Ingress traffic and loopback only.

## Current limits

- The web panel includes personal-library browsing, track search, pagination and browser playback through the server-side stream proxy. The browser JavaScript is checked in CI.
- A native Home Assistant media_player integration and a mobile app are separate roadmap tasks.
- Server-side playback uses FFmpeg and the Home Assistant shared PulseAudio service. Select an output device in the add-on Audio settings; actual sound output depends on HAOS exposing a working sink.
- VK audio availability depends on the account and VK's API access rules. CAPTCHA appearance is controlled by VK.

## Local development

    python -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt
    pip install pytest
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

To be decided.
