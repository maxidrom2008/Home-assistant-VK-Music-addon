# VK Music Server

Standalone VK Music server for Home Assistant OS with a companion Home Assistant `media_player` integration. It runs independently of Music Assistant and does not modify or replace the legacy Music Assistant VK Edition add-on.

**Current release candidate: `1.0.0-rc.17`.** This is a pre-release. CI validates the code, browser bundle and multi-architecture images, but real VK authorization, audible output and hardware-specific playback still require acceptance testing on the target Home Assistant installation.

## Features

- VK account authorization with VK ID browser CAPTCHA, legacy image CAPTCHA and supported two-factor/device-approval challenges.
- Persistent VK access-token storage under `/data`; passwords and one-time challenge data are held in memory only.
- Personal audio library, playlists, playlist tracks, text search and pagination.
- Browser playback through a server-side stream proxy. Temporary VK CDN URLs and private playlist access keys are not sent to the browser.
- Browser controls: play, pause, resume, stop, previous/next, volume and seek. The server reuses the signed VK stream URL while seeking and asks FFmpeg to seek in the source before transcoding, avoiding a fresh VK API lookup and full decode from the beginning for each seek.
- Optional server-side playback through FFmpeg and the Home Assistant shared PulseAudio service, with output-device selection and diagnostics.
- Companion Home Assistant `media_player` integration with library/playlist browsing and native media search.
- Home Assistant Ingress panel without a published LAN host port.
- Multi-architecture add-on images for `amd64` and `aarch64`.

## Install the Home Assistant app

1. In Home Assistant, open **Settings → Apps → Install app → ⋮ → Repositories**.
2. Add this repository:
   `https://github.com/maxidrom2008/Home-assistant-VK-Music-addon`
3. Install **VK Music Server** from the Apps store.
4. Open its Ingress panel and sign in with your VK phone/email and password.
5. Complete any CAPTCHA or verification challenge requested by VK.
6. Choose browser playback or HAOS server playback. For server playback, select an available output in the app's Audio settings.

The app publishes images to `ghcr.io/maxidrom2008/vk-music-server` for `amd64` and `aarch64`. CI builds and validates both architectures before the multi-architecture image is published from `main).

## Install the Home Assistant media_player integration

The companion integration requires Home Assistant Core **2025.5.0 or newer**, because it uses native media-player search support introduced in that release. [Home Assistant 2025.5 release notes](https://www.home-assistant.io/blog/2025/05/07/release-20255).

### Option A — HACS custom repository

This repository is not included in the default HACS catalog. Add it as a custom repository:

1. Open **HACS**.
2. Open the **⋮** menu and choose **Custom repositories**.
3. Enter `https://github.com/maxidrom2008/Home-assistant-VK-Music-addon`.
4. Select category **Integration** and add the repository.
5. Find **VK Music Server** in HACS and download it.
6. Restart Home Assistant.

See the [HACS custom repository instructions](https://hacs.dev/docs/faq/custom_repositories/).

### Option B — manual installation

Copy `custom_components/vk_music_server` from this repository into:

```text
/config/custom_components/vk_music_server
```

Then restart Home Assistant.

### Configure the integration

1. First connect the VK account in the add-on panel.
2. Copy the **internal URL** displayed under **Интеграция Home Assistant**. It looks like `http://<supervisor-hostname>:8099`.
3. In Home Assistant, open **Settings → Devices & services → Add integration**.
4. Search for **VK Music Server** and paste the internal URL.

The integration creates `media_player.vk_music_server`. It supports playback controls, browsing the personal library and playlists, and native media search. The internal URL is reachable only within the Home Assistant network; the add-on does not publish this port to the LAN.

## VK account and token handling

Only the final access token, its User-Agent and the VK user ID are stored in SQLite. Passwords, CAPTCHA answers and one-time verification codes are not persisted. In-memory login sessions expire after ten minutes and are cleared on cancellation, replacement, failure or success.

Use **Отключить VK и удалить сохранённый токен** to remove the token from add-on storage. This does not guarantee revocation inside VK; for complete revocation, also use the security/application settings in your VK account.

## API

All application endpoints are available through Home Assistant Ingress:

| Endpoint | Purpose |
|---|---|
| `GET /health` | Supervisor watchdog health check |
| `GET /api/v1/status` | Server status and version |
| `GET /api/v1/integration/info` | Internal URL for the companion integration |
| `GET /api/v1/auth/status` | VK token state |
| `POST /api/v1/auth/start` | Start VK login |
| `POST /api/v1/auth/challenge` | Submit CAPTCHA or verification response |
| `POST /api/v1/auth/challenge/refresh` | Refresh browser CAPTCHA link |
| `POST /api/v1/auth/token` | Validate and import an existing token |
| `DELETE /api/v1/auth/challenge/{challenge_id}` | Cancel an unfinished login |
| `DELETE /api/v1/auth/token` | Stop server playback and delete the saved token |
| `GET /api/v1/library/tracks` | Browse personal audio library |
| `GET /api/v1/playlists` | Browse playlists |
| `GET /api/v1/playlists/{owner_id}_{playlist_id}/tracks` | Browse playlist tracks |
| `GET /api/v1/search` | Search tracks |
| `GET /api/v1/tracks/{owner_id}_{track_id}/stream` | Proxied browser audio stream |
| `GET /api/v1/playback/state` | Current server playback state |
| `POST /api/v1/playback/server/play` | Start server playback |
| `POST /api/v1/playback/server/pause` | Pause server playback |
| `POST /api/v1/playback/server/resume` | Resume server playback |
| `POST /api/v1/playback/server/stop` | Stop server playback |
| `WS /api/v1/events` | Playback/auth events and ping/pong |

The API is restricted to Home Assistant Core, Supervisor/Ingress and loopback. Other add-on containers and LAN clients are rejected. Direct host-port publishing is intentionally disabled.

## Current limits

- VK audio availability depends on the account and VK API access rules. CAPTCHA appearance and verification methods are controlled by VK.
- Audible server-side playback depends on HAOS exposing a working PulseAudio sink and the selected device being available to the add-on.
- Browser and server playback are separate output modes.
- A native Home Assistant mobile app is not included.

## Local development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pip install pytest

cd app/web
npm install --no-audit --no-fund
npm run build
cd ../..

VKMS_DATA_DIR=./data uvicorn app.main:app --host 0.0.0.0 --port 8099
```

Run checks:

```bash
VKMS_DATA_DIR=./data pytest -q
node --check app/web/app.js
node --test tests/web_player.test.mjs
docker build --tag vk-music-server:local .
```

## Data and upgrades

The add-on maps `/data` persistently. Database migrations preserve existing records; do not remove the add-on's data directory when updating. Keep Home Assistant backups. The SQLite database and sidecar files are created with restrictive permissions where supported. Tokens are secrets: do not share database files or diagnostic backups publicly.

## Release notes

See [CHANGELOG.md](CHANGELOG.md) for the release-by-release history and [docs/RELEASE_TEST_1_0.md](docs/RELEASE_TEST_1_0.md) for the HAOS acceptance checklist. A stable `1.0.0` release should be created only after real VK authorization and physical HAOS audio checks pass.

## License

No source license has been selected by the repository owner. Until a license is added, the code is not offered under an OSI-approved open-source license.
