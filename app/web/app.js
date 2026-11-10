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
    if (s.authenticated) {
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
  $("nowPlaying").textContent = (track.artist ? track.artist + " — " : "") + (track.title || "Без названия");
  if (outputMode === "server") {
    $("audio").pause();
    $("audio").removeAttribute("src");
    try {
      const state = await call("playback/server/play", {
        method:"POST",
        body:JSON.stringify({track_id:track.id})
      });
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
  audio.src = api("tracks/" + encodeURIComponent(track.id) + "/stream");
  try {
    await audio.play();
    $("outputStatus").textContent = "Воспроизведение в этом браузере";
  } catch (err) {
    $("libraryMessage").textContent = "Не удалось начать воспроизведение: " + (err.message || String(err));
  }
}
async function setOutputMode(mode) {
  outputMode = mode;
  $("browserOutput").className = mode === "browser" ? "" : "secondary";
  $("serverOutput").className = mode === "server" ? "" : "secondary";
  $("audio").hidden = mode === "server";
  $("serverPause").hidden = mode !== "server";
  $("serverResume").hidden = mode !== "server";
  $("serverStop").hidden = mode !== "server";
  if (mode === "server") {
    $("audio").pause();
    $("outputStatus").textContent = "Следующий выбранный трек будет играть через аудиовыход HAOS.";
    try {
      const state = await call("playback/state");
      if (state.state === "error") $("outputStatus").textContent = state.error || "Ошибка серверного вывода.";
      else if (state.track) $("nowPlaying").textContent = (state.track.artist ? state.track.artist + " — " : "") + state.track.title;
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
    $("message").textContent = "Не удалось загрузить виджет VK CAPTCHA: " + (err.message || String(err)) + ". Проверьте доступ браузера к esm.sh и обновите ссылку CAPTCHA.";
  }
}
async function submitChallenge() {
  if (!challengeId) return;
  let answer = "";
  if (challengeType === "browser_captcha") {
    if (!captchaWidget) {
      $("message").textContent = "Виджет CAPTCHA ещё не загружен. Обновите ссылку или разрешите загрузку внешнего скрипта.";
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
$("audio").addEventListener("ended", playNext);
$("audio").addEventListener("error", () => {
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
refreshStatus();