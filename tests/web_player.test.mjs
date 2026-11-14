import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(new URL("../app/web/package.json", import.meta.url));
const { JSDOM } = require("jsdom");

function jsonResponse(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      return data;
    },
  };
}

async function waitFor(predicate, description, timeoutMs = 2000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`Timed out waiting for ${description}`);
}

test("browser player loads, plays, seeks and switches to HAOS playback", async () => {
  const html = await readFile(new URL("../app/web/index.html", import.meta.url), "utf8");
  const appJs = await readFile(new URL("../app/web/app.js", import.meta.url), "utf8");
  const dom = new JSDOM(html, {
    url: "http://homeassistant.local/ingress/vk_music_server/",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  const calls = [];
  const serverZones = new Map();
  const track = {
    id: "123_456",
    title: "Regression Test Track",
    artist: "Test Artist",
    duration: 180,
  };

  const fakeFetch = async (input, options = {}) => {
    const url = new URL(String(input), window.document.baseURI);
    const path = url.pathname.split("/api/v1/").pop() || "";
    const method = options.method || "GET";
    calls.push({ path, method, body: options.body, outputDevice: url.searchParams.get("output_device") });

    if (path === "auth/status") {
      return jsonResponse({
        authenticated: true,
        state: "connected",
        user_id: "123",
        updated_at: "2026-11-12T00:00:00Z",
      });
    }
    if (path === "integration/info") {
      return jsonResponse({ available: false, base_url: null });
    }
    if (path.startsWith("library/tracks")) {
      return jsonResponse({ items: [track], limit: 50, offset: 0, has_more: false });
    }
    if (path.startsWith("playlists")) {
      return jsonResponse({ items: [], limit: 100, offset: 0, has_more: false });
    }
    if (path === "playback/outputs") {
      return jsonResponse({
        outputs: [
          { id: "default", name: "По умолчанию" },
          { id: "selected_sink", name: "Test speaker" },
        ],
        selected: "default",
        default_sink: "default_sink",
        device_count: 1,
        notice: "Test audio outputs",
      });
    }
    if (path === "playback/state") {
      const device = url.searchParams.get("output_device") || "default";
      return jsonResponse(serverZones.get(device) || {
        state: "idle", mode: "server", track: null, position: 0, output_device: device,
      });
    }
    if (path === "playback/states") {
      return jsonResponse({ zones: [...serverZones.values()] });
    }
    if (path === "playback/server/play") {
      const body = JSON.parse(options.body || "{}");
      const device = body.output_device || "default";
      const state = {
        state: "playing", mode: "server", track, position: 0,
        output: device === "default" ? "По умолчанию" : "Test speaker",
        output_device: device, volume: 0.8,
        equalizer: { bass: 0, low_mid: 0, mid: 0, high_mid: 0, treble: 0 },
      };
      serverZones.set(device, state);
      return jsonResponse(state);
    }
    if (path === "playback/server/seek") {
      const body = JSON.parse(options.body || "{}");
      const state = serverZones.get(body.output_device || "default");
      state.position = body.position;
      serverZones.set(body.output_device || "default", state);
      return jsonResponse(state);
    }
    if (path === "playback/server/equalizer") {
      const body = JSON.parse(options.body || "{}");
      const state = serverZones.get(body.output_device || "default");
      state.equalizer = Object.fromEntries(["bass", "low_mid", "mid", "high_mid", "treble"].map((band) => [band, body[band]]));
      serverZones.set(body.output_device || "default", state);
      return jsonResponse(state);
    }
    if (path === "playback/server/pause") {
      const device = url.searchParams.get("output_device") || "default";
      const state = serverZones.get(device);
      state.state = "paused";
      state.position = 10;
      return jsonResponse(state);
    }
    if (path === "playback/server/resume") {
      const device = url.searchParams.get("output_device") || "default";
      const state = serverZones.get(device);
      state.state = "playing";
      state.position = 10;
      return jsonResponse(state);
    }
    if (path === "playback/server/stop") {
      const device = url.searchParams.get("output_device") || "default";
      const state = serverZones.get(device) || {};
      state.state = "idle";
      state.track = null;
      state.position = 0;
      return jsonResponse(state);
    }
    if (path === "playback/output") {
      return jsonResponse({ selected: "selected_sink", name: "Test speaker" });
    }
    if (path === "playback/volume") {
      return jsonResponse({ volume: 0.5, output_device: "default" });
    }
    return jsonResponse({ detail: `Unexpected test request: ${method} ${path}` }, 404);
  };

  class TestWebSocket extends window.EventTarget {
    static CONNECTING = 0;
    static OPEN = 1;

    constructor(url) {
      super();
      this.url = String(url);
      this.readyState = TestWebSocket.OPEN;
    }

    close() {
      this.readyState = 3;
      this.dispatchEvent(new window.Event("close"));
    }
  }

  Object.assign(globalThis, {
    window,
    document: window.document,
    Event: window.Event,
    CustomEvent: window.CustomEvent,
    HTMLElement: window.HTMLElement,
    Element: window.Element,
    Node: window.Node,
    MutationObserver: window.MutationObserver,
    HTMLMediaElement: window.HTMLMediaElement,
    WebSocket: TestWebSocket,
    requestAnimationFrame: window.requestAnimationFrame.bind(window),
    cancelAnimationFrame: window.cancelAnimationFrame.bind(window),
    fetch: fakeFetch,
    confirm: () => true,
  });
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: window.navigator,
  });
  window.WebSocket = TestWebSocket;
  window.fetch = fakeFetch;

  const audio = window.document.getElementById("audio");
  let paused = true;
  let ended = false;
  let currentTime = 0;
  let readyState = 0;
  let playCount = 0;
  let audioSource = "";

  Object.defineProperties(audio, {
    paused: { configurable: true, get: () => paused },
    ended: { configurable: true, get: () => ended },
    src: {
      configurable: true,
      get: () => audioSource,
      set: (value) => {
        audioSource = String(value);
        currentTime = 0;
        readyState = 0;
      },
    },
    duration: {
      configurable: true,
      get: () => {
        const start = new URL(audioSource || window.document.baseURI, window.document.baseURI)
          .searchParams.get("start");
        return track.duration - (Number(start) || 0);
      },
    },
    currentTime: {
      configurable: true,
      get: () => currentTime,
      set: (value) => { currentTime = Number(value); },
    },
    readyState: { configurable: true, get: () => readyState },
  });
  audio.play = async () => {
    playCount += 1;
    paused = false;
    audio.dispatchEvent(new window.Event("play"));
  };
  audio.pause = () => {
    paused = true;
    audio.dispatchEvent(new window.Event("pause"));
  };
  audio.load = () => {
    readyState = window.HTMLMediaElement.HAVE_FUTURE_DATA;
    audio.dispatchEvent(new window.Event("loadedmetadata"));
    audio.dispatchEvent(new window.Event("canplay"));
  };

  try {
    // Loading the production bundle catches missing DOM references
    // during initialization, not just JavaScript syntax errors.
    await import("../app/web/app.bundle.js");

    await waitFor(
      () => window.document.querySelector("#trackList button"),
      "the connected library track",
    );
    assert.equal(window.document.getElementById("status").textContent.includes("VK подключён"), true);

    window.document.querySelector("#trackList button").click();
    await waitFor(
      () => window.document.getElementById("nowPlaying").textContent.includes(track.title),
      "browser player track title",
    );
    assert.equal(paused, false);
    const spectrum = window.document.getElementById("spectrumCanvas");
    assert.ok(spectrum, "player includes a spectrum visualizer");
    assert.equal(spectrum.dataset.bands, "12");
    assert.equal(spectrum.dataset.minFrequency, "50");
    assert.equal(spectrum.dataset.maxFrequency, "20000");
    assert.equal(spectrum.dataset.fftSize, "8192");
    assert.equal(spectrum.dataset.sensitivityDb, "0");
    assert.equal(spectrum.dataset.height, "87");
    assert.equal(spectrum.dataset.segments, "14");
    assert.ok(html.includes("#player{position:sticky;top:0"));
    assert.ok(html.includes("#player .playerButtons{margin-top:10px;flex-wrap:nowrap"));
    assert.equal(window.document.querySelectorAll("#player .playerButtons").length, 3);
    assert.ok(appJs.includes("spectrumAnalyser.fftSize = 8192"));
    assert.ok(appJs.includes("SPECTRUM_HIGH_SHELF_DB = 2"));
    assert.ok(appJs.includes("SPECTRUM_GAIN_DB = 0"));
    assert.ok(appJs.includes("const segmentCount = 14"));
    assert.ok(appJs.includes("segmentColors"));
    
    assert.equal(window.document.getElementById("outputStatus").textContent.includes("HLS"), false);
    assert.equal(window.document.getElementById("timelineSeek").disabled, false);

    const seek = window.document.getElementById("timelineSeek");
    seek.value = "30";
    seek.dispatchEvent(new window.Event("input", { bubbles: true }));
    seek.dispatchEvent(new window.Event("change", { bubbles: true }));
    await waitFor(() => audio.src.includes("start=30.000"), "seek stream URL");
    await waitFor(() => playCount >= 2 && paused === false, "browser playback after seek");

    // The replacement stream starts its local currentTime at zero and exposes
    // only the remaining media duration. The player timeline must stay absolute.
    assert.equal(seek.max, "180");
    currentTime = 5;
    audio.dispatchEvent(new window.Event("timeupdate"));
    assert.equal(seek.value, "35");
    assert.equal(window.document.getElementById("elapsedTime").textContent, "0:35");

    seek.value = "75";
    seek.dispatchEvent(new window.Event("input", { bubbles: true }));
    seek.dispatchEvent(new window.Event("change", { bubbles: true }));
    await waitFor(() => audio.src.includes("start=75.000"), "second seek uses absolute position");
    await waitFor(() => playCount >= 3 && paused === false, "browser playback after second seek");
    assert.equal(seek.max, "180");
    currentTime = 10;
    audio.dispatchEvent(new window.Event("timeupdate"));
    assert.equal(seek.value, "85");
    assert.equal(window.document.getElementById("elapsedTime").textContent, "1:25");

    window.document.getElementById("serverOutput").click();
    await waitFor(
      () => calls.some((call) => call.path === "playback/state"),
      "server playback state",
    );
    assert.equal(window.document.getElementById("browserTimeline").hidden, true);
    assert.equal(window.document.getElementById("serverTimeline").hidden, false);
    assert.equal(window.document.getElementById("serverEqualizer").hidden, false);
    assert.equal(window.document.getElementById("spectrumCanvas").hidden, true);
    assert.equal(window.getComputedStyle(window.document.getElementById("spectrumCanvas")).display, "none",
      "the spectrum canvas must be visually hidden in HAOS mode");
    assert.equal(window.document.getElementById("browserControls").hidden, true);
    assert.equal(window.document.getElementById("serverControls").hidden, false);
    assert.equal(window.document.getElementById("transportControls").hidden, false);
    assert.equal(window.document.getElementById("player").contains(window.document.getElementById("zoneSettings")), false,
      "expanded zone settings must never enlarge the sticky player");
    assert.equal(window.document.getElementById("player").contains(window.document.getElementById("serverEqualizer")), false,
      "equalizer must stay outside the sticky player");
    assert.equal(window.document.getElementById("zoneSettings").open, false,
      "zone settings start collapsed");
    assert.equal(paused, false, "switching to HAOS must not stop the browser stream");
    assert.ok(audio.src.includes("start=75.000"), "browser source URL must stay attached");
    assert.equal(calls.some((call) => call.path === "playback/server/stop"), false);

    window.document.querySelector("#trackList button").click();
    await waitFor(
      () => calls.some((call) => call.path === "playback/server/play")
        && !window.document.getElementById("serverPause").hidden,
      "HAOS server playback request and updated controls",
    );
    assert.equal(window.document.getElementById("serverPause").hidden, false);
    assert.equal(window.document.getElementById("nowPlaying").textContent.includes(track.title), true);
    assert.equal(paused, false, "HAOS playback and browser playback may run simultaneously");

    const serverSeek = window.document.getElementById("serverTimelineSeek");
    serverSeek.value = "45";
    serverSeek.dispatchEvent(new window.Event("input", { bubbles: true }));
    serverSeek.dispatchEvent(new window.Event("change", { bubbles: true }));
    await waitFor(
      () => calls.some((call) => call.path === "playback/server/seek"),
      "HAOS seek request",
    );
    assert.equal(JSON.parse(calls.findLast((call) => call.path === "playback/server/seek").body).position, 45);

    const bass = window.document.getElementById("eq_bass");
    bass.value = "5";
    bass.dispatchEvent(new window.Event("change", { bubbles: true }));
    await waitFor(
      () => calls.some((call) => call.path === "playback/server/equalizer"),
      "HAOS equalizer request",
    );
    assert.equal(JSON.parse(calls.findLast((call) => call.path === "playback/server/equalizer").body).bass, 5);

    const output = window.document.getElementById("audioOutput");
    const zoneRefreshesBeforeSelect = calls.filter((call) => call.path === "playback/states").length;
    output.value = "selected_sink";
    output.dispatchEvent(new window.Event("change", { bubbles: true }));
    await waitFor(
      () => calls.some((call) => call.path === "playback/state" && call.outputDevice === "selected_sink"),
      "selected HAOS zone state",
    );
    await waitFor(
      () => calls.filter((call) => call.path === "playback/states").length > zoneRefreshesBeforeSelect,
      "selected zone panel refresh",
    );
    const zoneRefreshesBeforeSecondPlay = calls.filter((call) => call.path === "playback/states").length;
    window.document.querySelector("#trackList button").click();
    await waitFor(
      () => serverZones.has("selected_sink"),
      "second HAOS playback zone",
    );
    await waitFor(
      () => calls.filter((call) => call.path === "playback/states").length > zoneRefreshesBeforeSecondPlay,
      "second zone panel refresh",
    );
    assert.equal(serverZones.has("default"), true, "first HAOS zone remains active");
    assert.equal(serverZones.get("default").state, "playing");
    assert.equal(paused, false, "switching outputs must not stop browser playback");
    assert.ok(appJs.includes("playback/server/seek"));
    assert.ok(appJs.includes("playback/server/equalizer"));
  } finally {
    dom.window.close();
  }
});
