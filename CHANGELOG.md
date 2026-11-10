# Changelog

## 0.1.1
- Integrate vkpymusic 4.0.2 for VK authorization and media requests.
- Add interactive CAPTCHA and VK verification challenge endpoints, plus manual token import for browser-only CAPTCHA flows.
- Persist the final VK access token under /data with no application-side 24-hour TTL.
- Add a settings panel and an explicit disconnect/delete-token action.
- Add personal library, playlists, text search and a server-side stream proxy.
- Restrict application traffic to Home Assistant Ingress and loopback.
- Fix pytest import path and add persistent-storage tests.

## 0.1.0
- Initial standalone FastAPI, SQLite, Home Assistant add-on and CI scaffold.
