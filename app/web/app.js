import { CaptchaWidget } from "@vkid/captcha";
import Hls from "hls.js";

const api = p => new URL("api/v1/" + p, document.baseURI).toString();
const $ = id => document.getElementById(id);
let challengeId = null;
let challengeType = null;
let captchaWidget = null;
const PAGE_SIZE = 50;
let currentItems = [];
let currentOffset = 0;
let currentMode = "library";
let hasMoreTracks = false;
let loadSequence = 0;
let currentTrackIndex = -1;
let browserTrackIndex = -1;
let outputMode = "browser";
let selectedOutputDevice = "default";
let serverPlaybackState = { state: "idle", track: null, position: 0, output_device: "default" };
let serverTrackDuration = 0;
let serverPosition = 0;
let serverPositionMark = null;
let serverTimelineFrame = 0;
let serverSeeking = false;
let serverSeekRequestId = 0;
let currentPlaylistId = null;
let eventReconnectDelay = 3000;
let eventSocket = null;
let browserTrackDuration = 0;
// The server returns a new stream starting at the requested offset, so the
// HTMLMediaElement currentTime is relative to that stream, not the whole track.
let browserStreamOffset = 0;
let timelineFrame = 0;
let timelineSeeking = false;
let seekRequestId = 0;
let playbackVolume = 0.8;
let currentBrowserTrackId = null;
let browserHls = null;
let browserPlaybackMode = "legacy";
let spectrumContext = null;
let spectrumAnalyser = null;
let spectrumSource = null;
let spectrumData = null;
let spectrumFrame = 0;
let spectrumCanvasContext = null;
let spectrumCanvasSize = "";
const SPECTRUM_BANDS = 12;
const SPECTRUM_MIN_HZ = 50;
const SPECTRUM_MAX_HZ = 20000;
const SPECTRUM_GAIN_DB = 0;
const SPECTRUM_HIGH_SHELF_DB = 2;
const SPECTRUM_FLOOR_DB = -96;
const SPECTRUM_CEILING_DB = -24;
const SPECTRUM_CURVE = 1.08;

function stopSpectrumAnimation() {
  if (spectrumFrame) cancelAnimationFrame(spectrumFrame);
  spectrumFrame = 0;
}

function drawSpectrum() {
  spectrumFrame = 0;
  const audio = $("audio");
  const canvas = $("spectrumCanvas");
  if (!spectrumAnalyser || !spectrumCanvasContext || audio.paused || outputMode !== "browser") return;
  const width = Math.max(1, Math.floor(canvas.clientWidth || canvas.getBoundingClientRect().width || 320));
  const height = Math.max(1, Math.floor(canvas.clientHeight || 58));
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const size = Math.round(width * dpr) + "x" + Math.round(height * dpr);
  if (size !== spectrumCanvasSize) {
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    spectrumCanvasContext.setTransform(dpr, 0, 0, dpr, 0, 0);
    spectrumCanvasSize = size;
  }
  spectrumAnalyser.getFloatFrequencyData(spectrumData);
  const ctx = spectrumCanvasContext;
  ctx.clearRect(0, 0, width, height);
  const gap = 5;
  const barWidth = Math.max(2, (width - gap * (SPECTRUM_BANDS - 1)) / SPECTRUM_BANDS);
  const segmentHeight = 4;
  const segmentGap = 2;
  const segmentCount = 14;
  const segmentStep = segmentHeight + segmentGap;
  const segmentColors = ["#22c55e", "#4ade80", "#84cc16", "#a3e635", "#c7e21b", "#eab308", "#facc15", "#f59e0b", "#fb923c", "#f97316", "#ef4444", "#dc2626", "#b91c1c", "#991b1b"];
  const nyquist = spectrumContext.sampleRate / 2;
  for (let band = 0; band < SPECTRUM_BANDS; band += 1) {
    const lowHz = SPECTRUM_MIN_HZ * Math.pow(SPECTRUM_MAX_HZ / SPECTRUM_MIN_HZ, band / SPECTRUM_BANDS);
    const highHz = SPECTRUM_MIN_HZ * Math.pow(SPECTRUM_MAX_HZ / SPECTRUM_MIN_HZ, (band + 1) / SPECTRUM_BANDS);
    const binWidth = spectrumContext.sampleRate / spectrumAnalyser.fftSize;
    // Use bin-centre frequencies to keep the upper bands aligned through 20 kHz.
    const first = Math.max(0, Math.ceil(lowHz / binWidth));
    const last = Math.min(spectrumData.length - 1, Math.floor(Math.min(highHz, nyquist) / binWidth));
    let powerSum = 0;
    let count = 0;
    for (let bin = first; bin <= last; bin += 1) {
      const db = spectrumData[bin];
      if (Number.isFinite(db)) {
        const amplitude = Math.pow(10, db / 20);
        powerSum += amplitude * amplitude;
        count += 1;
      }
    }
    const bandDb = count ? 10 * Math.log10(powerSum / count) : SPECTRUM_FLOOR_DB;
    const highFrequencyLift = SPECTRUM_HIGH_SHELF_DB * (band / (SPECTRUM_BANDS - 1));
    const adjustedDb = bandDb + SPECTRUM_GAIN_DB + highFrequencyLift;
    const normalized = Math.max(0, Math.min(1,
      (adjustedDb - SPECTRUM_FLOOR_DB) / (SPECTRUM_CEILING_DB - SPECTRUM_FLOOR_DB)));
    const level = Math.pow(normalized, SPECTRUM_CURVE);
    const activeSegments = Math.min(segmentCount, Math.round(level * segmentCount));
    const x = band * (barWidth + gap);
    for (let segment = 0; segment < activeSegments; segment += 1) {
      const y = height - segmentHeight - segment * segmentStep;
      ctx.fillStyle = segmentColors[Math.min(segmentColors.length - 1,
        Math.floor(segment / (segmentCount - 1) * (segmentColors.length - 1)))];
      ctx.fillRect(x, y, barWidth, segmentHeight);
    }
  }
  spectrumFrame = requestAnimationFrame(drawSpectrum);
}

function spectrumCaptureSupported() {
  const audio = $("audio");
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  const captureStream = audio.captureStream || audio.mozCaptureStream || audio.webkitCaptureStream;
  return Boolean(AudioContextClass && typeof captureStream === "function");
}

function startSpectrum() {
  if (outputMode !== "browser") return;
  const audio = $("audio");
  const canvas = $("spectrumCanvas");
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  const captureStream = audio.captureStream || audio.mozCaptureStream || audio.webkitCaptureStream;
  if (!AudioContextClass || typeof captureStream !== "function") {
    // The visualizer is optional. Never put native media playback behind Web Audio.
    stopSpectrumAnimation();
    canvas.hidden = true;
    return;
  }
  try {
    if (!spectrumContext) {
      const capturedAudio = captureStream.call(audio);
      if (!capturedAudio || !capturedAudio.getAudioTracks?.().length) {
        canvas.hidden = true;
        return;
      }
      spectrumContext = new AudioContextClass();
      spectrumAnalyser = spectrumContext.createAnalyser();
      spectrumAnalyser.fftSize = 8192;
      spectrumAnalyser.minDecibels = -100;
      spectrumAnalyser.maxDecibels = -20;
      spectrumAnalyser.smoothingTimeConstant = 0.68;
      spectrumData = new Float32Array(spectrumAnalyser.frequencyBinCount);
      // Read a parallel capture stream. Do NOT use createMediaElementSource():
      // that API replaces the element's native output route and a suspended
      // AudioContext can make an otherwise-playing <audio> element silent.
      spectrumSource = spectrumContext.createMediaStreamSource(capturedAudio);
      spectrumSource.connect(spectrumAnalyser);
      // The analyser is intentionally not connected to AudioContext.destination.
      spectrumCanvasContext = canvas.getContext("2d");
    }
    if (!spectrumCanvasContext) {
      canvas.hidden = true;
      return;
    }
    canvas.hidden = false;
    if (spectrumContext.state === "suspended") {
      spectrumContext.resume().catch(() => {
        // A blocked analyser must not affect the native <audio> output.
        stopSpectrumAnimation();
        canvas.hidden = true;
      });
    }
    if (!spectrumFrame && spectrumCanvasContext) spectrumFrame = requestAnimationFrame(drawSpectrum);
  } catch (err) {
    // Playback must continue normally if capture, Web Audio or canvas analysis is unavailable.
    stopSpectrumAnimation();
    canvas.hidden = true;
  }
}

function applyServerPlaybackState(state) {
  if (!state) return;
  const device = String(state.output_device || "default");
  if (device !== selectedOutputDevice) return;
  serverPlaybackState = state;
  serverTrackDuration = Math.max(0, Number(state.track?.duration) || 0);
  serverPosition = Math.max(0, Number(state.position) || 0);
  serverPositionMark = state.state === "playing" ? Date.now() : null;
  if (state.track) {
    const label = (state.track.artist ? state.track.artist + " — " : "") + (state.track.title || "Без названия");
    if (outputMode === "server") $("nowPlaying").textContent = label;
    currentTrackIndex = currentItems.findIndex(item => String(item.id) === String(state.track.id));
  } else if (state.state === "idle" && outputMode === "server") {
    $("nowPlaying").textContent = "Ничего не воспроизводится";
    currentTrackIndex = -1;
  }
  if (outputMode === "server") {
    $("outputStatus").textContent = state.state === "playing"
      ? "Играет через HAOS · " + (state.output || "PulseAudio")
      : state.state === "paused"
        ? "Зона на паузе · " + (state.output || "HAOS")
        : state.state === "error"
          ? (state.error || "Ошибка серверного вывода")
          : "Зона остановлена · " + (state.output || "HAOS");
    $("serverPause").hidden = state.state !== "playing";
    $("serverResume").hidden = state.state !== "paused";
    $("serverStop").hidden = !["playing", "paused"].includes(state.state);
    const bands = state.equalizer || {};
    for (const name of ["bass", "low_mid", "mid", "high_mid", "treble"]) {
      const input = $("eq_" + name);
      if (input && !input.matches(":active")) input.value = String(Number(bands[name]) || 0);
      const output = $("eq_" + name + "_value");
      if (output) output.textContent = (Number(bands[name]) || 0) + " dB";
    }
    $("volumeControl").value = String(Math.round((state.volume == null ? 0.8 : Number(state.volume)) * 100));
    $("volumeValue").textContent = $("volumeControl").value + "%";
    renderServerTimeline();
    if (serverTimelineFrame) cancelAnimationFrame(serverTimelineFrame);
    serverTimelineFrame = 0;
    if (state.state === "playing") serverTimelineFrame = requestAnimationFrame(updateServerTimeline);
  }
}

function renderServerTimeline() {
  const seek = $("serverTimelineSeek");
  if (!seek) return;
  const elapsed = serverPosition + (serverPositionMark ? Math.max(0, Date.now() - serverPositionMark) / 1000 : 0);
  seek.disabled = outputMode !== "server" || !serverPlaybackState.track || serverTrackDuration <= 0;
  seek.max = String(Math.max(1, Math.ceil(serverTrackDuration)));
  if (!serverSeeking) {
    seek.value = String(Math.min(Math.floor(elapsed), Number(seek.max)));
    $("serverElapsedTime").textContent = formatDuration(elapsed);
  }
  $("serverTotalTime").textContent = formatDuration(serverTrackDuration);
}

function updateServerTimeline() {
  renderServerTimeline();
  if (serverTimelineFrame) cancelAnimationFrame(serverTimelineFrame);
  serverTimelineFrame = 0;
  if (outputMode === "server" && serverPlaybackState.state === "playing") {
    serverTimelineFrame = requestAnimationFrame(updateServerTimeline);
  }
}

async function refreshPlaybackZones() {
  try {
    const data = await call("playback/states");
    const host = $("activeZones");
    if (!host) return;
    const active = (data.zones || []).filter(zone => ["playing", "paused", "error"].includes(zone.state));
    const summary = $("zoneSummaryStatus");
    if (summary) summary.textContent = active.length
      ? active.length + " активных HAOS-зон"
      : "Настроить отдельные аудиовыходы";
    host.replaceChildren();
    if (!active.length) {
      host.textContent = "Сейчас нет активных HAOS-зон.";
      return;
    }
    for (const zone of active) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "zoneStatus";
      item.setAttribute("aria-pressed", String(zone.output_device === selectedOutputDevice));
      item.title = "Переключить панель управления на эту зону";
      const name = document.createElement("strong");
      name.textContent = zone.output || zone.output_device || "HAOS";
      const detail = document.createElement("span");
      const track = zone.track ? [zone.track.artist, zone.track.title].filter(Boolean).join(" — ") : "Нет трека";
      detail.textContent = track + " · " + (zone.state === "playing" ? "играет" : zone.state === "paused" ? "пауза" : "ошибка");
      item.append(name, detail);
      item.addEventListener("click", async () => {
        if (outputMode !== "server") await setOutputMode("server");
        if (zone.output_device !== selectedOutputDevice) await setAudioOutput(zone.output_device);
      });
      host.append(item);
    }
  } catch (err) {
    // Keep the player usable with older servers while the add-on is updating.
  }
}

function connectEvents() {
  if (!("WebSocket" in window)) return;
  if (eventSocket && (eventSocket.readyState === WebSocket.CONNECTING || eventSocket.readyState === WebSocket.OPEN)) return;
  try {
    const url = new URL("api/v1/events", document.baseURI);
    url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(url);
    eventSocket = socket;
    socket.addEventListener("open", () => { eventReconnectDelay = 3000; });
    socket.addEventListener("message", event => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === "playback.state") {
          applyServerPlaybackState(message.data);
          refreshPlaybackZones();
        }
      } catch (err) {}
    });
    socket.addEventListener("close", () => {
      if (eventSocket === socket) eventSocket = null;
      setTimeout(connectEvents, eventReconnectDelay);
      eventReconnectDelay = Math.min(eventReconnectDelay * 2, 60000);
    });
    socket.addEventListener("error", () => socket.close());
  } catch (err) {
    setTimeout(connectEvents, eventReconnectDelay);
    eventReconnectDelay = Math.min(eventReconnectDelay * 2, 60000);
  }
}

async function call(path, options={}) {
  const response = await fetch(api(path), {headers:{"Content-Type":"application/json"}, ...options});
  const data = await response.json().catch(()=>({detail:"Некорректный ответ сервера"}));
  if (!response.ok) throw new Error(data.detail || ("HTTP " + response.status));
  return data;
}
async function destroyCaptchaWidget() {
  if (captchaWidget) {
    try { captchaWidget.destroy(); } catch (e) {}
    captchaWidget = null;
  }
  $("vkCaptcha").replaceChildren();
}
async function finishLogin() {
  await destroyCaptchaWidget();
  challengeId = null;
  challengeType = null;
  $("challenge").style.display = "none";
  await refreshStatus();
  $("message").textContent = "VK успешно подключён.";
  $("message").className = "msg ok";
}
async function refreshStatus() {
  try {
    const s = await call("auth/status");
    if (s.state === "validation_unavailable") {
      const firstConnect = $("music").hidden;
      $("status").textContent = "Токен VK сохранён" + (s.user_id ? " · ID " + s.user_id : "") + " · проверка VK временно недоступна";
      $("status").className = "status";
      $("login").hidden = true;
      $("manualToken").hidden = true;
      $("connectedActions").hidden = false;
      $("music").hidden = false;
      $("haIntegration").hidden = true;
      $("audio").pause();
      try {
        const integration = await call("integration/info");
        $("haIntegration").hidden = !integration.available;
        $("internalBaseUrl").textContent = integration.base_url || "";
      } catch (e) {
        $("haIntegration").hidden = true;
      }
      if (firstConnect) await loadTracks("library", false);
    } else if (s.authenticated) {
      const firstConnect = $("music").hidden;
      $("status").textContent = "VK подключён" + (s.user_id ? " · ID " + s.user_id : "") + (s.updated_at ? " · сохранён " + s.updated_at : "");
      $("status").className = "status ok";
      $("login").hidden = true;
      $("manualToken").hidden = true;
      $("connectedActions").hidden = false;
      $("music").hidden = false;
      try {
        const integration = await call("integration/info");
        $("haIntegration").hidden = !integration.available;
        $("internalBaseUrl").textContent = integration.base_url || "";
      } catch (e) {
        $("haIntegration").hidden = true;
      }
      if (firstConnect) await loadTracks("library", false);
    } else if (s.token_saved) {
      $("status").textContent = "Токен сохранён, но VK его не принимает. Подключите аккаунт заново или удалите токен.";
      $("login").hidden = false;
      $("manualToken").hidden = false;
      $("connectedActions").hidden = false;
      $("haIntegration").hidden = true;
      $("music").hidden = true;
      $("audio").pause();
      $("audio").removeAttribute("src");
      currentTrackIndex = -1;
    } else {
      $("status").textContent = "VK не подключён";
      $("login").hidden = false;
      $("manualToken").hidden = false;
      $("connectedActions").hidden = true;
      $("haIntegration").hidden = true;
      $("music").hidden = true;
      $("audio").pause();
      $("audio").removeAttribute("src");
      currentTrackIndex = -1;
    }
  } catch(e) {$("status").textContent = "Ошибка проверки: " + e.message;}
}
function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  return Math.floor(value / 60) + ":" + String(Math.floor(value % 60)).padStart(2, "0");
}
function renderBrowserTimeline() {
  const audio = $("audio");
  const streamElapsed = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
  const elapsed = browserStreamOffset + Math.max(0, streamElapsed);
  const duration = browserTrackDuration;
  const seek = $("timelineSeek");
  seek.disabled = outputMode !== "browser" || !currentBrowserTrackId || duration <= 0;
  seek.max = String(Math.max(1, Math.ceil(duration)));
  if (!timelineSeeking) {
    seek.value = String(Math.min(Math.floor(elapsed), Number(seek.max)));
    $("elapsedTime").textContent = formatDuration(elapsed);
  }
  $("totalTime").textContent = formatDuration(duration);
}
function startBrowserTimeline(duration) {
  browserTrackDuration = Math.max(0, Number(duration) || 0);
  browserStreamOffset = 0;
  $("browserTimeline").hidden = outputMode !== "browser";
  timelineSeeking = false;
  const seek = $("timelineSeek");
  seek.min = "0";
  seek.max = String(Math.max(1, Math.ceil(browserTrackDuration)));
  seek.step = "1";
  seek.value = "0";
  seek.disabled = outputMode !== "browser" || !currentBrowserTrackId || browserTrackDuration <= 0;
  $("elapsedTime").textContent = "0:00";
  $("totalTime").textContent = formatDuration(browserTrackDuration);
  if (timelineFrame) cancelAnimationFrame(timelineFrame);
  timelineFrame = 0;
  renderBrowserTimeline();
}
function stopBrowserTimeline() {
  if (timelineFrame) cancelAnimationFrame(timelineFrame);
  timelineFrame = 0;
}
function updateBrowserTimeline() {
  renderBrowserTimeline();
  if (timelineFrame) cancelAnimationFrame(timelineFrame);
  timelineFrame = 0;
  const audio = $("audio");
  if (outputMode === "browser" && !audio.paused && !audio.ended) {
    timelineFrame = requestAnimationFrame(updateBrowserTimeline);
  }
}
async function seekBrowserStream(seconds) {
  const audio = $("audio");
  const requestId = ++seekRequestId;
  const target = Math.max(0, Math.min(browserTrackDuration, Number(seconds) || 0));
  if (browserPlaybackMode === "hls") {
    try {
      // HLS.js/native HLS performs an in-stream seek; no FFmpeg process restart.
      audio.currentTime = target;
      browserStreamOffset = 0;
      $("libraryMessage").textContent = "";
    } catch (err) {
      $("libraryMessage").textContent = "Не удалось перемотать HLS-поток: " + err.message;
    } finally {
      timelineSeeking = false;
      renderBrowserTimeline();
    }
    return;
  }
  const wasPlaying = !audio.paused && !audio.ended;
  const source = api("tracks/" + encodeURIComponent(currentBrowserTrackId) + "/stream?start=" + target.toFixed(3));
  audio.pause();
  browserStreamOffset = target;
  audio.src = source;
  const ready = new Promise((resolve, reject) => {
    const cleanup = () => {
      audio.removeEventListener("canplay", onReady);
      audio.removeEventListener("error", onError);
    };
    const onReady = () => { cleanup(); resolve(); };
    const onError = () => {
      cleanup();
      reject(new Error(audio.error?.message || "Не удалось загрузить поток"));
    };
    audio.addEventListener("canplay", onReady, { once: true });
    audio.addEventListener("error", onError, { once: true });
    audio.load();
    if (audio.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA) {
      cleanup();
      resolve();
    }
  });
  try {
    await ready;
    if (requestId !== seekRequestId) return;
    audio.volume = playbackVolume;
    if (wasPlaying) await audio.play();
    $("libraryMessage").textContent = "";
  } catch (err) {
    if (requestId === seekRequestId) $("libraryMessage").textContent = "Не удалось перемотать трек: " + err.message;
  } finally {
    if (requestId === seekRequestId) {
      timelineSeeking = false;
      renderBrowserTimeline();
    }
  }
}
function destroyBrowserHls() {
  if (browserHls) {
    browserHls.destroy();
    browserHls = null;
  }
}
async function startLegacyBrowserStream(track, start = 0) {
  destroyBrowserHls();
  browserPlaybackMode = "legacy";
  browserStreamOffset = Math.max(0, Number(start) || 0);
  const audio = $("audio");
  audio.volume = playbackVolume;
  const suffix = browserStreamOffset > 0 ? "?start=" + browserStreamOffset.toFixed(3) : "";
  audio.src = api("tracks/" + encodeURIComponent(track.id) + "/stream" + suffix);
  await audio.play();
}
async function startHlsBrowserStream(track) {
  const audio = $("audio");
  const nativeHls = audio.canPlayType("application/vnd.apple.mpegurl");
  if (!Hls.isSupported() && !nativeHls) return false;
  const session = await call("tracks/" + encodeURIComponent(track.id) + "/hls", { method: "POST" });
  const manifestUrl = new URL(session.manifest_url, document.baseURI).toString();
  browserStreamOffset = 0;
  browserPlaybackMode = "hls";
  if (!Hls.isSupported()) {
    audio.src = manifestUrl;
    audio.volume = playbackVolume;
    await audio.play();
    return true;
  }
  destroyBrowserHls();
  const instance = new Hls({ enableWorker: true, lowLatencyMode: false });
  browserHls = instance;
  await new Promise((resolve, reject) => {
    let settled = false;
    instance.on(Hls.Events.MEDIA_ATTACHED, () => instance.loadSource(manifestUrl));
    instance.on(Hls.Events.MANIFEST_PARSED, () => {
      settled = true;
      resolve();
    });
    instance.on(Hls.Events.ERROR, (_event, data) => {
      if (!data.fatal) return;
      if (!settled) {
        settled = true;
        reject(new Error(data.details || "HLS playback failed"));
        return;
      }
      const position = audio.currentTime || 0;
      destroyBrowserHls();
      startLegacyBrowserStream(track, position).catch(err => {
        $("libraryMessage").textContent = "HLS и резервный поток недоступны: " + err.message;
      });
    });
    instance.attachMedia(audio);
  });
  audio.volume = playbackVolume;
  await audio.play();
  return true;
}
function renderPlaylists(items) {
  const list = $("trackList");
  list.replaceChildren();
  $("backToPlaylists").hidden = true;
  $("loadMore").style.display = "none";
  $("libraryMessage").textContent = items.length
    ? "Плейлисты аккаунта VK: " + items.length
    : "Плейлисты не найдены.";
  for (const playlist of items) {
    const row = document.createElement("div");
    row.className = "trackRow";
    const meta = document.createElement("div");
    meta.className = "trackMeta";
    const title = document.createElement("div");
    title.className = "trackTitle";
    title.textContent = playlist.title || "Плейлист без названия";
    const description = document.createElement("div");
    description.className = "trackArtist";
    description.textContent = playlist.description || "Плейлист VK";
    meta.append(title, description);
    const open = document.createElement("button");
    open.type = "button";
    open.textContent = "Открыть";
    open.addEventListener("click", () => {
      currentPlaylistId = playlist.id;
      loadTracks("playlist", false);
    });
    row.append(meta, open);
    list.append(row);
  }
}
async function loadPlaylists() {
  const sequence = ++loadSequence;
  currentMode = "playlists";
  currentPlaylistId = null;
  currentItems = [];
  $("trackList").replaceChildren();
  $("loadMore").style.display = "none";
  $("backToPlaylists").hidden = true;
  $("libraryMessage").textContent = "Загружаю плейлисты…";
  try {
    const data = await call("playlists?limit=100&offset=0");
    if (sequence !== loadSequence) return;
    renderPlaylists(data.items || []);
  } catch (err) {
    if (sequence === loadSequence) $("libraryMessage").textContent = err.message;
  }
}
function renderTracks() {
  const list = $("trackList");
  list.replaceChildren();
  $("backToPlaylists").hidden = currentMode !== "playlist";
  currentItems.forEach((track, index) => {
    const row = document.createElement("div");
    row.className = "trackRow";
    const meta = document.createElement("div");
    meta.className = "trackMeta";
    const title = document.createElement("div");
    title.className = "trackTitle";
    title.textContent = track.title || "Без названия";
    const artist = document.createElement("div");
    artist.className = "trackArtist";
    artist.textContent = track.artist || "Неизвестный исполнитель";
    meta.append(title, artist);
    const duration = document.createElement("span");
    duration.className = "trackDuration";
    duration.textContent = formatDuration(track.duration);
    const play = document.createElement("button");
    play.type = "button";
    play.textContent = "Слушать";
    play.addEventListener("click", () => playTrack(index));
    row.append(meta, duration, play);
    list.append(row);
  });
  $("loadMore").style.display = hasMoreTracks ? "block" : "none";
  if (!currentItems.length) $("libraryMessage").textContent = "Треки не найдены.";
}
async function loadTracks(mode="library", append=false) {
  const query = mode === "search" ? $("searchQuery").value.trim() : "";
  if (mode === "search" && !query) mode = "library";
  currentMode = mode;
  const offset = append ? currentOffset : 0;
  const sequence = ++loadSequence;
  $("libraryMessage").textContent = "Загрузка…";
  if (!append) {
    currentItems = [];
    currentTrackIndex = -1;
    currentOffset = 0;
    hasMoreTracks = false;
    renderTracks();
  }
  const params = new URLSearchParams({limit:String(PAGE_SIZE),offset:String(offset)});
  const endpoint = mode === "search"
    ? "search?q=" + encodeURIComponent(query) + "&" + params.toString()
    : mode === "playlist"
      ? "playlists/" + encodeURIComponent(currentPlaylistId || "") + "/tracks?" + params.toString()
      : "library/tracks?" + params.toString();
  try {
    const data = await call(endpoint);
    if (sequence !== loadSequence) return;
    const items = Array.isArray(data.items) ? data.items : [];
    currentItems = append ? currentItems.concat(items) : items;
    currentOffset = offset + items.length;
    hasMoreTracks = Boolean(data.has_more ?? (items.length === PAGE_SIZE));
    $("libraryMessage").textContent = currentItems.length
      ? (mode === "search"
          ? "Результаты поиска: "
          : mode === "playlist"
            ? "Треки плейлиста: "
            : "В моей музыке: ") + currentItems.length
      : "Треки не найдены.";
    renderTracks();
  } catch (err) {
    if (sequence !== loadSequence) return;
    $("libraryMessage").textContent = err.message;
  }
}
async function playTrack(index, targetMode = outputMode) {
  const track = currentItems[index];
  if (!track || !track.id) return;
  currentTrackIndex = index;
  if (targetMode === "server") {
    try {
      const state = await call("playback/server/play", {
        method: "POST",
        body: JSON.stringify({ track_id: track.id, output_device: selectedOutputDevice }),
      });
      applyServerPlaybackState(state);
      $("libraryMessage").textContent = state.state === "playing"
        ? "Трек запущен в зоне «" + (state.output || selectedOutputDevice) + "». Другие зоны продолжают играть."
        : (state.error || "Сервер не смог начать воспроизведение.");
      await refreshPlaybackZones();
    } catch (err) {
      $("libraryMessage").textContent = err.message;
      $("outputStatus").textContent = "Серверный вывод недоступен. Проверьте аудиовыход add-on.";
    }
    return;
  }

  browserTrackIndex = index;
  currentBrowserTrackId = String(track.id);
  if (outputMode === "browser") $("nowPlaying").textContent = (track.artist ? track.artist + " — " : "") + (track.title || "Без названия");
  startBrowserTimeline(track.duration);
  const audio = $("audio");
  destroyBrowserHls();
  try {
    const usedHls = await startHlsBrowserStream(track);
    if (!usedHls) await startLegacyBrowserStream(track);
    if (outputMode === "browser") $("outputStatus").textContent = "Воспроизведение в браузере";
  } catch (err) {
    destroyBrowserHls();
    try {
      await startLegacyBrowserStream(track);
      if (outputMode === "browser") $("outputStatus").textContent = "HLS недоступен — включён резервный FFmpeg-поток";
    } catch (fallbackError) {
      $("libraryMessage").textContent = "Не удалось начать воспроизведение: " + (fallbackError.message || err.message || String(err));
    }
  }
}
async function refreshAudioOutputs() {
  const select = $("audioOutput");
  const previous = select.value;
  try {
    const data = await call("playback/outputs");
    $("outputNotice").textContent = data.notice || "Показаны устройства, доступные аудиослужбе HAOS.";
    if (data.supervisor_error) {
      $("outputNotice").textContent += " Не удалось запросить полный список Supervisor; показан резервный список PulseAudio.";
    }
    if (!data.device_count) {
      $("outputNotice").textContent += " Сейчас аудиослужба не сообщила ни одного физического выхода.";
    } else if (data.default_sink) {
      $("outputNotice").textContent += " Текущий выход по умолчанию: " + data.default_sink + ".";
    }
    select.replaceChildren();
    for (const output of data.outputs || []) {
      const option = document.createElement("option");
      option.value = output.id;
      option.textContent = output.name;
      select.append(option);
    }
    select.value = data.selected || previous || "default";
    if (!select.value) select.value = "default";
    selectedOutputDevice = select.value;
    select.disabled = false;
    await refreshPlaybackZones();
  } catch (err) {
    select.disabled = true;
    $("outputStatus").textContent = "Не удалось получить устройства HAOS: " + err.message;
  }
}
async function setAudioOutput(device) {
  try {
    const selected = await call("playback/output", {
      method:"POST", body:JSON.stringify({device})
    });
    selectedOutputDevice = selected.selected || device;
    $("outputStatus").textContent = "Активная зона: " + selected.name + ". Переключение не останавливает другие зоны.";
    const state = await call("playback/state?output_device=" + encodeURIComponent(selectedOutputDevice));
    applyServerPlaybackState(state);
    await refreshPlaybackZones();
  } catch (err) {
    $("outputStatus").textContent = err.message;
    await refreshAudioOutputs();
  }
}
async function setOutputMode(mode) {
  outputMode = mode;
  $("browserOutput").className = mode === "browser" ? "" : "secondary";
  $("serverOutput").className = mode === "server" ? "" : "secondary";
  $("browserTimeline").hidden = mode !== "browser" || !currentBrowserTrackId;
  $("serverTimeline").hidden = mode !== "server";
  $("playerOutputPicker").hidden = mode !== "server";
  $("zoneSettings").open = mode === "server";
  $("serverEqualizer").hidden = mode !== "server";
  $("spectrumCanvas").hidden = mode === "server" || !spectrumCaptureSupported();
  $("browserControls").hidden = mode === "server";
  $("serverControls").hidden = mode !== "server";
  $("browserPause").hidden = mode !== "browser" || $("audio").paused;
  $("browserResume").hidden = mode !== "browser" || !$("audio").paused || !$("audio").src;
  $("browserStop").hidden = mode !== "browser" || !$("audio").src;
  if (mode === "browser") {
    stopSpectrumAnimation();
    $("serverPause").hidden = true;
    $("serverResume").hidden = true;
    $("serverStop").hidden = true;
    $("volumeControl").value = String(Math.round(playbackVolume * 100));
    $("volumeValue").textContent = Math.round(playbackVolume * 100) + "%";
    $("volumeControl").previousElementSibling.textContent = "Громкость браузера";
    $("audio").volume = playbackVolume;
    if (!$("audio").paused && !timelineFrame) timelineFrame = requestAnimationFrame(updateBrowserTimeline);
    if (!$("audio").paused) startSpectrum();
    $("outputStatus").textContent = "Браузерная зона. Потоки HAOS продолжают играть независимо.";
    $("zoneSummaryStatus").textContent = "Браузер · HAOS-зоны продолжают играть";
    const track = currentItems[browserTrackIndex];
    if (track) $("nowPlaying").textContent = (track.artist ? track.artist + " — " : "") + (track.title || "Без названия");
    renderBrowserTimeline();
    return;
  }

  $("volumeControl").previousElementSibling.textContent = "Громкость выбранной зоны";
  stopSpectrumAnimation();
  await refreshAudioOutputs();
  $("outputStatus").textContent = "Выбрана HAOS-зона. Браузер и остальные выходы продолжают играть.";
  $("zoneSummaryStatus").textContent = "Выбрана HAOS-зона";
  try {
    const state = await call("playback/state?output_device=" + encodeURIComponent(selectedOutputDevice));
    applyServerPlaybackState(state);
  } catch (err) {
    $("outputStatus").textContent = err.message;
  }
  await refreshPlaybackZones();
}
async function serverPlaybackAction(action) {
  try {
    const state = await call(
      "playback/server/" + action + "?output_device=" + encodeURIComponent(selectedOutputDevice),
      { method: "POST" },
    );
    applyServerPlaybackState(state);
    $("outputStatus").textContent = action === "pause"
      ? "Пауза · " + (state.output || "HAOS")
      : action === "resume"
        ? "Продолжает играть · " + (state.output || "HAOS")
        : "Зона остановлена · " + (state.output || "HAOS");
    await refreshPlaybackZones();
    return state;
  } catch (err) {
    $("libraryMessage").textContent = err.message;
  }
}

async function seekServerStream(seconds) {
  const requestId = ++serverSeekRequestId;
  const target = Math.max(0, Math.min(serverTrackDuration, Number(seconds) || 0));
  try {
    const state = await call("playback/server/seek", {
      method: "POST",
      body: JSON.stringify({ position: target, output_device: selectedOutputDevice }),
    });
    if (requestId === serverSeekRequestId) applyServerPlaybackState(state);
  } catch (err) {
    $("libraryMessage").textContent = "Не удалось перемотать HAOS-поток: " + err.message;
  } finally {
    if (requestId === serverSeekRequestId) {
      serverSeeking = false;
      renderServerTimeline();
    }
  }
}

async function updateServerEqualizer() {
  const bands = {};
  for (const name of ["bass", "low_mid", "mid", "high_mid", "treble"]) {
    bands[name] = Number($("eq_" + name).value) || 0;
    $("eq_" + name + "_value").textContent = bands[name] + " dB";
  }
  try {
    const state = await call("playback/server/equalizer", {
      method: "POST",
      body: JSON.stringify({ output_device: selectedOutputDevice, ...bands }),
    });
    applyServerPlaybackState(state);
    await refreshPlaybackZones();
  } catch (err) {
    $("libraryMessage").textContent = "Не удалось применить эквалайзер: " + err.message;
  }
}

async function playNext(targetMode = outputMode) {
  const currentIndex = targetMode === "browser" ? browserTrackIndex : currentTrackIndex;
  const nextIndex = currentIndex + 1;
  if (nextIndex < currentItems.length) return playTrack(nextIndex, targetMode);
  if (hasMoreTracks) {
    const previousLength = currentItems.length;
    await loadTracks(currentMode, true);
    if (currentItems.length > previousLength) return playTrack(previousLength, targetMode);
  }
}
function playPrevious() {
  const currentIndex = outputMode === "browser" ? browserTrackIndex : currentTrackIndex;
  if (currentIndex > 0) playTrack(currentIndex - 1, outputMode);
}
async function showChallenge(data) {
  await destroyCaptchaWidget();
  challengeId = data.challenge_id;
  const targetChallengeId = challengeId;
  const c = data.challenge || {};
  challengeType = c.type || "verification_code";
  $("challenge").style.display = "block";
  $("challengeTitle").textContent = challengeType === "browser_captcha" || challengeType === "captcha" ? "CAPTCHA VK" : "Подтверждение входа";
  $("challengeHint").textContent = c.hint || c.phone_mask || c.label || "";
  $("captcha").hidden = challengeType !== "captcha" || !c.image;
  if (!$("captcha").hidden) $("captcha").src = c.image;
  $("vkCaptcha").hidden = challengeType !== "browser_captcha";
  $("answerLabel").hidden = challengeType === "browser_captcha" || challengeType === "unsupported_captcha";
  $("answer").hidden = challengeType === "browser_captcha" || challengeType === "unsupported_captcha";
  $("answer").value = "";
  $("approved").checked = false;
  $("approvalOption").hidden = !c.approval_supported || challengeType !== "verification_code";
  $("answerButton").hidden = challengeType === "unsupported_captcha";
  $("answerButton").textContent = challengeType === "browser_captcha" ? "Проверить и продолжить" : "Отправить";
  $("refreshCaptchaButton").hidden = challengeType !== "browser_captcha";
  $("message").textContent = data.error || "";
  $("message").className = "msg";
  if (challengeType !== "browser_captcha") {
    if (challengeType === "unsupported_captcha") {
      $("message").textContent = c.hint || c.label || "Этот формат CAPTCHA пока не поддерживается.";
    } else {
      $("answer").focus();
    }
    return;
  }

  try {
    // The VK ID CAPTCHA SDK is bundled into the add-on image.
    if (challengeId !== targetChallengeId) return;
    const widget = new CaptchaWidget();
    captchaWidget = widget;
    await widget.render({link:c.link, container:"#vkCaptcha"});
    if (challengeId !== targetChallengeId) {
      try { widget.destroy(); } catch (e) {}
      return;
    }
    $("challengeHint").textContent = "Пройдите проверку в блоке VK. После её завершения нажмите «Проверить и продолжить». Ссылка одноразовая.";
  } catch (err) {
    $("message").textContent = "Не удалось загрузить виджет VK CAPTCHA: " + (err.message || String(err)) + ". Проверьте, что сборка интерфейса установлена; при необходимости обновите ссылку CAPTCHA.";
  }
}
async function submitChallenge() {
  if (!challengeId) return;
  let answer = "";
  if (challengeType === "browser_captcha") {
    if (!captchaWidget) {
      $("message").textContent = "Виджет CAPTCHA ещё не загружен. Перезапустите страницу add-on и запросите новую ссылку.";
      return;
    }
    try {
      answer = await captchaWidget.execute();
      if (typeof answer !== "string" || !answer.trim()) throw new Error("VK не вернул токен CAPTCHA");
    } catch (code) {
      const errorCode = String(code);
      const messages = {
        not_passed: "Сначала пройдите проверку VK в виджете.",
        token_expired: "Ссылка CAPTCHA истекла. Запросите новую ссылку.",
        already_checked: "Эта CAPTCHA уже использована. Запросите новую ссылку.",
        close: "Проверка закрыта. Пройдите её заново.",
        timeout: "VK пока не ответил. Повторите проверку или обновите ссылку.",
        failed: "VK не завершил проверку. Обновите ссылку и попробуйте ещё раз."
      };
      $("message").textContent = messages[errorCode] || ("Ошибка CAPTCHA: " + errorCode);
      return;
    }
  } else {
    answer = $("answer").value.trim();
    const approved = $("approved").checked;
    if (!answer && !approved) {
      $("message").textContent = "Введите код или подтвердите вход в приложении VK/MAX.";
      return;
    }
    $("answerButton").disabled = true;
    try {
      const data = await call("auth/challenge",{method:"POST",body:JSON.stringify({challenge_id:challengeId,answer,approved})});
      if (data.state === "challenge_required") await showChallenge(data);
      else await finishLogin();
    } catch(err) {
      $("message").textContent = err.message;
    } finally {
      $("answerButton").disabled = false;
    }
    return;
  }

  $("answerButton").disabled = true;
  try {
    const data = await call("auth/challenge",{method:"POST",body:JSON.stringify({challenge_id:challengeId,answer})});
    if (data.state === "challenge_required") await showChallenge(data);
    else await finishLogin();
  } catch(err) {
    $("message").textContent = err.message;
  } finally {
    $("answerButton").disabled = false;
  }
}
$("login").addEventListener("submit", async e => {
  e.preventDefault();
  $("loginButton").disabled = true;
  $("message").textContent = "";
  try {
    const data = await call("auth/start", {method:"POST",body:JSON.stringify({login:$("loginName").value,password:$("password").value})});
    $("password").value = "";
    if (data.state === "challenge_required") await showChallenge(data);
    else await finishLogin();
  } catch(err) {
    $("password").value = "";
    $("message").textContent = err.message;
  } finally {
    $("loginButton").disabled = false;
  }
});
$("tokenButton").addEventListener("click", async () => {
  const token = $("tokenValue").value.trim();
  if (!token) { $("message").textContent = "Вставьте access token VK."; return; }
  $("tokenButton").disabled = true;
  try {
    await call("auth/token", {method:"POST",body:JSON.stringify({access_token:token})});
    $("tokenValue").value = "";
    await finishLogin();
  } catch(err) { $("message").textContent = err.message; }
  finally { $("tokenButton").disabled = false; }
});
$("answerButton").addEventListener("click", submitChallenge);
$("refreshCaptchaButton").addEventListener("click", async () => {
  if (!challengeId) return;
  $("refreshCaptchaButton").disabled = true;
  try {
    const data = await call("auth/challenge/refresh", {
      method:"POST",
      body:JSON.stringify({challenge_id:challengeId})
    });
    if (data.state === "challenge_required") await showChallenge(data);
    else await finishLogin();
  } catch(err) {
    $("message").textContent = err.message;
  } finally {
    $("refreshCaptchaButton").disabled = false;
  }
});
$("cancelButton").addEventListener("click",async()=>{
  if(challengeId) {
    try { await call("auth/challenge/"+encodeURIComponent(challengeId),{method:"DELETE"}); } catch(e) {}
  }
  await destroyCaptchaWidget();
  challengeId=null;
  challengeType=null;
  $("challenge").style.display="none";
  $("message").textContent="Вход отменён.";
});
$("libraryButton").addEventListener("click", () => loadTracks("library", false));
$("playlistsButton").addEventListener("click", loadPlaylists);
$("backToPlaylists").addEventListener("click", loadPlaylists);
$("clearSearchButton").addEventListener("click", () => {
  $("searchQuery").value = "";
  loadTracks("library", false);
});
$("searchForm").addEventListener("submit", event => {
  event.preventDefault();
  loadTracks("search", false);
});
$("loadMore").addEventListener("click", () => loadTracks(currentMode, true));
$("nextTrack").addEventListener("click", playNext);
$("previousTrack").addEventListener("click", playPrevious);
$("browserOutput").addEventListener("click", () => setOutputMode("browser"));
$("serverOutput").addEventListener("click", () => setOutputMode("server"));
$("serverPause").addEventListener("click", () => serverPlaybackAction("pause"));
$("serverResume").addEventListener("click", () => serverPlaybackAction("resume"));
$("serverStop").addEventListener("click", () => serverPlaybackAction("stop"));
$("browserPause").addEventListener("click", () => $("audio").pause());
$("browserResume").addEventListener("click", async () => { try { await $("audio").play(); } catch(e) { $("libraryMessage").textContent=e.message; } });
$("browserStop").addEventListener("click", () => { const a=$("audio"); a.pause(); destroyBrowserHls(); browserPlaybackMode="legacy"; a.currentTime=0; a.removeAttribute("src"); a.load(); $("browserPause").hidden=true; $("browserResume").hidden=true; $("browserStop").hidden=true; renderBrowserTimeline(); });
$("timelineSeek").addEventListener("pointerdown", () => { timelineSeeking = true; });
$("timelineSeek").addEventListener("input", event => {
  timelineSeeking = true;
  const value = Number(event.target.value) || 0;
  $("elapsedTime").textContent = formatDuration(value);
});
$("timelineSeek").addEventListener("change", event => {
  if (outputMode !== "browser" || !currentBrowserTrackId) return;
  seekBrowserStream(event.target.value);
});
$("timelineSeek").addEventListener("pointercancel", () => { timelineSeeking = false; renderBrowserTimeline(); });
$("timelineSeek").addEventListener("blur", () => { if (timelineSeeking) { timelineSeeking = false; renderBrowserTimeline(); } });

$("serverTimelineSeek").addEventListener("pointerdown", () => { serverSeeking = true; });
$("serverTimelineSeek").addEventListener("input", event => {
  serverSeeking = true;
  $("serverElapsedTime").textContent = formatDuration(Number(event.target.value) || 0);
});
$("serverTimelineSeek").addEventListener("change", event => {
  if (outputMode === "server" && serverPlaybackState.track) seekServerStream(event.target.value);
});
$("serverTimelineSeek").addEventListener("pointercancel", () => { serverSeeking = false; renderServerTimeline(); });
$("serverTimelineSeek").addEventListener("blur", () => { if (serverSeeking) { serverSeeking = false; renderServerTimeline(); } });

for (const name of ["bass", "low_mid", "mid", "high_mid", "treble"]) {
  $("eq_" + name).addEventListener("change", updateServerEqualizer);
}
$("serverEqReset").addEventListener("click", () => {
  for (const name of ["bass", "low_mid", "mid", "high_mid", "treble"]) $("eq_" + name).value = "0";
  updateServerEqualizer();
});
$("volumeControl").addEventListener("input", async e => {
  const value = Math.max(0, Math.min(1, Number(e.target.value) / 100));
  $("volumeValue").textContent = Math.round(value * 100) + "%";
  if (outputMode === "server") {
    try {
      const state = await call("playback/volume", {
        method: "POST",
        body: JSON.stringify({ volume: value, output_device: selectedOutputDevice }),
      });
      applyServerPlaybackState({ ...serverPlaybackState, ...state });
    } catch (err) {
      $("outputStatus").textContent = "Ошибка громкости: " + err.message;
    }
  } else {
    playbackVolume = value;
    $("audio").volume = playbackVolume;
  }
});
$("audioOutput").addEventListener("change", event => setAudioOutput(event.target.value));
$("refreshOutputs").addEventListener("click", refreshAudioOutputs);
$("audio").addEventListener("play", () => { $("browserPause").hidden = false; $("browserResume").hidden = true; $("browserStop").hidden = false; if (outputMode === "browser" && !timelineFrame) timelineFrame = requestAnimationFrame(updateBrowserTimeline); startSpectrum(); });
$("audio").addEventListener("playing", startSpectrum);
$("audio").addEventListener("timeupdate", () => { if (outputMode === "browser" && !timelineSeeking) renderBrowserTimeline(); });
$("audio").addEventListener("loadedmetadata", () => {
  const duration = $("audio").duration;
  if (outputMode === "browser" && Number.isFinite(duration) && duration > 0) {
    // Keep the original VK track duration after a seek. The duration reported
    // by the replacement stream is only the unplayed tail of the track.
    if (browserTrackDuration <= 0) browserTrackDuration = browserStreamOffset + duration;
    renderBrowserTimeline();
  }
});
$("audio").addEventListener("pause", () => { stopBrowserTimeline(); stopSpectrumAnimation(); if (outputMode === "browser") { $("browserPause").hidden = true; $("browserResume").hidden = !$("audio").src || $("audio").ended; $("browserStop").hidden = !$("audio").src; renderBrowserTimeline(); } });
$("audio").addEventListener("ended", () => {
  stopBrowserTimeline();
  $("elapsedTime").textContent = formatDuration(browserTrackDuration);
  playNext("browser");
});
$("audio").addEventListener("error", () => {
  stopBrowserTimeline();
  if ($("audio").src && browserPlaybackMode === "hls") {
    const track = currentItems[browserTrackIndex];
    const position = $("audio").currentTime || 0;
    if (track) {
      startLegacyBrowserStream(track, position).then(() => {
        $("outputStatus").textContent = "HLS прерван — включён резервный FFmpeg-поток";
      }).catch(err => {
        $("libraryMessage").textContent = "HLS и резервный поток недоступны: " + err.message;
      });
    } else {
      $("libraryMessage").textContent = "HLS-поток прерван. Попробуйте повторить воспроизведение.";
    }
  } else if ($("audio").src) {
    $("libraryMessage").textContent = "VK не смог предоставить поток этого трека. Попробуйте другой трек или повторите позже.";
  }
});
$("copyInternalUrl").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("internalBaseUrl").textContent);
    $("message").textContent = "Внутренний URL скопирован.";
    $("message").className = "msg ok";
  } catch (err) {
    $("message").textContent = "Не удалось скопировать. Выделите URL и скопируйте вручную.";
  }
});
$("deleteButton").addEventListener("click",async()=>{
  if(!confirm("Удалить сохранённый токен VK из данных add-on?"))return;
  $("deleteButton").disabled=true;
  try {
    await call("auth/token",{method:"DELETE"});
    await refreshStatus();
    $("message").textContent="Токен удалён. Для доступа к музыке подключите VK заново.";
    $("message").className="msg ok";
  } catch(err) {$("message").textContent=err.message;}
  finally {$("deleteButton").disabled=false;}
});
connectEvents();
refreshStatus();