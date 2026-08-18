const app = document.getElementById("app");
const audio = document.getElementById("player");

const state = {
  authed: false,
  needsAuth: false,
  tab: "home",
  view: "home",
  home: { continue: null, listening: [], recent: [], finished: [] },
  books: [],
  book: null,
  chapter: null,
  cues: [],
  bookmarks: [],
  voices: [],
  files: [],
  title: "",
  author: "",
  voice: "",
  query: "",
  filter: "all",
  password: "",
  error: "",
  toast: "",
  sheet: null,
  carMode: false,
  fontSize: Number(localStorage.getItem("la-font") || 1.28),
  speed: Number(localStorage.getItem("la-speed") || 1),
  skip: Number(localStorage.getItem("la-skip") || 30),
  sleepUntil: 0,
  sleepChapter: false,
  poll: null,
  stream: null,
  installEvent: null,
  stats: { today_seconds: 0, total_seconds: 0, finished: 0, titles: 0, streak: 0 },
  boost: Number(localStorage.getItem("la-boost") || 1),
  layout: localStorage.getItem("la-layout") || "grid",
  queue: JSON.parse(localStorage.getItem("la-queue") || "[]"),
  downloaded: JSON.parse(localStorage.getItem("la-dl") || "[]"),
  findQuery: "",
  searchHits: { books: [], passages: [] },
  keepAwake: localStorage.getItem("la-wake") !== "0",
  haptics: localStorage.getItem("la-haptics") !== "0",
};
let lastTick = Date.now();
let audioCtx = null;
let gainNode = null;
let mediaSource = null;
let wakeLock = null;

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  state.installEvent = event;
  render();
});

const svg = (d) => {
  const wrap = document.createElement("span");
  wrap.innerHTML = `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
  return wrap.firstChild;
};

function h(tag, attrs = {}, kids = []) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") el.className = value;
    else if (key === "style" && value) el.setAttribute("style", value);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (value === false || value == null) continue;
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  for (const kid of [].concat(kids)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(kid));
  }
  return el;
}

function coverStyle(book, extra = "") {
  const hue = book.cover_hue ?? 18;
  return `background: linear-gradient(160deg, hsl(${hue} 70% 38%), hsl(${(hue + 28) % 360} 40% 12%));${extra}`;
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds)) return "0:00";
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  const hrs = Math.floor(m / 60);
  if (hrs) return `${hrs}:${String(m % 60).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
  return `${m}:${String(r).padStart(2, "0")}`;
}

function formatLeft(seconds, speed = 1) {
  const adj = seconds / (speed || 1);
  if (!adj || adj < 1) return "0 min left";
  const m = Math.round(adj / 60);
  if (m < 60) return `${m} min left`;
  const h = Math.floor(m / 60);
  return `${h} hr ${m % 60} min left`;
}

function formatLength(seconds) {
  if (!seconds) return "Narrating";
  const m = Math.round(seconds / 60);
  if (seconds < 60) return `${Math.round(seconds)} sec`;
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} hr ${m % 60} min`;
}

function greeting() {
  const hour = new Date().getHours();
  if (hour < 5) return "Good night";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function toast(message) {
  state.toast = message;
  render();
  setTimeout(() => {
    if (state.toast === message) {
      state.toast = "";
      render();
    }
  }, 2200);
}

function buzz() {
  if (state.haptics && navigator.vibrate) navigator.vibrate(12);
}

function downloaded(id) {
  return state.downloaded.includes(id);
}

function saveQueue() {
  localStorage.setItem("la-queue", JSON.stringify(state.queue));
}

function ensureGraph() {
  if (mediaSource || !window.AudioContext) return;
  audioCtx = new AudioContext();
  mediaSource = audioCtx.createMediaElementSource(audio);
  gainNode = audioCtx.createGain();
  gainNode.gain.value = state.boost;
  mediaSource.connect(gainNode).connect(audioCtx.destination);
}

async function setWake(on) {
  try {
    if (on && state.keepAwake && "wakeLock" in navigator) wakeLock = await navigator.wakeLock.request("screen");
    else if (wakeLock) { await wakeLock.release(); wakeLock = null; }
  } catch { /* ignore */ }
}
  state.toast = message;
  render();
  setTimeout(() => {
    if (state.toast === message) {
      state.toast = "";
      render();
    }
  }, 2200);
}

async function api(path, options) {
  const res = await fetch(path, options);
  if (res.status === 401 && path !== "/api/me" && path !== "/api/login") {
    state.authed = false;
    state.needsAuth = true;
    state.view = "login";
    render();
    throw new Error("Sign in required");
  }
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = body.detail || message;
    } catch {
      try { message = await res.text(); } catch { /* ignore */ }
    }
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

function watchBook(id) {
  if (state.stream) state.stream.close();
  if (!window.EventSource) return;
  state.stream = new EventSource(`/api/books/${id}/stream`);
  state.stream.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (state.book && state.book.id === id) {
      state.book.status = payload.status;
      state.book.ready_chapters = payload.ready_chapters;
      payload.chapters.forEach((live) => {
        const chapter = state.book.chapters.find((c) => c.id === live.id);
        if (chapter) Object.assign(chapter, live);
      });
      render();
    }
    refresh(false);
    if (payload.status === "ready" || payload.status === "error") state.stream.close();
  };
}

async function refresh(shouldRender = true) {
  const [home, books] = await Promise.all([api("/api/home"), api(`/api/books?q=${encodeURIComponent(state.query)}`)]);
  state.home = home;
  state.books = books;
  if (shouldRender && ["home", "library", "title"].includes(state.view)) render();
  const busy = books.some((b) => b.status === "processing");
  if (busy && !state.poll) state.poll = setInterval(() => refresh(true), 4000);
  if (!busy && state.poll) {
    clearInterval(state.poll);
    state.poll = null;
  }
}

async function openBook(id) {
  state.book = await api(`/api/books/${id}`);
  state.bookmarks = await api(`/api/books/${id}/bookmarks`);
  state.view = "title";
  state.tab = "library";
  if (state.book.status === "processing") watchBook(id);
  render();
}

function resumeChapter(book) {
  if (!book) return null;
  const chapters = book.chapters || [];
  return chapters[book.progress_chapter] || chapters.find((c) => c.status === "ready");
}

async function playChapter(book, chapter, time = 0, intoPlayer = true) {
  if (!chapter || chapter.status !== "ready") {
    toast("That chapter isn’t ready yet");
    return;
  }
  if (!state.book || state.book.id !== book.id) state.book = await api(`/api/books/${book.id}`);
  const full = await api(`/api/books/${book.id}/chapters/${chapter.id}`);
  state.chapter = full;
  state.cues = full.cues || [];
  audio.src = `/api/books/${book.id}/chapters/${chapter.id}/audio`;
  audio.playbackRate = state.speed;
  const startAt = Math.max(0, time - (time > 2 ? 2 : 0));
  const go = async () => {
    try { audio.currentTime = startAt; } catch { /* ignore */ }
    ensureGraph();
    if (audioCtx && audioCtx.state === "suspended") audioCtx.resume();
    if (gainNode) gainNode.gain.value = state.boost;
    setupMediaSession();
    prefetchNext();
    cacheAudio(audio.src);
    buzz();
    setWake(true);
    if (intoPlayer) state.view = "player";
    render();
  };
  try {
    await audio.play();
  } catch { /* user gesture fallback */ }
  if (audio.readyState >= 1) await go();
  else audio.onloadedmetadata = go;
}

function currentChapterIndex() {
  if (!state.book || !state.chapter) return 0;
  return state.book.chapters.findIndex((c) => c.id === state.chapter.id);
}

async function skipChapter(delta) {
  if (!state.book) return;
  const next = state.book.chapters[currentChapterIndex() + delta];
  if (next && next.status === "ready") await playChapter(state.book, next, 0, state.view === "player" || state.carMode);
  else if (delta > 0) toast("End of title");
}

function setupMediaSession() {
  if (!("mediaSession" in navigator) || !state.book || !state.chapter) return;
  navigator.mediaSession.metadata = new MediaMetadata({
    title: state.chapter.title,
    artist: state.book.title,
    album: `Narrated by ${state.book.narrator || "ListenAlong"}`,
    artwork: [{ src: "/static/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
  });
  const skip = () => state.skip;
  navigator.mediaSession.setActionHandler("play", () => audio.play());
  navigator.mediaSession.setActionHandler("pause", () => audio.pause());
  navigator.mediaSession.setActionHandler("previoustrack", () => skipChapter(-1));
  navigator.mediaSession.setActionHandler("nexttrack", () => skipChapter(1));
  navigator.mediaSession.setActionHandler("seekbackward", () => { audio.currentTime -= skip(); });
  navigator.mediaSession.setActionHandler("seekforward", () => { audio.currentTime += skip(); });
  navigator.mediaSession.setActionHandler("seekto", (e) => {
    if (typeof e.seekTime === "number") audio.currentTime = e.seekTime;
  });
}

function saveProgress() {
  if (!state.book || !state.chapter) return;
  const now = Date.now();
  const listened = audio.paused ? 0 : Math.min(15, (now - lastTick) / 1000) * state.speed;
  lastTick = now;
  fetch(`/api/books/${state.book.id}/progress`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chapter_idx: Math.max(0, currentChapterIndex()),
      time: audio.currentTime || 0,
      listened,
    }),
  }).catch(() => {});
}

function prefetchNext() {
  if (!state.book) return;
  const next = state.book.chapters[currentChapterIndex() + 1];
  if (next && next.status === "ready") cacheAudio(`/api/books/${state.book.id}/chapters/${next.id}/audio`);
}

function cacheAudio(url) {
  if (!("caches" in window)) return;
  caches.open("listenalong-v5").then((cache) => cache.add(url).catch(() => {}));
}

async function downloadBook(book) {
  const ready = (book.chapters || []).filter((ch) => ch.status === "ready");
  for (const chapter of ready) cacheAudio(`/api/books/${book.id}/chapters/${chapter.id}/audio`);
  if (!downloaded(book.id)) {
    state.downloaded.push(book.id);
    localStorage.setItem("la-dl", JSON.stringify(state.downloaded));
  }
  toast(`Downloaded ${ready.length} chapters`);
}

function remainingNow() {
  if (!state.book || !state.chapter) return 0;
  const idx = currentChapterIndex();
  let left = Math.max(0, (state.chapter.duration || 0) - (audio.currentTime || 0));
  for (const chapter of state.book.chapters) {
    if (chapter.idx > idx) left += chapter.duration || 0;
  }
  return left;
}

function highlight() {
  const t = audio.currentTime;
  const words = document.querySelectorAll(".reader .word");
  let active = null;
  for (const word of words) {
    const on = t >= Number(word.dataset.start) && t < Number(word.dataset.end) + 0.08;
    word.classList.toggle("active", on);
    if (on) active = word;
  }
  document.querySelectorAll(".sentence").forEach((s) => s.classList.remove("active"));
  if (active) {
    const sentence = active.closest(".sentence");
    if (sentence) {
      sentence.classList.add("active");
      const rect = active.getBoundingClientRect();
      if (rect.top < 90 || rect.bottom > window.innerHeight - 160) {
        active.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    }
  }
}

function readerText(text, cues) {
  if (!cues.length) return h("div", { class: "reader", style: `--read-size:${state.fontSize}rem` }, text);
  const wrap = h("div", { class: "reader", style: `--read-size:${state.fontSize}rem` });
  let cursor = 0;
  let sentence = h("span", { class: "sentence" });
  wrap.append(sentence);
  for (const cue of cues) {
    const start = Math.max(cursor, cue.charStart);
    const end = Math.max(start, cue.charEnd);
    if (start > cursor) sentence.append(text.slice(cursor, start));
    sentence.append(h("span", {
      class: "word",
      "data-start": cue.start,
      "data-end": cue.end,
      onclick: () => { audio.currentTime = cue.start; highlight(); },
    }, text.slice(start, end) || cue.text));
    cursor = end;
    if (/[.!?]/.test(cue.text)) {
      sentence = h("span", { class: "sentence" });
      wrap.append(sentence);
    }
  }
  if (cursor < text.length) sentence.append(text.slice(cursor));
  return wrap;
}

async function importBooks(event) {
  event.preventDefault();
  if (!state.files.length) {
    state.error = "Choose a document, zip, or folder first.";
    render();
    return;
  }
  const data = new FormData();
  data.append("title", state.title);
  data.append("author", state.author);
  data.append("voice", state.voice || (state.voices[0] && state.voices[0].short_name) || "");
  for (const file of state.files) data.append("files", file);
  state.error = "";
  try {
    const book = await api("/api/books", { method: "POST", body: data });
    toast("Starting narration");
    await refresh(false);
    await openBook(book.id);
  } catch (err) {
    state.error = err.message;
    render();
  }
}

async function bookmarkHere() {
  if (!state.book || !state.chapter) return;
  const note = prompt("Bookmark note", state.chapter.title) || state.chapter.title;
  await api(`/api/books/${state.book.id}/bookmarks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chapter_id: state.chapter.id, time: audio.currentTime || 0, note }),
  });
  state.bookmarks = await api(`/api/books/${state.book.id}/bookmarks`);
  toast("Bookmark saved");
}

function coverEl(book, extraClass = "") {
  return h("div", { class: `cover ${extraClass}` }, [
    h("img", { src: `/api/books/${book.id}/cover`, alt: book.title, loading: "lazy" }),
    downloaded(book.id) ? h("span", { class: "dl-badge" }, "Saved") : null,
  ]);
}

function tile(book) {
  return h("button", { class: "tile", onclick: () => openBook(book.id) }, [
    coverEl(book),
    h("div", { class: "meta" }, [
      h("strong", {}, book.title),
      h("span", {}, book.finished ? "Finished" : formatLeft(book.remaining || 0, state.speed)),
    ]),
  ]);
}

function rail(label, books) {
  if (!books || !books.length) return null;
  return h("section", {}, [
    h("div", { class: "rail-head" }, h("h2", {}, label)),
    h("div", { class: "rail" }, books.map(tile)),
  ]);
}

function nav() {
  if (["login", "player", "immersion"].includes(state.view) || state.carMode) return null;
  const item = (id, label, path) => h("button", {
    class: state.tab === id ? "on" : "",
    onclick: () => { state.tab = id; state.view = id; render(); },
  }, [svg(path), label]);
  return h("nav", { class: "nav" }, [
    item("home", "Home", '<path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-7H10v7H5a1 1 0 0 1-1-1z"/>'),
    item("library", "Library", '<rect x="4" y="5" width="6" height="14" rx="1"/><rect x="14" y="5" width="6" height="14" rx="1"/>'),
    item("add", "Add", '<circle cx="12" cy="12" r="8"/><path d="M12 8v8M8 12h8"/>'),
    item("you", "You", '<circle cx="12" cy="8" r="3"/><path d="M5 19c1.5-3 4-5 7-5s5.5 2 7 5"/>'),
  ]);
}

function mini() {
  if (!state.chapter || ["login", "player", "immersion"].includes(state.view) || state.carMode) return null;
  return h("div", { class: "mini", onclick: () => { state.view = "player"; render(); } }, [
    h("div", { class: "cover sq", style: coverStyle(state.book, "width:46px;height:46px;aspect-ratio:1") }),
    h("div", {}, [h("strong", {}, state.book.title), h("small", {}, state.chapter.title)]),
    h("button", {
      class: "play-fab",
      style: "width:40px;height:40px",
      onclick: (e) => { e.stopPropagation(); togglePlay(); },
    }, audio.paused ? "▶" : "❚❚"),
  ]);
}

function togglePlay() {
  ensureGraph();
  if (audio.paused) {
    if (audioCtx && audioCtx.state === "suspended") audioCtx.resume();
    audio.play();
    setWake(true);
  } else {
    audio.pause();
    setWake(false);
  }
  syncPlayButtons();
}

function playerView() {
  if (!state.book || !state.chapter) return homeView();
  const idx = currentChapterIndex();
  const remaining = remainingNow();
  return h("div", {
    class: "player",
    ontouchstart: (e) => { state._swipeY = e.changedTouches[0].clientY; },
    ontouchend: (e) => {
      if ((e.changedTouches[0].clientY - (state._swipeY || 0)) > 90) {
        state.view = "title";
        state.tab = "library";
        render();
      }
    },
  }, [
    h("div", { class: "bar" }, [
      h("button", { class: "icon-btn", onclick: () => { state.view = "title"; state.tab = "library"; render(); } }, svg('<path d="M6 9l6 6 6-6"/>')),
      h("span", { class: "muted" }, "Now playing"),
      h("button", { class: "icon-btn", onclick: () => { state.sheet = "more"; render(); } }, svg('<circle cx="6" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="18" cy="12" r="1.3"/>')),
    ]),
    coverEl(state.book, "lg"),
    h("div", { class: "player-copy" }, [
      h("h1", {}, state.book.title),
      h("p", {}, `${state.book.author || "Unknown"} · Narrated by ${state.book.narrator}`),
      h("div", { class: "chapter-line" }, `Chapter ${idx + 1} of ${state.book.chapter_count}  ·  ${state.chapter.title}`),
    ]),
    h("input", {
      class: "seek",
      type: "range",
      min: 0,
      max: Math.max(state.chapter.duration || 1, 1),
      step: 0.1,
      value: audio.currentTime || 0,
      oninput: (e) => { audio.currentTime = Number(e.target.value); highlight(); },
    }),
    h("div", { class: "times" }, [
      h("span", {}, formatTime(audio.currentTime)),
      h("span", { class: "left-label" }, formatLeft(remaining, state.speed)),
    ]),
    h("div", { class: "transport" }, [
      h("button", { class: "skip", onclick: () => { audio.currentTime -= state.skip; } }, `−${state.skip}`),
      h("button", { class: "play-fab xl", onclick: togglePlay }, audio.paused ? "▶" : "❚❚"),
      h("button", { class: "skip", onclick: () => { audio.currentTime += state.skip; } }, `+${state.skip}`),
    ]),
    h("div", { class: "tools" }, [
      h("button", { onclick: () => { state.sheet = "speed"; render(); } }, [svg('<path d="M4 12h16M12 6v12"/>'), `${state.speed}x`]),
      h("button", { onclick: () => { state.sheet = "sleep"; render(); } }, [svg('<path d="M12 7v5l3 2"/><circle cx="12" cy="12" r="8"/>'), "Sleep"]),
      h("button", { onclick: bookmarkHere }, [svg('<path d="M7 4h10v16l-5-3-5 3z"/>'), "Bookmark"]),
      h("button", { onclick: () => { state.sheet = "chapters"; render(); } }, [svg('<path d="M5 7h14M5 12h14M5 17h10"/>'), "Chapters"]),
      h("button", { onclick: () => { state.sheet = "find"; render(); } }, [svg('<circle cx="11" cy="11" r="6"/><path d="M20 20l-3-3"/>'), "Find"]),
      h("button", { onclick: () => { state.view = "immersion"; render(); } }, [svg('<path d="M5 5h14v14H5z"/><path d="M8 9h8M8 12h6"/>'), "Immersion"]),
    ]),
  ]);
}

function sheet() {
  if (!state.sheet) return null;
  const close = () => { state.sheet = null; render(); };
  const panel = (title, body) => h("div", { class: "sheet" }, [
    h("div", { class: "grab" }),
    h("div", { class: "bar" }, [h("strong", {}, title), h("button", { class: "muted", onclick: close }, "Close")]),
    body,
  ]);
  if (state.sheet === "chapters" && state.book) {
    return panel("Chapters", state.book.chapters.map((ch, i) => h("button", {
      class: "row",
      onclick: async () => { state.sheet = null; if (ch.status === "ready") await playChapter(state.book, ch, 0, true); },
    }, [
      h("div", {}, [h("strong", {}, `${i + 1}. ${ch.title}`), h("div", { class: "muted" }, ch.status === "ready" ? formatLength(ch.duration) : ch.status)]),
      state.chapter && state.chapter.id === ch.id ? h("span", { class: "now" }, "Playing") : null,
    ])));
  }
  if (state.sheet === "speed") {
    const speeds = [0.5, 0.7, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3, 3.5];
    return panel("Narration speed", h("div", { class: "chips", style: "flex-wrap:wrap" }, speeds.map((s) => h("button", {
      class: `chip ${s === state.speed ? "on" : ""}`,
      onclick: () => {
        state.speed = s;
        audio.playbackRate = s;
        localStorage.setItem("la-speed", String(s));
        state.sheet = null;
        render();
      },
    }, `${s}x`))));
  }
  if (state.sheet === "sleep") {
    const opts = [0, 5, 15, 30, 45, 60, 90];
    return panel("Sleep timer", [
      ...opts.map((mins) => h("button", {
        class: "row",
        onclick: () => {
          state.sleepChapter = false;
          state.sleepUntil = mins ? Date.now() + mins * 60 * 1000 : 0;
          state.sheet = null;
          render();
          if (mins) toast(`Sleep in ${mins} min`);
        },
      }, mins ? `${mins} minutes` : "Off")),
      h("button", {
        class: "row",
        onclick: () => { state.sleepChapter = true; state.sleepUntil = 0; state.sheet = null; toast("Sleep at end of chapter"); render(); },
      }, "End of chapter"),
    ]);
  }
  if (state.sheet === "find") {
    return panel("Find in your library", [
      h("input", {
        class: "search",
        placeholder: "Search titles and text",
        value: state.findQuery,
        oninput: async (e) => {
          state.findQuery = e.target.value;
          if (state.findQuery.length > 1) state.searchHits = await api(`/api/search?q=${encodeURIComponent(state.findQuery)}`);
          else state.searchHits = { books: [], passages: [] };
          render();
        },
      }),
      ...(state.searchHits.passages || []).map((hit) => h("button", {
        class: "hit",
        onclick: async () => {
          state.sheet = null;
          await openBook(hit.book_id);
          const chapter = state.book.chapters.find((c) => c.id === hit.chapter_id);
          if (chapter && chapter.status === "ready") {
            await playChapter(state.book, chapter, 0, true);
            const cue = (state.cues || []).find((c) => c.charStart >= hit.char_start - 1);
            if (cue) audio.currentTime = cue.start;
          }
        },
      }, [h("strong", {}, hit.book_title), h("p", {}, hit.snippet)])),
    ]);
  }
  if (state.sheet === "more" && state.book) {
    return panel("More", [
      h("button", { class: "row", onclick: () => { state.carMode = true; state.sheet = null; render(); } }, "Car mode"),
      h("button", { class: "row", onclick: () => downloadBook(state.book) }, "Download"),
      h("button", { class: "row", onclick: () => { state.sheet = "find"; render(); } }, "Find in title"),
      h("button", { class: "row", onclick: () => {
        if (!state.queue.includes(state.book.id)) state.queue.push(state.book.id);
        saveQueue();
        state.sheet = null;
        toast("Added to Up Next");
        render();
      } }, "Add to Up Next"),
      h("div", { class: "muted", style: "margin:10px 0 6px" }, "Jump amount"),
      h("div", { class: "chips" }, [10, 15, 20, 30, 60, 90].map((n) => h("button", {
        class: `chip ${n === state.skip ? "on" : ""}`,
        onclick: () => { state.skip = n; localStorage.setItem("la-skip", String(n)); render(); },
      }, `${n}s`))),
    ]);
  }
  return null;
}

function homeView() {
  const current = state.home.continue;
  const chapter = resumeChapter(current);
  return h("div", { class: "shell" }, [
    h("div", { class: "kicker" }, "ListenAlong"),
    h("h1", { class: "hello" }, greeting()),
    h("p", { class: "muted" }, "Pick up where you left off, or start something new."),
    h("input", {
      class: "search",
      placeholder: "Search titles and text",
      onchange: async (e) => {
        state.findQuery = e.target.value;
        state.sheet = "find";
        if (state.findQuery.length > 1) state.searchHits = await api(`/api/search?q=${encodeURIComponent(state.findQuery)}`);
        render();
      },
    }),
    state.installEvent ? h("div", { class: "banner" }, [
      h("div", {}, [h("strong", {}, "Add to Home Screen"), h("div", { class: "muted" }, "Opens like the Audible app.")]),
      h("button", { class: "btn", onclick: async () => { state.installEvent.prompt(); await state.installEvent.userChoice; state.installEvent = null; render(); } }, "Install"),
    ]) : null,
    current && chapter ? h("button", {
      class: "continue",
      onclick: () => playChapter(current, chapter, current.progress_time || 0, true),
    }, [
      coverEl(current, "sq"),
      h("div", {}, [
        h("div", { class: "kicker" }, "Continue listening"),
        h("h3", {}, current.title),
        h("div", { class: "muted" }, chapter.title),
        h("div", { class: "progress", style: "margin-top:10px" }, h("i", { style: `width:${current.progress_pct || 0}%` })),
        h("div", { class: "left-label" }, formatLeft(current.remaining || 0, state.speed)),
      ]),
      h("span", { class: "play-fab" }, "▶"),
    ]) : null,
    rail("Jump back in", state.home.listening),
    rail("Recently added", state.home.recent),
    rail("Finished", state.home.finished),
    !current && !state.home.recent.length ? h("div", { class: "empty" }, "Your library is empty. Add a title to begin.") : null,
  ]);
}

function libraryView() {
  const filtered = state.books.filter((book) => {
    if (state.filter === "listening") return book.elapsed > 8 && !book.finished;
    if (state.filter === "finished") return book.finished;
    return true;
  });
  return h("div", { class: "shell" }, [
    h("div", { class: "bar" }, [
      h("h1", { class: "hello" }, "Library"),
      h("button", { class: "chip", onclick: () => { state.layout = state.layout === "grid" ? "list" : "grid"; localStorage.setItem("la-layout", state.layout); render(); } }, state.layout === "grid" ? "List" : "Grid"),
    ]),
    h("input", {
      class: "search",
      placeholder: "Search your titles",
      value: state.query,
      oninput: async (e) => { state.query = e.target.value; await refresh(true); },
    }),
    h("div", { class: "chips" }, [
      ["all", "All"],
      ["listening", "In progress"],
      ["finished", "Finished"],
    ].map(([id, label]) => h("button", {
      class: `chip ${state.filter === id ? "on" : ""}`,
      onclick: () => { state.filter = id; render(); },
    }, label))),
    filtered.length
      ? (state.layout === "list"
        ? h("div", {}, filtered.map((book) => h("button", { class: "list-row", onclick: () => openBook(book.id) }, [
            coverEl(book, "sq"),
            h("div", {}, [h("strong", {}, book.title), h("div", { class: "muted" }, `${formatLength(book.duration)} · ${book.narrator}`)]),
            h("span", { class: "muted" }, `${Math.round(book.progress_pct || 0)}%`),
          ])))
        : h("div", { class: "grid" }, filtered.map((book) => h("button", { class: "tile", style: "flex:none;width:100%", onclick: () => openBook(book.id) }, [
            coverEl(book),
            h("div", { class: "meta" }, [h("strong", {}, book.title), h("span", {}, formatLength(book.duration))]),
          ]))))
      : h("div", { class: "empty" }, "No titles in this filter."),
  ]);
}

function titleView() {
  const book = state.book;
  if (!book) return libraryView();
  const resume = resumeChapter(book);
  return h("div", { class: "shell tight" }, [
    h("div", { class: "bar" }, [
      h("button", { class: "icon-btn", onclick: () => { state.view = "library"; state.tab = "library"; render(); } }, svg('<path d="M15 6l-6 6 6 6"/>')),
      h("button", { class: "muted", onclick: async () => {
        if (!confirm("Remove this title?")) return;
        await api(`/api/books/${book.id}`, { method: "DELETE" });
        if (state.chapter && state.book.id === book.id) { audio.pause(); state.chapter = null; }
        state.view = "library";
        await refresh();
        render();
      } }, "Remove"),
    ]),
    h("div", { class: "title-hero" }, [
      coverEl(book, "lg"),
      h("h1", {}, book.title),
      h("p", { class: "muted" }, `By ${book.author || "Unknown"} · Narrated by ${book.narrator}`),
      h("p", { class: "muted" }, `${book.chapter_count} chapters · ${formatLength(book.duration)}`),
      book.excerpt ? h("p", { class: "excerpt" }, book.excerpt) : null,
    ]),
    h("div", { class: "actions" }, [
      resume && resume.status === "ready" ? h("button", {
        class: "btn",
        onclick: () => playChapter(book, resume, book.progress_chapter === resume.idx ? book.progress_time : 0, true),
      }, book.elapsed > 8 ? "Continue" : "Play") : h("span", { class: "pill" }, "Narrating…"),
      h("button", { class: "btn ghost", onclick: () => downloadBook(book) }, "Download"),
      h("button", { class: "btn ghost", onclick: () => {
        if (!state.queue.includes(book.id)) state.queue.push(book.id);
        saveQueue();
        toast("Added to Up Next");
      } }, "Up Next"),
      h("button", { class: "btn ghost", onclick: () => { if (state.chapter) { state.view = "immersion"; render(); } else toast("Play a chapter first"); } }, "Immersion"),
    ]),
    book.status === "processing" ? h("p", { class: "muted" }, `Narrating ${book.ready_chapters}/${book.chapter_count}. You can play chapters as they finish.`) : null,
    book.error ? h("p", { class: "error" }, book.error) : null,
    h("div", { class: "actions" }, [
      h("button", { class: "chip", onclick: async () => {
        const title = prompt("Title", book.title);
        if (!title) return;
        state.book = await api(`/api/books/${book.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) });
        render();
      } }, "Rename"),
      h("button", { class: "chip", onclick: async () => {
        const author = prompt("Author", book.author || "");
        if (author == null) return;
        state.book = await api(`/api/books/${book.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ author }) });
        render();
      } }, "Author"),
      h("button", { class: "chip", onclick: async () => {
        state.book = await api(`/api/books/${book.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ finished: !book.finished }) });
        toast(state.book.finished ? "Marked finished" : "Back in progress");
        await refresh(false);
        render();
      } }, book.finished ? "Unfinish" : "Mark finished"),
    ]),
    state.bookmarks.length ? h("section", {}, [
      h("div", { class: "rail-head" }, h("h2", {}, "Bookmarks")),
      ...state.bookmarks.map((mark) => h("button", {
        class: "row",
        onclick: async () => {
          const chapter = book.chapters.find((c) => c.id === mark.chapter_id);
          if (chapter) await playChapter(book, chapter, mark.time, true);
        },
      }, [h("span", {}, mark.note || "Bookmark"), h("span", { class: "muted" }, formatTime(mark.time))])),
    ]) : null,
    h("div", { class: "rail-head" }, h("h2", {}, "Chapters")),
    ...book.chapters.map((ch, i) => h("button", {
      class: "row",
      onclick: async () => { if (ch.status === "ready") await playChapter(book, ch, book.progress_chapter === ch.idx ? book.progress_time : 0, true); },
    }, [
      h("div", {}, [h("strong", {}, `${i + 1}. ${ch.title}`), h("div", { class: "muted" }, ch.error || (ch.status === "ready" ? formatLength(ch.duration) : ch.status))]),
      ch.status === "ready" ? h("span", { class: "now" }, "Play") : h("span", { class: "muted" }, "Wait"),
    ])),
  ]);
}

function addView() {
  const input = h("input", {
    type: "file",
    multiple: true,
    hidden: true,
    onchange: (e) => {
      state.files = [...e.target.files];
      if (!state.title && state.files[0]) state.title = state.files[0].name.replace(/\.[^.]+$/, "");
      render();
    },
  });
  const folder = h("input", {
    type: "file",
    multiple: true,
    webkitdirectory: true,
    hidden: true,
    onchange: (e) => {
      state.files = [...e.target.files];
      state.title = state.files[0]?.webkitRelativePath?.split("/")[0] || state.title;
      render();
    },
  });
  return h("div", { class: "shell tight" }, [
    h("h1", { class: "hello" }, "Add a title"),
    h("p", { class: "muted" }, "PDF, EPUB, Word, notes, code, a zip, or a folder. On iPhone, zip the folder first."),
    state.error ? h("p", { class: "error" }, state.error) : null,
    h("form", { onsubmit: importBooks }, [
      h("label", {
        class: "drop",
        ondragover: (e) => { e.preventDefault(); e.currentTarget.classList.add("drag"); },
        ondragleave: (e) => e.currentTarget.classList.remove("drag"),
        ondrop: (e) => { e.preventDefault(); e.currentTarget.classList.remove("drag"); state.files = [...e.dataTransfer.files]; render(); },
      }, [
        input,
        "Tap to choose files",
        h("div", {}, [
          h("button", { type: "button", class: "btn ghost", style: "margin:12px 8px 0 0", onclick: () => input.click() }, "Files"),
          h("button", { type: "button", class: "btn ghost", style: "margin-top:12px", onclick: () => folder.click() }, "Folder"),
        ]),
      ]),
      folder,
      state.files.length ? h("p", { class: "muted" }, `${state.files.length} selected`) : null,
      h("label", { class: "field" }, [h("span", {}, "Title"), h("input", { value: state.title, oninput: (e) => { state.title = e.target.value; } })]),
      h("label", { class: "field" }, [h("span", {}, "Author"), h("input", { value: state.author, placeholder: "Optional", oninput: (e) => { state.author = e.target.value; } })]),
      h("label", { class: "field" }, [
        h("span", {}, "Narrator"),
        h("select", { onchange: (e) => { state.voice = e.target.value; localStorage.setItem("la-voice", state.voice); } }, state.voices.map((v) => h("option", { value: v.short_name, selected: v.short_name === state.voice }, v.label))),
      ]),
      h("button", {
        type: "button",
        class: "btn ghost",
        style: "width:100%;margin-bottom:12px",
        onclick: () => {
          const preview = new Audio(`/api/voices/${encodeURIComponent(state.voice)}/preview`);
          preview.play();
        },
      }, "Preview narrator"),
      h("button", { class: "btn", type: "submit", style: "width:100%" }, "Start narration"),
    ]),
  ]);
}

function youView() {
  const hours = (n) => `${Math.floor(n / 3600)}h ${Math.round((n % 3600) / 60)}m`;
  const queued = state.queue.map((id) => state.books.find((b) => b.id === id)).filter(Boolean);
  return h("div", { class: "shell tight" }, [
    h("h1", { class: "hello" }, "You"),
    h("div", { class: "stats" }, [
      h("div", { class: "stat" }, [h("b", {}, hours(state.stats.today_seconds)), h("span", {}, "Today")]),
      h("div", { class: "stat" }, [h("b", {}, String(state.stats.streak)), h("span", {}, "Day streak")]),
      h("div", { class: "stat" }, [h("b", {}, hours(state.stats.total_seconds)), h("span", {}, "All time")]),
      h("div", { class: "stat" }, [h("b", {}, String(state.stats.finished)), h("span", {}, "Finished titles")]),
    ]),
    h("div", { class: "rail-head" }, h("h2", {}, "Playback")),
    h("div", { class: "row" }, [
      h("span", {}, `Loudness ${state.boost.toFixed(1)}x`),
      h("input", { class: "range", type: "range", min: 1, max: 2.5, step: 0.1, value: state.boost, oninput: (e) => {
        state.boost = Number(e.target.value);
        localStorage.setItem("la-boost", String(state.boost));
        ensureGraph();
        if (gainNode) gainNode.gain.value = state.boost;
      } }),
    ]),
    h("button", { class: "row", onclick: () => { state.keepAwake = !state.keepAwake; localStorage.setItem("la-wake", state.keepAwake ? "1" : "0"); render(); } }, [
      h("span", {}, "Keep screen awake while playing"),
      h("span", { class: `switch ${state.keepAwake ? "on" : ""}` }, h("i")),
    ]),
    h("button", { class: "row", onclick: () => { state.haptics = !state.haptics; localStorage.setItem("la-haptics", state.haptics ? "1" : "0"); render(); } }, [
      h("span", {}, "Haptics"),
      h("span", { class: `switch ${state.haptics ? "on" : ""}` }, h("i")),
    ]),
    queued.length ? h("section", {}, [
      h("div", { class: "rail-head" }, h("h2", {}, "Up Next")),
      ...queued.map((book) => h("div", { class: "list-row" }, [
        coverEl(book, "sq"),
        h("button", { onclick: () => openBook(book.id) }, [h("strong", {}, book.title), h("div", { class: "muted" }, book.narrator)]),
        h("button", { class: "muted", onclick: () => { state.queue = state.queue.filter((id) => id !== book.id); saveQueue(); render(); } }, "Remove"),
      ])),
    ]) : h("p", { class: "muted" }, "Add titles to Up Next from a book page."),
  ]);
}

function immersionView() {
  if (!state.book || !state.chapter) return homeView();
  return h("div", { class: "shell" }, [
    h("div", { class: "bar" }, [
      h("button", { class: "btn ghost", onclick: () => { state.view = "player"; render(); } }, "Player"),
      h("div", {}, [
        h("button", { class: "chip", onclick: () => { state.fontSize = Math.max(1, state.fontSize - 0.08); localStorage.setItem("la-font", state.fontSize); render(); } }, "A−"),
        h("button", { class: "chip", onclick: () => { state.fontSize = Math.min(1.8, state.fontSize + 0.08); localStorage.setItem("la-font", state.fontSize); render(); } }, "A+"),
      ]),
    ]),
    h("p", { class: "kicker" }, "Immersion reading"),
    h("h2", {}, state.chapter.title),
    readerText(state.chapter.text || "", state.cues),
  ]);
}

function carView() {
  if (!state.chapter) return null;
  return h("div", { class: "car" }, [
    h("p", { class: "kicker" }, "Car mode"),
    h("h1", {}, state.book.title),
    h("p", { class: "muted" }, state.chapter.title),
    h("div", { class: "row-btns" }, [
      h("button", { class: "skip", style: "width:90px;height:90px;font-size:1rem", onclick: () => { audio.currentTime -= state.skip; } }, `−${state.skip}`),
      h("button", { class: "play-fab", onclick: togglePlay }, audio.paused ? "▶" : "❚❚"),
      h("button", { class: "skip", style: "width:90px;height:90px;font-size:1rem", onclick: () => { audio.currentTime += state.skip; } }, `+${state.skip}`),
    ]),
    h("button", { class: "btn ghost", onclick: () => { state.carMode = false; render(); } }, "Exit car mode"),
  ]);
}

function loginView() {
  return h("div", { class: "login" }, [
    h("form", {
      class: "login-card",
      onsubmit: async (event) => {
        event.preventDefault();
        state.error = "";
        try {
          await api("/api/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ password: state.password }),
          });
          state.authed = true;
          state.view = "home";
          state.tab = "home";
          await boot(true);
        } catch (err) {
          state.error = err.message;
          render();
        }
      },
    }, [
      h("div", { class: "kicker" }, "Your private library"),
      h("h1", {}, "ListenAlong"),
      h("p", { class: "muted" }, "Sign in on this phone once. Then it works from any network."),
      state.error ? h("p", { class: "error" }, state.error) : null,
      h("label", { class: "field" }, [
        h("span", {}, "Password"),
        h("input", { type: "password", autocomplete: "current-password", value: state.password, oninput: (e) => { state.password = e.target.value; } }),
      ]),
      h("button", { class: "btn", type: "submit" }, "Continue"),
    ]),
  ]);
}

function render() {
  app.replaceChildren();
  if (!state.authed && state.needsAuth) {
    app.append(loginView());
    return;
  }
  const view = {
    home: homeView,
    library: libraryView,
    title: titleView,
    add: addView,
    you: youView,
    player: playerView,
    immersion: immersionView,
    login: loginView,
  }[state.view] || homeView;
  app.append(view());
  if (state.carMode) app.append(carView());
  app.append(mini(), nav(), sheet());
  if (state.toast) app.append(h("div", { class: "toast" }, state.toast));
}

function syncPlayButtons() {
  document.querySelectorAll(".play-fab").forEach((button) => {
    button.textContent = audio.paused ? "▶" : "❚❚";
  });
}

audio.addEventListener("timeupdate", () => {
  if (state.sleepUntil) {
    const left = state.sleepUntil - Date.now();
    if (left <= 0) {
      audio.pause();
      state.sleepUntil = 0;
      if (gainNode) gainNode.gain.value = state.boost;
      toast("Sleep timer ended");
    } else if (gainNode && left < 20000) {
      gainNode.gain.value = state.boost * Math.max(0.05, left / 20000);
    }
  }
  highlight();
  const seek = document.querySelector(".seek");
  if (seek && document.activeElement !== seek) seek.value = audio.currentTime;
  const times = document.querySelector(".times span");
  if (times) times.textContent = formatTime(audio.currentTime);
  const left = document.querySelector(".left-label");
  if (left && state.chapter) left.textContent = formatLeft(remainingNow(), state.speed);
});
audio.addEventListener("pause", () => { saveProgress(); syncPlayButtons(); setWake(false); });
audio.addEventListener("play", () => { syncPlayButtons(); lastTick = Date.now(); setWake(true); });
audio.addEventListener("ended", async () => {
  saveProgress();
  if (state.sleepChapter) {
    state.sleepChapter = false;
    toast("Sleep timer ended");
    return;
  }
  const nextChapter = state.book && state.book.chapters[currentChapterIndex() + 1];
  if (nextChapter && nextChapter.status === "ready") {
    await skipChapter(1);
    return;
  }
  const nextId = state.queue.find((id) => id !== (state.book && state.book.id));
  if (nextId) {
    state.queue = state.queue.filter((id) => id !== nextId);
    saveQueue();
    const book = await api(`/api/books/${nextId}`);
    const chapter = (book.chapters || []).find((c) => c.status === "ready");
    if (chapter) await playChapter(book, chapter, 0, true);
    return;
  }
  toast("End of title");
});
setInterval(saveProgress, 5000);

document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, textarea, select")) return;
  if (e.code === "Space") { e.preventDefault(); togglePlay(); }
  if (e.code === "ArrowRight") audio.currentTime += state.skip;
  if (e.code === "ArrowLeft") audio.currentTime -= state.skip;
});

async function boot(alreadyAuthed = false) {
  try {
    const me = await api("/api/me");
    state.needsAuth = me.auth;
    state.authed = alreadyAuthed || me.signed_in || !me.auth;
    if (!state.authed) {
      state.view = "login";
      render();
      return;
    }
    state.voices = await api("/api/voices");
    state.voice = localStorage.getItem("la-voice") || (state.voices[0] && state.voices[0].short_name) || "";
    try { state.stats = await api("/api/stats"); } catch { /* ignore */ }
    await refresh(false);
    render();
  } catch {
    state.needsAuth = true;
    state.authed = false;
    state.view = "login";
    render();
  }
}

boot();
