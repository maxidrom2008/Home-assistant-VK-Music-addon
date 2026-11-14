# VK Music Server 1.0.0-rc.25 — HAOS acceptance checklist

Run these checks on a real Home Assistant OS installation. This checklist supplements CI: mocked tests do not replace real VK authorization or playback through physical audio devices. Keep the existing Music Assistant VK Edition add-on installed and untouched.

## Installation and startup

- [ ] Add the repository `https://github.com/maxidrom2008/Home-assistant-VK-Music-addon` to Home Assistant Apps.
- [ ] Confirm the installed app version is `1.0.0-rc.25`.
- [ ] Confirm the app starts and `/health` reports `{"status":"ok"}`.
- [ ] Confirm the app panel opens through Ingress and no host port is published to the LAN.
- [ ] Switch to **Вывод через HAOS** and confirm the device selector is visible directly in the player without opening advanced settings.
- [ ] Refresh the device list and confirm available HAOS/PulseAudio sinks appear with readable names.
- [ ] Restart Home Assistant while the app is still starting; confirm its integration retries setup and becomes available when the app starts.

## VK authorization and token lifecycle

- [ ] Sign in with a real VK account.
- [ ] Complete browser VK ID CAPTCHA, legacy image CAPTCHA, and any two-factor/device-approval challenge requested by VK.
- [ ] Confirm the UI shows the connected VK user ID.
- [ ] Cancel a pending login and confirm it does not save a token.
- [ ] Import a valid access token manually and confirm it is validated before storage.
- [ ] Restart the app and confirm the token remains saved.
- [ ] Temporarily block VK network access and confirm the UI reports validation unavailable, not an invalid token.
- [ ] Restore network access and confirm token validation recovers.
- [ ] Delete the token and confirm all server playback zones stop and the account is disconnected.

## Library and browser playback

- [ ] Load the personal audio library and paginate through more than one page.
- [ ] Search for a known track and open a playlist.
- [ ] Play a track in browser mode; verify audible playback, pause, resume, stop and track-end behavior.
- [ ] Verify browser audio remains audible when Web Audio is suspended or blocked; the optional spectrum visualizer must never mute native media playback.
- [ ] In a browser without `captureStream()`, confirm the visualizer hides but the track continues to play normally.
- [ ] Seek near the beginning, middle and end of a track; confirm playback resumes at the requested offset.
- [ ] Seek several times within one track and confirm the server reuses the resolved VK URL instead of querying VK again for every seek.
- [ ] Start browser playback, switch the selected control panel to HAOS, and verify browser playback continues without a pause or source reset.
- [ ] Switch back to browser mode and verify all HAOS zones continue playing.
- [ ] Reload the panel during playback and confirm it resynchronizes without stopping server-side zones.

## Independent HAOS playback zones

- [ ] Select physical output A in the visible player selector and play track A.
- [ ] Select physical output B and play a different track B.
- [ ] Confirm tracks A and B continue simultaneously on their intended physical outputs.
- [ ] Start or resume a browser track while both HAOS zones are active; confirm all three sources continue.
- [ ] Select zone A and seek; confirm only zone A restarts at the requested position and zone B continues uninterrupted.
- [ ] Change the five-band equalizer on zone A; confirm the new EQ is audible on A and zone B is unaffected.
- [ ] Change volume on zone B; confirm only the intended output is changed.
- [ ] Pause, resume and stop one zone; confirm other zones and browser playback remain unaffected.
- [ ] Use active-zone cards to switch the control panel between already playing outputs without restarting them.
- [ ] Restart the app during playback and confirm all FFmpeg processes are cleaned up.

## Home Assistant integration

- [ ] Install `custom_components/vk_music_server` through HACS as a custom Integration repository or copy it manually into `/config/custom_components/vk_music_server`.
- [ ] Restart Home Assistant and confirm Home Assistant Core is 2025.5.0 or newer.
- [ ] Add **VK Music Server** from Settings → Devices & services → Add integration using the internal URL shown in the app panel.
- [ ] Confirm `media_player.vk_music_server` is created and available.
- [ ] Browse personal tracks and playlists from Home Assistant, search for a VK track, and play a result.
- [ ] Start, pause, resume, seek, adjust volume and stop playback from Home Assistant.
- [ ] Stop the add-on temporarily; confirm the entity becomes unavailable and recovers when the app returns.

## CI checks and release decision

CI must pass Python/API tests, browser DOM tests, JavaScript syntax checks, Python compilation, Hassfest, HACS validation, and Docker builds for `amd64` and `aarch64`. The public image manifest must contain both `linux/amd64` and `linux/arm64`.

The stable `1.0.0` release should be created only after real VK authorization and physical HAOS audio checks above pass on target hardware. CI success alone does not satisfy these hardware-dependent checks.
