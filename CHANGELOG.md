# Changelog

## 0.1.2
- Add first-class VK ID browser CAPTCHA integration using the pinned @vkid/captcha 2.0.0 widget.
- Pass the browser-generated success_token back into the pending VK authorization request; retain legacy image CAPTCHA support.
- Refresh expired/consumed CAPTCHA links instead of retrying stale one-use tokens.
- Validate CAPTCHA redirect URLs against the VK ID HTTPS host allowlist before returning them to the browser.
- Expire abandoned in-memory login sessions after 10 minutes and wipe temporary credentials on cancel, replacement, failure and success.
- Add automated tests for the modern CAPTCHA request, challenge lifecycle and device-approval 2FA.
- Support push/device approval for VK 2FA methods that do not deliver a one-time code.
- Add a working browser music player with library browsing, search, pagination and next/previous track controls.
- Add server-side FFmpeg playback through the Supervisor-managed PulseAudio service, with play, pause, resume and stop controls.
- Enable the Home Assistant add-on audio interface and verify FFmpeg PulseAudio output support during image build.
- Add private playlist-track resolution and web playlist browsing without exposing VK playlist access keys.

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
