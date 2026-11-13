# Changelog

## 1.0.0-rc.21
- Reduce spectrum analyzer gain and soften its response to prevent loud peaks from pinning most frequency bars at maximum.
- Increase visualizer height by 50% and render 14 stacked green-to-red color segments per frequency band.

## 1.0.0-rc.20
- Increase spectrum sensitivity using RMS power aggregation, a larger FFT, a wider dynamic range and a gentle high-frequency lift; calculate band edges from actual FFT-bin frequencies through 20 kHz.
- Keep the player sticky at the top while browsing the library and combine playback/navigation controls into one compact horizontal row.

## 1.0.0-rc.18\n- Add a server-side HLS proxy that keeps signed VK CDN URLs and AES key URLs out of the browser.\n- Use HLS.js for browser playback and in-stream seeking; retain the existing FFmpeg endpoint as a compatibility fallback.\n- Rewrite playlist, variant, segment, initialization-map and key references to opaque, account-scoped local URLs; preserve byte-range requests and expire sessions.\n- Add HLS proxy tests for URI rewriting, external-host rejection, session isolation/expiry and byte-range forwarding.\n\n## 1.0.0-rc.19
- Replace the browser player's HLS/FFmpeg technical status text with a lightweight 12-band Web Audio spectrum visualizer.
- Analyze logarithmically spaced frequencies from 50 Hz to 20 kHz; pause animation when playback pauses and hide it for HAOS server output.
- Keep audio playback functional on browsers without Web Audio support and remove protocol-specific status wording.

All notable project changes are recorded here. Versions are Home Assistant add-on release candidates unless otherwise noted.

## 1.0.0-rc.17
- Remove the fixed 200 ms preflight delay before returning browser audio streams; retain an event-loop-turn check for immediately failed FFmpeg processes.
- Avoid adding a constant wait to every initial play and seek request.

## 1.0.0-rc.16
- Reuse the signed VK stream URL during browser seeks so the server does not repeat `get_songs_by_id_async` for every offset request.
- Move FFmpeg `-ss` before `-i` to use input-side seeking and avoid decoding the track from the beginning for each seek.
- Add regression tests for FFmpeg argument ordering, URL-cache reuse, expiry, account isolation and refresh on a new play action.

## 1.0.0-rc.15
- Fix browser seek timeline position after replacing the audio stream at a requested offset.
- Keep the displayed track duration and absolute seek position stable while the replacement stream reports only its remaining duration.
- Add a browser regression test covering consecutive seeks and elapsed-time updates after stream reload.

## 1.0.0-rc.14
- Harden CI metadata handling against shell injection and workflow-output newline injection; pin GitHub Actions to immutable revisions and disable persisted checkout credentials.
- Keep pull-request validation builds read-only and build the supported `amd64` and `aarch64` images without registry credentials.
- Improve server playback volume targeting and add a PulseAudio fallback with controlled errors when the Supervisor audio API is unavailable.
- Retry Home Assistant integration setup when the VK Music Server API is temporarily unavailable.
- Synchronize the current playback snapshot with newly connected and reconnected browser clients.
- Add production-bundle browser interaction tests and lock Python runtime dependencies to exact versions.
- Real VK authorization and physical HAOS audio playback still require acceptance testing before a stable `1.0.0` release.

## 1.0.0-rc.13
- Fix browser playback startup after the timeline/seek-slider rewrite by removing references to a timeline progress element that is not present in the player HTML.
- Keep the rewritten timeline renderer independent of the removed duplicate progress bar.
- This is a JavaScript startup-regression fix; real-device playback and seek behavior still require end-to-end acceptance testing.

## 1.0.0-rc.12
- Rebuild the browser seek slider and playback timeline loop around a single animation-frame updater.
- Separate slider drag preview from the committed seek action so a seek is applied once when the user finishes dragging.
- Rework seek handling to replace the proxied stream at the requested offset and guard overlapping seek requests.
- The initial rewrite contained a reference to a non-existent progress element; that startup regression is corrected in rc.13.

## 1.0.0-rc.11
- Use a controlled pause/load/readiness/resume sequence when seeking by replacing the browser audio stream.
- Guard against stale seek completions and avoid issuing `play()` while the previous source is still being replaced.

## 1.0.0-rc.10
- Re-enable the browser seek control and explicitly enable it when a browser track with a known duration is active.
- Keep the timeline synchronized with browser audio events.

## 1.0.0-rc.9
- Stabilize seek preview while dragging the timeline.
- Fix browser seeking by restarting the server-proxied VK stream at the requested position instead of relying on unsupported byte-range seeking.
- Remove the duplicate timeline display.

## 1.0.0-rc.8
- Restore browser pause, resume and stop controls and add a functional seek slider.
- Add volume control for browser and HAOS playback.
- Hide PulseAudio dummy sinks from selectable outputs.
- Polish player controls and validate browser stop-state handling.

## 1.0.0-rc.7
- Add PulseAudio diagnostics and tests for failed server-side playback.
- Improve playback failure-state reporting and use the Supervisor audio inventory with a PulseAudio fallback.

## 1.0.0-rc.3
- Add HAOS audio-device selection and refine the sticky player layout.
- Improve playback timeline behavior and HAOS audio-output diagnostics.

## 1.0.0-rc.2
- Fix browser playback for VK HLS streams by using the server-side FFmpeg stream conversion path.

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
