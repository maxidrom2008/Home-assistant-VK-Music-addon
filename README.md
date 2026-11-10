# VK Music Server

Standalone VK Music server for Home Assistant OS. It is independent from Music Assistant and does not modify or replace the existing Music Assistant VK Edition add-on.

## v0.1.1 — first VK integration slice

This checkpoint adds:
- VK login based on the same tested `vkpymusic==4.0.2` request API used by the existing VK Edition project.
- Manual CAPTCHA and verification challenge input in the add-on panel. VK chooses the validation method; the UI can accept SMS/app codes and the final four digits of a verification call.
- Persistent token storage in `/data/vk_music.sqlite3`, with no one-day deletion timer in this application.
- Explicit token deletion from the Settings page or `DELETE /api/v1/auth/token`.
- Personal audio library, playlists and text search API.
- Server-side proxy for client audio streams. Temporary VK CDN URLs are resolved on the server and not returned to the browser.
- Home Assistant Ingress interface, protected by Home Assistant authentication.

**Token lifetime:** the add-on keeps the token until you remove it. It cannot force VK to keep the token valid forever; VK may revoke, expire, or restrict it independently. The add-on checks whether the saved token is currently accepted.

## Setup and disconnect

Open **VK Music** from the Home Assistant sidebar (or open the add-on's Ingress page). Enter your VK phone/email and password. Complete CAPTCHA or the verification challenge if VK asks for one.

Only the final access token and its User-Agent are persisted. The password and one-time verification data are held in memory during the login flow and are not written to SQLite.

When connected, the page shows the VK user ID and the time the token was saved. Use **Отключить VK и удалить сохранённый токен** to delete the saved token from add-on storage. The endpoint `DELETE /api/v1/auth/token` does the same.

Deleting the token from this add-on does not guarantee revocation inside VK. For complete revocation, also use the security/application settings in your VK account.

## API

All application endpoints are available through Home Assistant Ingress:

- `GET /health`
- `GET /api/v1/status`
- `GET /api/v1/auth/status`
- `POST /api/v1/auth/start` — JSON: `{"login":"...","password":"..."}`
- `POST /api/v1/auth/challenge` — JSON: `{"challenge_id":"...","answer":"..."}`
- `DELETE /api/v1/auth/challenge/{challenge_id}` — discard an unfinished login
- `DELETE /api/v1/auth/token`
- `GET /api/v1/library/tracks?limit=50&offset=0`
- `GET /api/v1/playlists?limit=50&offset=0`
- `GET /api/v1/search?q=...&limit=50&offset=0`
- `GET /api/v1/tracks/{owner_id}_{track_id}/stream`
- `GET /api/v1/playback/state`
- WebSocket: `/api/v1/events`

Direct host-port publishing is intentionally disabled. Current Home Assistant add-on guidance recommends Ingress for web interfaces and restricting requests to the Supervisor proxy address; this server accepts Ingress traffic and loopback only.

## Current limits

- Client-side stream proxy API is implemented, but a complete browser player UI is still planned.
- A Home Assistant media_player integration and mobile app are separate roadmap tasks.
- Server-side playback to physical audio outputs is not yet implemented. FFmpeg alone is not an audio output device.
- VK audio availability depends on the account and VK's API access rules.

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

The add-on maps `/data` persistently. Database migrations preserve existing records; do not remove the add-on's data directory when updating. Keep Home Assistant backups. The SQLite file is created with restrictive file permissions where supported. Tokens are secrets: do not share database files or diagnostic backups publicly.

## Playback modes

1. **Client-side stream:** implemented proxy supplies audio bytes to clients without exposing the temporary VK CDN URL.
2. **Server-side playback:** planned output/FFmpeg layer. A dedicated sink/transport implementation and device testing are still required.

## License

To be decided.
