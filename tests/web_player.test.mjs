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
    calls.push({ path, method, body: options.body });

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
      return jsonResponse({ state: "idle", mode: "server", track: null, position: 0 });
    }
    if (path === "playback/server/play") {
      return jsonResponse({
        state: "playing",
        mode: "server",
        track,
        position: 0,
        output: "Test speaker",
      });
    }
    if (path === "playback/server/pause") {
      return jsonResponse({ state: "paused", mode: "server", track, position: 10 });
    }
    if (path === "playback/server/resume") {
      return jsonResponse({ state: "playing", mode: "server", track, position: 10 });
    }
    if (path === "playback/server/stop") {
      return jsonResponse({ state: "idle", mode: "server", track: null, position: 0 });
    }
    if (path === "playback/output") {
      return jsonResponse({ selected: "selected_sink", name: "Test speaker" });
    }
    if (path === "playback/volume") {
      return jsonResponse({ volume: 0.5 });
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
    assert.equal(spectrum.dataset.sensitivityDb, "10");
    assert.match(html, /#player\\{position:sticky;top:0/);
    assert.match(html, /#player \.playerButtons\\{[^}]*flex-wrap:nowrap/);
    assert.equal(window.document.querySelectorAll("#player .playerButtons").length, 1);
    assert.match(appJs, /spectrumAnalyser\\.fftSize = 8192/);
    assert.match(appJs, /SPECTRUM_HIGH_SHELF_DB = 4/);
    assert.match(appJs, /SPECTRUM_GAIN_DB = 10/);
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

    window.document.querySelector("#trackList button").click();
    await waitFor(
      () => calls.some((call) => call.path === "playback/server/play")
        && !window.document.getElementById("serverPause").hidden,
      "HAOS server playback request and updated controls",
    );
    assert.equal(window.document.getElementById("serverPause").hidden, false);
    assert.equal(window.document.getElementById("nowPlaying").textContent.includes(track.title), true);
  } finally {
    dom.window.close();
  }
});
