# VK Music Server

Standalone VK Music server for Home Assistant OS. This project is independent from Music Assistant and does not modify or replace the existing Music Assistant VK Edition add-on.

## Current state — v0.1.0 scaffold

The repository currently contains the initial application scaffold:
- Home Assistant add-on metadata for amd64 and aarch64.
- FastAPI application with health, status, library, playlist, search and playback-state API shapes.
- WebSocket event endpoint.
- Persistent SQLite database under /data.
- Explicit VK client and client-stream adapter boundaries.
- FFmpeg included in the container image for later server-side playback work.

Not implemented yet: VK login/challenge handling, VK library access, playlist retrieval, real audio stream proxy, browser player, Home Assistant integration and physical/server-side audio outputs. API responses intentionally report these features as unavailable rather than returning fabricated data.

## Architecture

- API and WebSocket: FastAPI.
- Persistent state: SQLite in /data/vk_music.sqlite3.
- VK integration: isolated adapter in app/vk/.
- Client playback: stream proxy boundary in app/playback/.
- Server playback: planned output/FFmpeg layer; FFmpeg alone does not provide an audio output device.
- Add-on ingress: internal port 8099; optional LAN mapping to host port 8098.

## Local development

    python -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt
    pip install pytest httpx
    VKMS_DATA_DIR=./data uvicorn app.main:app --host 0.0.0.0 --port 8099

Health check: GET /health
Interactive API docs: /docs

## Data and upgrades

Persistent application data belongs in /data, which is mapped by the add-on. Never store VK passwords, one-time codes or CAPTCHA answers. Access tokens must not be exposed by status endpoints or logs. Database schema changes must be versioned and preserve existing data during upgrades.

## Playback modes

1. Client-side stream: server obtains a VK track stream and serves it to Web, mobile or other clients.
2. Server-side playback: server feeds decoded audio to a selected output through a dedicated output adapter.

Both modes are architectural goals. Neither is claimed as complete in this scaffold.

## License

To be decided.
