# Changelog

## 1.0.0-rc.8
- Restore browser pause, resume and stop controls and add a functional seek slider.
- Add volume control for browser and HAOS playback.
- Hide PulseAudio dummy sinks from selectable outputs.


## 1.0.0-rc.1
- Prepare the first 1.x release candidate.
- Harden SQLite database, WAL and SHM file permissions for persisted VK credentials.
- Prevent a cancelled or expired in-flight VK login from saving a late access token.
- Validate VK track IDs before making API requests.
- Add API authentication, database migration, cancellation and WebSocket tests.
- Implement live authentication and playback WebSocket events; keep the browser player synchronized with server playback state.
- Add native Home Assistant media search and advertise the music content type in the media player entity.
- Centralize the runtime API version and synchronize Home Assistant app, HACS integration and web package metadata.
- Add a final HAOS acceptance checklist; real-account CAPTCHA and physical audio output remain hardware-validation gates.

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
- Add the companion Home Assistant media_player integration with media browsing for personal tracks and playlists.
- Discover the app's actual internal DNS hostname through Supervisor and allow API access from Home Assistant Core without publishing a LAN port.
- Publish tested amd64 and aarch64 Home Assistant app images to GHCR and configure the app manifest to use the multi-arch image.
- Bundle the pinned VK ID CAPTCHA SDK into the app image instead of loading it from a browser-side CDN.

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
