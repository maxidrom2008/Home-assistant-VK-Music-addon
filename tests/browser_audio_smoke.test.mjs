import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { test } from "node:test";
import { once } from "node:events";

const require = createRequire(new URL("../app/web/package.json", import.meta.url));
const { chromium } = require("playwright");

function makeWave(seconds = 8, frequency = 440, sampleRate = 48000) {
  const samples = Math.floor(seconds * sampleRate);
  const dataBytes = samples * 2;
  const wav = Buffer.alloc(44 + dataBytes);
  wav.write("RIFF", 0);
  wav.writeUInt32LE(36 + dataBytes, 4);
  wav.write("WAVE", 8);
  wav.write("fmt ", 12);
  wav.writeUInt32LE(16, 16);
  wav.writeUInt16LE(1, 20); // PCM
  wav.writeUInt16LE(1, 22); // mono
  wav.writeUInt32LE(sampleRate, 24);
  wav.writeUInt32LE(sampleRate * 2, 28);
  wav.writeUInt16LE(2, 32);
  wav.writeUInt16LE(16, 34);
  wav.write("data", 36);
  wav.writeUInt32LE(dataBytes, 40);
  for (let i = 0; i < samples; i += 1) {
    const value = Math.round(7000 * Math.sin(2 * Math.PI * frequency * i / sampleRate));
    wav.writeInt16LE(value, 44 + i * 2);
  }
  return wav;
}

function sendJson(response, status, value) {
  const body = Buffer.from(JSON.stringify(value));
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": body.length,
    "cache-control": "no-store",
  });
  response.end(body);
}

test("production browser player keeps decoded audio audible when Web Audio is suspended", { timeout: 45000 }, async () => {
  const html = await readFile(new URL("../app/web/index.html", import.meta.url));
  const bundle = await readFile(new URL("../app/web/app.bundle.js", import.meta.url));
  const wav = makeWave();
  const track = {
    id: "123_456",
    title: "Chromium Audio Smoke Test",
    artist: "VK Music CI",
    duration: 8,
  };
  const requests = [];
  const server = createServer((request, response) => {
    const url = new URL(request.url || "/", "http://127.0.0.1");
    requests.push({ method: request.method, path: url.pathname });

    if (request.method === "GET" && url.pathname === "/") {
      response.writeHead(200, {
        "content-type": "text/html; charset=utf-8",
        "content-length": html.length,
        "cache-control": "no-store",
      });
      response.end(html);
      return;
    }
    if (request.method === "GET" && url.pathname === "/app.js") {
      response.writeHead(200, {
        "content-type": "text/javascript; charset=utf-8",
        "content-length": bundle.length,
        "cache-control": "no-store",
      });
      response.end(bundle);
      return;
    }
    if (request.method === "GET" && url.pathname === "/api/v1/auth/status") {
      sendJson(response, 200, {
        authenticated: true,
        state: "connected",
        user_id: "ci-test",
        updated_at: "2026-11-14T00:00:00Z",
      });
      return;
    }
    if (request.method === "GET" && url.pathname === "/api/v1/integration/info") {
      sendJson(response, 200, { available: false, base_url: null });
      return;
    }
    if (request.method === "GET" && url.pathname === "/api/v1/library/tracks") {
      sendJson(response, 200, {
        items: [track],
        limit: 50,
        offset: 0,
        has_more: false,
      });
      return;
    }
    if (request.method === "POST" && url.pathname === "/api/v1/tracks/123_456/hls") {
      // Force the production player to exercise its FFmpeg-compatible legacy
      // stream fallback. The fallback response below is a real PCM WAV file.
      sendJson(response, 503, { detail: "HLS disabled in the smoke test" });
      return;
    }
    if (request.method === "GET" && url.pathname === "/api/v1/tracks/123_456/stream") {
      response.writeHead(200, {
        "content-type": "audio/wav",
        "content-length": wav.length,
        "cache-control": "no-store",
        "accept-ranges": "none",
      });
      response.end(wav);
      return;
    }

    sendJson(response, 404, { detail: "Unexpected smoke-test request: " + request.method + " " + url.pathname });
  });
  server.on("upgrade", (_request, socket) => socket.destroy());
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  const baseUrl = "http://127.0.0.1:" + address.port;

  let browser;
  try {
    browser = await chromium.launch({
      headless: true,
      args: ["--autoplay-policy=no-user-gesture-required", "--no-sandbox"],
    });
    const page = await browser.newPage();
    await page.addInitScript(() => {
      const NativeAudioContext = window.AudioContext;
      window.__audioSmoke = { mediaElementSourceCalls: 0, resumeCalls: 0 };
      if (NativeAudioContext) {
        window.AudioContext = class extends NativeAudioContext {
          constructor(...args) {
            super(...args);
            // Force the exact browser state that used to silence native media.
            Object.defineProperty(this, "state", {
              configurable: true,
              get: () => "suspended",
            });
          }
          createMediaElementSource(...args) {
            window.__audioSmoke.mediaElementSourceCalls += 1;
            return super.createMediaElementSource(...args);
          }
          resume() {
            window.__audioSmoke.resumeCalls += 1;
            return Promise.reject(new Error("Simulated autoplay policy blocks the optional analyser"));
          }
        };
      }
    });

    const pageErrors = [];
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.waitForSelector("#trackList button", { timeout: 10000 });
    await page.locator("#trackList button").click();

    await page.waitForFunction(() => {
      const audio = document.getElementById("audio");
      return audio && !audio.paused && audio.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA
        && audio.currentTime >= 1;
    }, null, { timeout: 15000 });

    const recorderResult = await page.evaluate(async () => {
      const audio = document.getElementById("audio");
      const stream = audio.captureStream();
      const tracks = stream.getAudioTracks();
      if (!tracks.length) throw new Error("The real media element exposed no captured audio track");
      if (typeof MediaRecorder === "undefined") throw new Error("MediaRecorder is unavailable in Chromium");
      const recorder = new MediaRecorder(stream);
      const chunks = [];
      recorder.ondataavailable = event => {
        if (event.data && event.data.size) chunks.push(event.data);
      };
      const stopped = new Promise((resolve, reject) => {
        recorder.onstop = resolve;
        recorder.onerror = event => reject(event.error || new Error("MediaRecorder failed"));
      });
      recorder.start(100);
      await new Promise(resolve => setTimeout(resolve, 900));
      recorder.stop();
      await stopped;
      return {
        trackCount: tracks.length,
        recordedBytes: chunks.reduce((sum, chunk) => sum + chunk.size, 0),
        currentTime: audio.currentTime,
        paused: audio.paused,
        volume: audio.volume,
        muted: audio.muted,
        visualizerHidden: document.getElementById("spectrumCanvas").hidden,
        mediaElementSourceCalls: window.__audioSmoke.mediaElementSourceCalls,
        resumeCalls: window.__audioSmoke.resumeCalls,
      };
    });

    assert.ok(recorderResult.trackCount > 0, "audio element must expose a decoded audio track");
    assert.ok(recorderResult.recordedBytes > 1000, "Chromium must record non-empty decoded audio samples");
    assert.ok(recorderResult.currentTime >= 1.5, "the native audio timeline must continue advancing");
    assert.equal(recorderResult.paused, false, "the browser media element must keep playing");
    assert.equal(recorderResult.volume, 0.8, "native browser volume must remain at its configured level");
    assert.equal(recorderResult.muted, false, "native browser media must not be muted");
    assert.equal(recorderResult.visualizerHidden, true,
      "a blocked analyser is hidden without muting the media element");
    assert.equal(recorderResult.mediaElementSourceCalls, 0,
      "the production player must not hijack the native media output route");
    assert.ok(recorderResult.resumeCalls >= 1, "the test must exercise a rejected AudioContext.resume()");
    assert.ok(requests.some(item => item.path === "/api/v1/tracks/123_456/stream"),
      "production player must use the real browser-stream fallback");
    assert.deepEqual(pageErrors, [], "production browser bundle must not raise uncaught page errors");
  } finally {
    if (browser) await browser.close();
    server.close();
    await once(server, "close");
  }
});
