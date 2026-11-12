# VK Music Server 1.0.0-rc.13 — HAOS acceptance checklist

Run these checks on a real Home Assistant OS installation. Keep the existing Music Assistant VK Edition add-on installed and untouched. This checklist supplements CI; mocked tests do not replace tests with a real VK account and physical audio output.

## Installation and startup

- [ ] Add the repository `https://github.com/maxidrom2008/Home-assistant-VK-Music-addon` to Home Assistant Apps.
- [ ] Confirm the installed app version is `1.0.0-rc.13`.
- [ ] Confirm the app starts and `/health` reports `{"status":"ok"}`.
- [ ] Confirm the app panel opens through Ingress and no host port is published to the LAN.
- [ ] Confirm the app Audio settings list the available output devices.
- [ ] Restart Home Assistant while the app is still starting; confirm its integration retries setup and becomes available when the app starts.

## VK authorization and token lifecycle

- [ ] Sign in with a real VK account.
- [ ] Complete browser VK ID CAPTCHA, if requested.
- [ ] Complete legacy image CAPTCHA, if requested.
- [ ] Complete every challenge VK actually presents: SMS, call verification, app code or device approval.
- [ ] Confirm the UI shows the connected VK user ID.
- [ ] Cancel a pending login and confirm it does not save a token.
- [ ] Import a valid access token manually and confirm it is validated before storage.
- [ ] Restart the app and confirm the token remains saved.
- [ ] Temporarily block VK network access and confirm the UI reports validation unavailable, not an invalid token.
- [ ] Restore network access and confirm token validation recovers.
- [ ] Delete the token and confirm server playback stops and the account is disconnected.

## Library and browser player

- [ ] Load the personal audio library and paginate through more than one page.
- [ ] Search for a known track.
- [ ] Open a playlist and load its tracks.
- [ ] Play a track in browser mode; verify audio, pause, resume and track-end behavior.
- [ ] Seek near the beginning, middle and end of a track; confirm playback resumes at the requested offset.
- [ ] Switch to server mode and verify browser playback stops.
- [ ] Switch back to browser mode and verify server playback stops.
- [ ] Reload the panel during playback and confirm the UI resynchronizes to current server playback state.

## Home Assistant integration

- [ ] Install `custom_components/vk_music_server` through HACS as a custom Integration repository or copy it manually into `/config/custom_components/vk_music_server`.
- [ ] Restart Home Assistant.
- [ ] Confirm Home Assistant Core is 2025.5.0 or newer.
- [ ] Add **VK Music Server** from Settings → Devices & services → Add integration using the internal URL shown in the app panel.
- [ ] Confirm `media_player.vk_music_server` is created and available.
- [ ] Browse personal tracks and playlists from Home Assistant.
- [ ] Search VK tracks from Home Assistant's media browser and play a result.
- [ ] Start a track, pause, resume and stop it from Home Assistant.
- [ ] Stop the app temporarily; confirm the entity becomes unavailable and recovers when the app returns.

## Physical HAOS audio

- [ ] Select the intended output device in the app Audio settings.
- [ ] Play a known track using server-side playback.
- [ ] Confirm audible sound from the selected physical device.
- [ ] Select another output and confirm volume changes affect the selected device, not the default device.
- [ ] Simulate temporary Supervisor audio API unavailability; confirm the PulseAudio fallback works where available.
- [ ] Pause and resume; confirm audio actually stops and continues.
- [ ] Stop playback and confirm the audio stream closes.
- [ ] Restart the app during playback and confirm FFmpeg is cleaned up.
- [ ] Repeat on each architecture that will be advertised as supported.

## CI checks and release decision

CI must pass Python/API tests, browser DOM tests, JS syntax checks, Python compilation, Hassfest, HACS validation and Docker builds for `amd64` and `aarch64`.

The stable `1.0.0` tag should be created only after the real VK authorization and physical HAOS audio checks above pass. CI success alone does not satisfy these hardware-dependent checks.
