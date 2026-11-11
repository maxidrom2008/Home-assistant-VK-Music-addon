# VK Music Server 1.0.0-rc.1 — HAOS acceptance checklist

Run this on a Home Assistant OS installation. Keep the existing Music Assistant VK Edition add-on installed and untouched.

## Installation and startup

- [ ] Add the repository `https://github.com/maxidrom2008/Home-assistant-VK-Music-addon` to Home Assistant Apps.
- [ ] Confirm the installed version is `1.0.0-rc.1`.
- [ ] Confirm the app starts and `/health` reports `{"status":"ok"}`.
- [ ] Confirm the app panel opens through Ingress and there is no published LAN port.
- [ ] Confirm the app Audio settings show an output device.

## VK authorization

- [ ] Sign in with a real VK account.
- [ ] Complete browser VK ID CAPTCHA, if requested.
- [ ] Complete legacy image CAPTCHA, if requested.
- [ ] Complete each challenge VK actually presents: SMS, call verification, app code or device approval.
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
- [ ] Play a track in browser mode; verify audio, pause and track-end behavior.
- [ ] Switch to server mode and verify the browser audio element is not playing simultaneously.
- [ ] Confirm the browser player receives live server playback state changes.

## Home Assistant integration

- [ ] Install `custom_components/vk_music_server` under `/config/custom_components/vk_music_server` or through a configured HACS custom repository.
- [ ] Restart Home Assistant.
- [ ] Add the VK Music Server integration using the internal URL displayed in the app panel.
- [ ] Confirm `media_player.vk_music_server` is created and available.
- [ ] Browse personal tracks and playlists from Home Assistant.
- [ ] Start a track, pause, resume and stop it from Home Assistant.

## Physical HAOS audio

- [ ] Select the intended output device in the app Audio settings.
- [ ] Play a known track using server-side playback.
- [ ] Confirm audible sound from the selected physical device.
- [ ] Pause and resume; confirm audio actually stops and continues.
- [ ] Stop playback and confirm the audio stream closes.
- [ ] Restart the app during playback and confirm FFmpeg is cleaned up.
- [ ] Repeat on each architecture that will be advertised as supported.

## Release decision

The stable `1.0.0` tag should be created only after the real VK authorization and physical HAOS audio checks above pass. CI success alone does not satisfy those hardware-dependent checks.
