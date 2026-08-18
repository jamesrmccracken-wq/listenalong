const app = document.getElementById("app");
const audio = document.getElementById("player");

const state = {
  authed: false,
  needsAuth: false,
  view: "library",
  books: [],
  continueBook: null,
  book: null,
  chapter: null,
  cues: [],
  bookmarks: [],
  voices: [],
  files: [],
  title: "",
  voice: "",
  query: "",
  password: "",
  error: "",
  toast: "",
  showNowPlaying: false,
  fontSize: Number(localStorage.getItem("la-font") || 1.22),
  speed: Number(localStorage.getItem("la-speed") || 1),
  sleepUntil: 0,
  poll: null,
  stream: null,
  installEvent: null,
};

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  state.installEvent = event;
  render();
});

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
  const hue = book.cover_hue ?? 28;
  return `background: linear-gradient(145deg, hsl(${hue} 62% 42%), hsl(${(hue + 40) % 360} 45% 18%));${extra}`;
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

function formatDuration(seconds) {
  if (!seconds) return "Narrating…";
  const m = Math.round(seconds / 60);
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return m >= 60 ? `${Math.round(m / 60)}h ${m % 60}m` : `${m} min`;
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
  if (res.status === 204) return null;
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
    refreshLibrary(false);
    if (payload.status === "ready" || payload.status === "error") state.stream.close();
  };
}

async function refreshLibrary(shouldRender = true) {
  state.books = await api(`/api/books?q=${encodeURIComponent(state.query)}`);
  const cont = await api("/api/continue");
  state.continueBook = cont.book;
  if (shouldRender && (state.view === "library" || state.view === "book")) render();
  const busy = state.books.some((b) => b.status === "processing");
  if (busy && !state.poll) state.poll = setInterval(() => refreshLibrary(true), 4000);
  if (!busy && state.poll) {
    clearInterval(state.poll);
    state.poll = null;
  }
}

async function openBook(id) {
  state.book = await api(`/api/books/${id}`);
  state.bookmarks = await api(`/api/books/${id}/bookmarks`);
  state.view = "book";
  if (state.book.status === "processing") watchBook(id);
  render();
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
  data.append("voice", state.voice || (state.voices[0] && state.voices[0].short_name) || "");
  for (const file of state.files) data.append("files", file);
  state.error = "";
  state.view = "library";
  render();
  try {
    const book = await api("/api/books", { method: "POST", body: data });
    toast("Narration started. Chapter 1 plays as soon as it’s ready.");
    await refreshLibrary(false);
    await openBook(book.id);
  } catch (err) {
    state.error = err.message;
    state.view = "import";
    render();
  }
}

async function playChapter(book, chapter, time = 0, commute = false) {
  if (chapter.status !== "ready") return;
  state.book = book.id === (state.book && state.book.id) ? state.book : await api(`/api/books/${book.id}`);
  const full = await api(`/api/books/${book.id}/chapters/${chapter.id}`);
  state.chapter = full;
  state.cues = full.cues || [];
  audio.src = `/api/books/${book.id}/chapters/${chapter.id}/audio`;
  audio.playbackRate = state.speed;
  const start = () => {
    if (time) audio.currentTime = time;
    setupMediaSession();
    prefetchNext();
    cacheAudio(audio.src);
    state.view = commute ? "library" : "reader";
    state.showNowPlaying = commute || state.showNowPlaying;
    render();
  };
  audio.onloadedmetadata = start;
  try {
    await audio.play();
  } catch {
    start();
  }
}

function currentChapterIndex() {
  if (!state.book || !state.chapter) return 0;
  return state.book.chapters.findIndex((c) => c.id === state.chapter.id);
}

async function skipChapter(delta) {
  if (!state.book) return;
  const next = state.book.chapters[currentChapterIndex() + delta];
  if (next && next.status === "ready") await playChapter(state.book, next, 0, state.showNowPlaying);
}

function setupMediaSession() {
  if (!("mediaSession" in navigator) || !state.book || !state.chapter) return;
  navigator.mediaSession.metadata = new MediaMetadata({
    title: state.chapter.title,
    artist: state.book.title,
    album: "ListenAlong",
    artwork: [{ src: "/static/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
  });
  navigator.mediaSession.setActionHandler("play", () => audio.play());
  navigator.mediaSession.setActionHandler("pause", () => audio.pause());
  navigator.mediaSession.setActionHandler("previoustrack", () => skipChapter(-1));
  navigator.mediaSession.setActionHandler("nexttrack", () => skipChapter(1));
  navigator.mediaSession.setActionHandler("seekbackward", () => { audio.currentTime -= 15; });
  navigator.mediaSession.setActionHandler("seekforward", () => { audio.currentTime += 15; });
  navigator.mediaSession.setActionHandler("seekto", (e) => {
    if (typeof e.seekTime === "number") audio.currentTime = e.seekTime;
  });
}

function saveProgress() {
  if (!state.book || !state.chapter) return;
  fetch(`/api/books/${state.book.id}/progress`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chapter_idx: currentChapterIndex(), time: audio.currentTime || 0 }),
  }).catch(() => {});
}

function prefetchNext() {
  if (!state.book) return;
  const next = state.book.chapters[currentChapterIndex() + 1];
  if (next && next.status === "ready") cacheAudio(`/api/books/${state.book.id}/chapters/${next.id}/audio`);
}

function cacheAudio(url) {
  if (!("caches" in window)) return;
  caches.open("listenalong-v3").then((cache) => cache.add(url).catch(() => {}));
}

async function downloadBook(book) {
  const ready = (book.chapters || []).filter((ch) => ch.status === "ready");
  for (const chapter of ready) cacheAudio(`/api/books/${book.id}/chapters/${chapter.id}/audio`);
  toast(`Saved ${ready.length} chapter${ready.length === 1 ? "" : "s"} for offline`);
}

function highlight() {
  const t = audio.currentTime;
  const words = document.querySelectorAll(".reader-text .word");
  let active = null;
  for (const word of words) {
    const start = Number(word.dataset.start);
    const end = Number(word.dataset.end);
    const on = t >= start && t < end + 0.08;
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

function renderReaderText(text, cues) {
  if (!cues.length) return h("div", { class: "reader-text", style: `--read-size:${state.fontSize}rem` }, text);
  const wrap = h("div", { class: "reader-text", style: `--read-size:${state.fontSize}rem` });
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

function miniPlayer() {
  if (!state.chapter || state.showNowPlaying || state.view === "reader" || state.view === "login") return null;
  return h("div", { class: "mini-player", onclick: () => { state.showNowPlaying = true; render(); } }, [
    h("div", { class: "mini-cover", style: coverStyle(state.book) }),
    h("div", {}, [
      h("strong", {}, state.chapter.title),
      h("small", {}, state.book.title),
    ]),
    h("button", {
      class: "btn icon",
      onclick: (e) => {
        e.stopPropagation();
        if (audio.paused) audio.play();
        else audio.pause();
        syncPlayButtons();
      },
    }, audio.paused ? "▶" : "❚❚"),
  ]);
}

function playerControls(full) {
  const chapter = state.chapter;
  const duration = chapter ? chapter.duration : 0;
  return h("div", {}, [
    h("input", {
      class: "seek",
      type: "range",
      min: 0,
      max: Math.max(duration, 1),
      step: 0.1,
      value: audio.currentTime || 0,
      oninput: (e) => { audio.currentTime = Number(e.target.value); highlight(); },
    }),
    h("div", { class: "times" }, [
      h("span", {}, formatTime(audio.currentTime)),
      h("span", {}, formatTime(duration)),
    ]),
    h("div", { class: "controls" }, [
      h("button", { class: "btn ghost", onclick: () => { audio.currentTime -= 15; } }, "−15"),
      h("button", { class: "btn ghost", onclick: () => skipChapter(-1) }, "⟨⟨"),
      h("button", {
        class: `btn icon ${full ? "xl" : ""}`,
        onclick: () => { if (audio.paused) audio.play(); else audio.pause(); syncPlayButtons(); },
      }, audio.paused ? "▶" : "❚❚"),
      h("button", { class: "btn ghost", onclick: () => skipChapter(1) }, "⟩⟩"),
      h("button", { class: "btn ghost", onclick: () => { audio.currentTime += 15; } }, "+15"),
    ]),
    h("div", { class: "tools" }, [
      speedControl(),
      sleepControl(),
      h("button", { class: "chip", onclick: bookmarkHere }, "Bookmark"),
      full ? h("button", { class: "chip", onclick: () => { state.showNowPlaying = false; state.view = "reader"; render(); } }, "Read along") : null,
    ]),
  ]);
}

async function bookmarkHere() {
  if (!state.book || !state.chapter) return;
  await api(`/api/books/${state.book.id}/bookmarks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chapter_id: state.chapter.id, time: audio.currentTime || 0, note: state.chapter.title }),
  });
  state.bookmarks = await api(`/api/books/${state.book.id}/bookmarks`);
  toast("Bookmark saved");
}

function speedControl() {
  const speeds = [0.8, 1, 1.2, 1.4, 1.6, 1.8, 2, 2.5];
  return h("select", {
    class: "chip",
    onchange: (e) => {
      state.speed = Number(e.target.value);
      audio.playbackRate = state.speed;
      localStorage.setItem("la-speed", String(state.speed));
    },
  }, speeds.map((s) => h("option", { value: s, selected: s === state.speed }, `${s}×`)));
}

function sleepControl() {
  return h("select", {
    class: "chip",
    onchange: (e) => {
      const mins = Number(e.target.value);
      state.sleepUntil = mins ? Date.now() + mins * 60 * 1000 : 0;
      if (mins) toast(`Sleep timer ${mins} min`);
    },
  }, [
    h("option", { value: 0 }, "Sleep off"),
    h("option", { value: 15 }, "Sleep 15m"),
    h("option", { value: 30 }, "Sleep 30m"),
    h("option", { value: 45 }, "Sleep 45m"),
    h("option", { value: 60 }, "Sleep 60m"),
    h("option", { value: 90 }, "Sleep 90m"),
  ]);
}

function nowPlaying() {
  if (!state.showNowPlaying || !state.chapter) return null;
  return h("div", { class: "now" }, [
    h("div", { class: "topbar" }, [
      h("button", { class: "btn ghost", onclick: () => { state.showNowPlaying = false; render(); } }, "Down"),
      h("button", { class: "btn ghost", onclick: () => { state.showNowPlaying = false; state.view = "reader"; render(); } }, "Text"),
    ]),
    h("div", { class: "now-cover sq", style: coverStyle(state.book) }),
    h("div", { class: "now-copy" }, [
      h("h1", {}, state.chapter.title),
      h("p", {}, state.book.title),
    ]),
    playerControls(true),
  ]);
}

function loginView() {
  return h("div", { class: "login-wrap" }, [
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
          state.view = "library";
          await boot(true);
        } catch (err) {
          state.error = err.message;
          render();
        }
      },
    }, [
      h("p", { class: "kicker status-pill" }, "Your private library"),
      h("h1", { class: "brand" }, ["Listen", h("span", {}, "Along")]),
      h("p", { class: "sub" }, "Sign in once on this phone. After that it works from any network, including the commute."),
      state.error ? h("p", { class: "error" }, state.error) : null,
      h("label", { class: "field" }, [
        h("span", {}, "Password"),
        h("input", {
          type: "password",
          autocomplete: "current-password",
          value: state.password,
          oninput: (e) => { state.password = e.target.value; },
        }),
      ]),
      h("button", { class: "btn", type: "submit" }, "Open library"),
    ]),
  ]);
}

function continueCard(book) {
  if (!book) return null;
  const chapter = (book.chapters || [])[book.progress_chapter] || (book.chapters || []).find((c) => c.status === "ready");
  return h("button", {
    class: "continue",
    onclick: async () => {
      if (!chapter || chapter.status !== "ready") {
        await openBook(book.id);
        return;
      }
      await playChapter(book, chapter, book.progress_time || 0, true);
    },
  }, [
    h("div", { class: "cover sq", style: coverStyle(book) }),
    h("div", {}, [
      h("div", { class: "kicker" }, "Continue listening"),
      h("h2", {}, book.title),
      h("div", { class: "card-meta" }, chapter ? chapter.title : "Open title"),
      h("div", { class: "progress-bar", style: "margin-top:10px" }, h("i", { style: `width:${book.progress_pct || 0}%` })),
    ]),
    h("span", { class: "btn icon" }, "▶"),
  ]);
}

function libraryView() {
  return h("div", { class: "app-shell" }, [
    h("div", { class: "topbar" }, [
      h("div", {}, [
        h("h1", { class: "brand" }, ["Listen", h("span", {}, "Along")]),
        h("p", { class: "sub" }, "Your library, on any network."),
      ]),
      h("div", { class: "row" }, [
        h("button", { class: "btn", onclick: () => { state.view = "import"; render(); } }, "Import"),
      ]),
    ]),
    state.installEvent ? h("div", { class: "banner" }, [
      h("div", {}, [h("strong", {}, "Add to Home Screen"), h("div", { class: "card-meta" }, "Install so it opens like an app on the commute.")]),
      h("button", {
        class: "btn",
        onclick: async () => {
          state.installEvent.prompt();
          await state.installEvent.userChoice;
          state.installEvent = null;
          render();
        },
      }, "Install"),
    ]) : null,
    h("input", {
      class: "search",
      placeholder: "Search titles",
      value: state.query,
      oninput: async (e) => {
        state.query = e.target.value;
        await refreshLibrary(true);
      },
    }),
    continueCard(state.continueBook),
    state.books.length
      ? h("div", { class: "library-grid" }, state.books.map(bookCard))
      : h("div", { class: "empty" }, [
          h("h2", {}, "Your library is empty"),
          h("p", { class: "sub" }, "Drop in a PDF, EPUB, Word doc, notes, or a whole folder."),
          h("button", { class: "btn", onclick: () => { state.view = "import"; render(); } }, "Add a title"),
        ]),
  ]);
}

function bookCard(book) {
  const total = book.chapter_count || 1;
  const ready = book.ready_chapters || 0;
  const pct = book.progress_pct || (ready / total) * 100;
  return h("button", { class: "cover-card", onclick: () => openBook(book.id) }, [
    h("div", { class: "cover", style: coverStyle(book) }, [
      h("b", {}, book.title),
      h("small", {}, book.status === "ready" ? formatDuration(book.duration) : `${ready}/${total} ready`),
    ]),
    h("div", { class: "card-meta" }, book.status === "error" ? "Needs attention" : book.status === "processing" ? "Narrating…" : `${Math.round(pct)}% listened`),
    h("div", { class: "progress-bar" }, h("i", { style: `width:${pct}%` })),
  ]);
}

function bookView() {
  const book = state.book;
  if (!book) return libraryView();
  const resume = book.chapters[book.progress_chapter] || book.chapters.find((c) => c.status === "ready");
  return h("div", { class: "app-shell" }, [
    h("div", { class: "topbar" }, [
      h("button", { class: "btn ghost", onclick: () => { state.view = "library"; render(); } }, "Library"),
      h("button", {
        class: "btn danger",
        onclick: async () => {
          if (!confirm("Remove this title and its audio?")) return;
          await api(`/api/books/${book.id}`, { method: "DELETE" });
          if (state.chapter && state.book && state.book.id === book.id) {
            audio.pause();
            state.chapter = null;
          }
          state.view = "library";
          await refreshLibrary();
          render();
        },
      }, "Delete"),
    ]),
    h("div", { class: "cover", style: coverStyle(book, "max-width:220px;margin-bottom:18px;") }, [
      h("b", {}, book.title),
      h("small", {}, `${book.chapter_count} chapters · ${formatDuration(book.duration)}`),
    ]),
    h("div", { class: "row", style: "margin-bottom:16px" }, [
      resume && resume.status === "ready" ? h("button", {
        class: "btn",
        onclick: () => playChapter(book, resume, book.progress_chapter === resume.idx ? book.progress_time : 0, true),
      }, "Play") : null,
      h("button", { class: "btn ghost", onclick: () => downloadBook(book) }, "Save offline"),
      h("button", {
        class: "btn ghost",
        onclick: async () => {
          const title = prompt("Rename title", book.title);
          if (!title) return;
          state.book = await api(`/api/books/${book.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title }),
          });
          await refreshLibrary(false);
          render();
        },
      }, "Rename"),
    ]),
    book.status === "processing" ? h("p", { class: "status-pill" }, `Narrating ${book.ready_chapters}/${book.chapter_count} — play as soon as a chapter is ready.`) : null,
    book.error ? h("p", { class: "error" }, book.error) : null,
    state.bookmarks.length ? h("div", { class: "panel", style: "margin:16px 0" }, [
      h("strong", {}, "Bookmarks"),
      ...state.bookmarks.map((mark) => h("button", {
        class: "chapter-row",
        onclick: async () => {
          const chapter = book.chapters.find((c) => c.id === mark.chapter_id);
          if (chapter) await playChapter(book, chapter, mark.time, true);
        },
      }, [
        h("span", {}, mark.note || "Bookmark"),
        h("span", { class: "card-meta" }, formatTime(mark.time)),
      ])),
    ]) : null,
    ...book.chapters.map((ch) => h("button", {
      class: "chapter-row",
      onclick: async () => {
        if (ch.status === "ready") await playChapter(book, ch, book.progress_chapter === ch.idx ? book.progress_time : 0);
      },
    }, [
      h("div", {}, [
        h("strong", {}, ch.title),
        h("div", { class: "card-meta" }, ch.error || (ch.status === "ready" ? formatDuration(ch.duration) : ch.status)),
      ]),
      ch.status === "ready" ? h("span", {}, "Play") : h("span", { class: "pending" }, ch.status === "narrating" ? "Now" : "Wait"),
    ])),
  ]);
}

function importView() {
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
      state.title = state.files[0] && state.files[0].webkitRelativePath
        ? state.files[0].webkitRelativePath.split("/")[0]
        : state.title;
      render();
    },
  });

  return h("div", { class: "app-shell" }, [
    h("div", { class: "topbar" }, [
      h("button", { class: "btn ghost", onclick: () => { state.view = "library"; render(); } }, "Library"),
    ]),
    h("h1", { class: "brand" }, "Import"),
    h("p", { class: "sub" }, "PDF, EPUB, Word, markdown, text, code, a zip, or a whole folder. On a phone, zip the folder first. After narration, it is available on every device."),
    state.error ? h("p", { class: "error" }, state.error) : null,
    h("form", { class: "panel", onsubmit: importBooks }, [
      h("label", {
        class: "drop",
        ondragover: (e) => { e.preventDefault(); e.currentTarget.classList.add("drag"); },
        ondragleave: (e) => e.currentTarget.classList.remove("drag"),
        ondrop: (e) => {
          e.preventDefault();
          e.currentTarget.classList.remove("drag");
          state.files = [...e.dataTransfer.files];
          render();
        },
      }, [
        input,
        "Tap to choose files, or drop them here",
        h("div", {}, [
          h("button", { type: "button", class: "btn ghost", style: "margin:12px 8px 0 0", onclick: () => input.click() }, "Files"),
          h("button", { type: "button", class: "btn ghost", style: "margin-top:12px", onclick: () => folder.click() }, "Folder"),
        ]),
      ]),
      folder,
      state.files.length ? h("p", { class: "file-list" }, `${state.files.length} file${state.files.length === 1 ? "" : "s"} selected`) : null,
      h("label", { class: "field" }, [
        h("span", {}, "Title"),
        h("input", {
          value: state.title,
          placeholder: "Optional — inferred from the file name",
          oninput: (e) => { state.title = e.target.value; },
        }),
      ]),
      h("label", { class: "field" }, [
        h("span", {}, "Voice"),
        h("select", {
          onchange: (e) => { state.voice = e.target.value; },
        }, state.voices.map((v) => h("option", { value: v.short_name, selected: v.short_name === state.voice }, v.label))),
      ]),
      h("button", { class: "btn", type: "submit" }, "Narrate"),
    ]),
  ]);
}

function readerView() {
  if (!state.book || !state.chapter) return libraryView();
  return h("div", { class: "app-shell" }, [
    h("div", { class: "topbar" }, [
      h("button", { class: "btn ghost", onclick: () => { state.view = "book"; render(); } }, "Chapters"),
      h("div", { class: "row" }, [
        h("button", { class: "chip", onclick: () => { state.fontSize = Math.max(1, state.fontSize - 0.08); localStorage.setItem("la-font", state.fontSize); render(); } }, "A-"),
        h("button", { class: "chip", onclick: () => { state.fontSize = Math.min(1.8, state.fontSize + 0.08); localStorage.setItem("la-font", state.fontSize); render(); } }, "A+"),
        h("button", { class: "btn ghost", onclick: () => { state.showNowPlaying = true; render(); } }, "Player"),
      ]),
    ]),
    h("p", { class: "sub" }, state.book.title),
    h("h2", { class: "brand" }, state.chapter.title),
    h("div", { class: "reader" }, renderReaderText(state.chapter.text || "", state.cues)),
    h("div", { class: "mini-player", style: "grid-template-columns:1fr" }, playerControls(false)),
  ]);
}

function render() {
  app.replaceChildren();
  if (!state.authed && state.needsAuth) {
    app.append(loginView());
    return;
  }
  const view = {
    library: libraryView,
    book: bookView,
    import: importView,
    reader: readerView,
    login: loginView,
  }[state.view] || libraryView;
  app.append(view(), miniPlayer(), nowPlaying());
  if (state.toast) app.append(h("div", { class: "toast" }, state.toast));
}

function syncPlayButtons() {
  document.querySelectorAll(".controls .btn.icon, .mini-player .btn.icon").forEach((button) => {
    button.textContent = audio.paused ? "▶" : "❚❚";
  });
}

audio.addEventListener("timeupdate", () => {
  if (state.sleepUntil && Date.now() >= state.sleepUntil) {
    audio.pause();
    state.sleepUntil = 0;
    toast("Sleep timer ended");
  }
  highlight();
  const seek = document.querySelector(".seek");
  if (seek && document.activeElement !== seek) seek.value = audio.currentTime;
  const times = document.querySelector(".times span");
  if (times) times.textContent = formatTime(audio.currentTime);
});
audio.addEventListener("pause", () => { saveProgress(); syncPlayButtons(); });
audio.addEventListener("play", syncPlayButtons);
audio.addEventListener("ended", async () => {
  saveProgress();
  await skipChapter(1);
});
setInterval(saveProgress, 5000);

document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, textarea, select")) return;
  if (e.code === "Space") {
    e.preventDefault();
    if (audio.paused) audio.play();
    else audio.pause();
  }
  if (e.code === "ArrowRight") audio.currentTime += 15;
  if (e.code === "ArrowLeft") audio.currentTime -= 15;
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
    state.voice = (state.voices[0] && state.voices[0].short_name) || "";
    await refreshLibrary(false);
    render();
  } catch {
    state.needsAuth = true;
    state.authed = false;
    state.view = "login";
    render();
  }
}

boot();
