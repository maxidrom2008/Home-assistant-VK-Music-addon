import { CaptchaWidget } from "@vkid/captcha";

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
let outputMode = "browser";
let currentPlaylistId = null;
let eventReconnectDelay = 3000;
let eventSocket = null;
let browserTrackDuration = 0;
let timelineFrame = 0;
let timelineSeeking = false;
let seekRequestId = 0;
let playbackVolume = 0.8;
let currentBrowserTrackId = null;

function applyServerPlaybackState(state) {
  if (!state || outputMode !== "server") return;
  if (state.track) {
    $("nowPlaying").textContent = (state.track.artist ? state.track.artist + " — " : "") + (state.track.title || "Без названия");
  } else if (state.state === "idle") {
    $("nowPlaying").textContent = "Ничего не воспроизводится";
    currentTrackIndex = -1;
  }
  $("outputStatus").textContent = state.state === "playing"
    ? "Играет через HAOS · " + (state.output || "PulseAudio")
    : state.state === "paused"
      ? "Серверный плеер на паузе"
      : state.state === "error"
        ? (state.error || "Ошибка серверного вывода")
        : "Серверный плеер остановлен";
  $("serverPause").hidden = state.state !== "playing";
  $("serverResume").hidden = state.state !== "paused";
  $("serverStop").hidden = !["playing", "paused"].includes(state.state);
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
        if (message.type === "playback.state") applyServerPlaybackState(message.data);
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
  const elapsed = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
  const duration = browserTrackDuration;
  const seek = $("timelineSeek");
  seek.disabled = outputMode !== "browser" || !currentBrowserTrackId || duration <= 0;
  seek.max = String(Math.max(1, Math.ceil(duration)));
  if (!timelineSeeking) {
    seek.value = String(Math.min(Math.floor(elapsed), Number(seek.max)));
    $("elapsedTime").textContent = formatDuration(elapsed);
  }
  $("totalTime").textContent = formatDuration(duration);
  $("timelineProgress").style.width = (duration > 0 ? Math.min(100, elapsed / duration * 100) : 0).toFixed(2) + "%";
}
function startBrowserTimeline(duration) {
  browserTrackDuration = Math.max(0, Number(duration) || 0);
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
  const wasPlaying = !audio.paused && !audio.ended;
  const target = Math.max(0, Math.min(browserTrackDuration, Number(seconds) || 0));
  const source = api("tracks/" + encodeURIComponent(currentBrowserTrackId) + "/stream?start=" + target.toFixed(3));

  audio.pause();
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
    if (requestId === seekRequestId) {
      $("libraryMessage").textContent = "Не удалось перемотать трек: " + err.message;
    }
  } finally {
    if (requestId === seekRequestId) {
      timelineSeeking = false;
      renderBrowserTimeline();
    }
  }
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
async function playTrack(index) {
  const track = currentItems[index];
  if (!track || !track.id) return;
  currentTrackIndex = index;
  currentBrowserTrackId = String(track.id);
  $("nowPlaying").textContent = (track.artist ? track.artist + " — " : "") + (track.title || "Без названия");
  startBrowserTimeline(track.duration);
  if (outputMode === "server") {
    stopBrowserTimeline();
    $("browserTimeline").hidden = true;
    $("audio").pause();
    $("audio").removeAttribute("src");
    try {
      const state = await call("playback/server/play", {
        method:"POST",
        body:JSON.stringify({track_id:track.id})
      });
      applyServerPlaybackState(state);
      $("outputStatus").textContent = state.state === "playing"
        ? "Играет через HAOS · " + (state.output || "PulseAudio")
        : (state.error || "Серверный вывод не начал воспроизведение");
      $("libraryMessage").textContent = state.state === "playing"
        ? "Серверное воспроизведение запущено."
        : "Сервер не смог начать воспроизведение.";
    } catch (err) {
      $("libraryMessage").textContent = err.message;
      $("outputStatus").textContent = "Серверный вывод недоступен. Проверьте аудиовыход add-on.";
    }
    return;
  }
  const audio = $("audio");
  audio.volume = playbackVolume;
  audio.src = api("tracks/" + encodeURIComponent(track.id) + "/stream");
  try {
    await audio.play();
    $("outputStatus").textContent = "Воспроизведение в этом браузере";
  } catch (err) {
    $("libraryMessage").textContent = "Не удалось начать воспроизведение: " + (err.message || String(err));
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
    select.disabled = false;
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
    $("outputStatus").textContent = "Выход HAOS: " + selected.name + ". Применится к следующему запуску трека.";
  } catch (err) {
    $("outputStatus").textContent = err.message;
    await refreshAudioOutputs();
  }
}
async function setOutputMode(mode) {
  outputMode = mode;
  $("browserOutput").className = mode === "browser" ? "" : "secondary";
  $("serverOutput").className = mode === "server" ? "" : "secondary";
  $("audio").hidden = false;
  $("browserTimeline").hidden = mode === "server";
  $("browserControls").hidden = mode === "server"; $("volumeControl").value = String(Math.round(playbackVolume*100)); $("audio").volume = playbackVolume;
  if (mode === "server") stopBrowserTimeline();
  $("serverPause").hidden = true; $("serverResume").hidden = true; $("serverStop").hidden = true;
  if (mode === "server") {
    $("audio").pause();
    await refreshAudioOutputs();
    $("outputStatus").textContent = "Следующий выбранный трек будет играть через аудиовыход HAOS.";
    try {
      const state = await call("playback/state");
      applyServerPlaybackState(state);
    } catch (err) {
      $("outputStatus").textContent = err.message;
    }
  } else {
    try { await call("playback/server/stop", {method:"POST"}); } catch (e) {}
    $("outputStatus").textContent = "Воспроизведение в этом браузере";
  }
}
async function serverPlaybackAction(action) {
  try {
    const state = await call("playback/server/" + action, {method:"POST"});
    $("outputStatus").textContent = action === "pause"
      ? "Серверный плеер на паузе"
      : action === "resume"
        ? "Серверный плеер продолжил воспроизведение"
        : "Серверный плеер остановлен";
    if (action === "stop") {
      $("nowPlaying").textContent = "Ничего не воспроизводится";
      currentTrackIndex = -1;
    }
    return state;
  } catch (err) {
    $("libraryMessage").textContent = err.message;
  }
}
async function playNext() {
  const nextIndex = currentTrackIndex + 1;
  if (nextIndex < currentItems.length) return playTrack(nextIndex);
  if (hasMoreTracks) {
    const previousLength = currentItems.length;
    await loadTracks(currentMode, true);
    if (currentItems.length > previousLength) return playTrack(previousLength);
  }
}
function playPrevious() {
  if (currentTrackIndex > 0) playTrack(currentTrackIndex - 1);
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
$("browserStop").addEventListener("click", () => { const a=$("audio"); a.pause(); a.currentTime=0; a.removeAttribute("src"); a.load(); $("browserPause").hidden=true; $("browserResume").hidden=true; $("browserStop").hidden=true; renderBrowserTimeline(); });
$("timelineSeek").addEventListener("pointerdown", () => { timelineSeeking = true; });
$("timelineSeek").addEventListener("input", event => {
  timelineSeeking = true;
  const value = Number(event.target.value) || 0;
  $("elapsedTime").textContent = formatDuration(value);
  $("timelineProgress").style.width = (browserTrackDuration > 0 ? value / browserTrackDuration * 100 : 0) + "%";
});
$("timelineSeek").addEventListener("change", event => {
  if (outputMode !== "browser" || !currentBrowserTrackId) return;
  seekBrowserStream(event.target.value);
});
$("timelineSeek").addEventListener("pointercancel", () => { timelineSeeking = false; renderBrowserTimeline(); });
$("timelineSeek").addEventListener("blur", () => { if (timelineSeeking) { timelineSeeking = false; renderBrowserTimeline(); } });
$("volumeControl").addEventListener("input",async e=>{playbackVolume=Math.max(0,Math.min(1,Number(e.target.value)/100));$("volumeValue").textContent=Math.round(playbackVolume*100)+"%";$("audio").volume=playbackVolume;if(outputMode==="server"){try{await call("playback/volume",{method:"POST",body:JSON.stringify({volume:playbackVolume})});}catch(err){$("outputStatus").textContent="Ошибка громкости: "+err.message;}}});
$("audioOutput").addEventListener("change", event => setAudioOutput(event.target.value));
$("refreshOutputs").addEventListener("click", refreshAudioOutputs);
$("audio").addEventListener("play", () => { $("browserPause").hidden = false; $("browserResume").hidden = true; $("browserStop").hidden = false; if (outputMode === "browser" && !timelineFrame) timelineFrame = requestAnimationFrame(updateBrowserTimeline); });
$("audio").addEventListener("timeupdate", () => { if (outputMode === "browser" && !timelineSeeking) renderBrowserTimeline(); });
$("audio").addEventListener("loadedmetadata", () => { const d = $("audio").duration; if (outputMode === "browser" && Number.isFinite(d) && d > 0) { browserTrackDuration = d; renderBrowserTimeline(); } });
$("audio").addEventListener("pause", () => { stopBrowserTimeline(); if (outputMode === "browser") { $("browserPause").hidden = true; $("browserResume").hidden = !$("audio").src || $("audio").ended; $("browserStop").hidden = !$("audio").src; renderBrowserTimeline(); } });
$("audio").addEventListener("ended", () => {
  stopBrowserTimeline();
  $("elapsedTime").textContent = formatDuration(browserTrackDuration);
  playNext();
});
$("audio").addEventListener("error", () => {
  stopBrowserTimeline();
  if ($("audio").src) $("libraryMessage").textContent = "VK не смог предоставить поток этого трека. Попробуйте другой трек или повторите позже.";
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