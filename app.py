from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import auth
import db
import extract
import icons
import covers
from tts import DEFAULT_VOICE, list_english_voices, preview_voice, synthesize_chapter_retry

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data")).resolve()
UPLOADS = DATA_DIR / "uploads"
AUDIO = DATA_DIR / "audio"
DB_PATH = DATA_DIR / "listenalong.db"

generate_lock = asyncio.Semaphore(2)
voice_cache: list[dict[str, str]] = []
PREVIEWS = None

WELCOME_TEXT = """
ListenAlong turns documents into an audiobook you can follow with your eyes and your ears.

Import a PDF, Word file, EPUB, markdown note, or a whole folder. ListenAlong extracts the text, splits it into chapters, and reads it aloud with a natural voice.

While the audio plays, the current words stay highlighted so you can dual-code: reading and listening at the same time.

Open it from any network — home, work, or mobile data. Add it to your phone’s home screen. Generated audio is a real recording, so it keeps playing when the screen locks on the commute.

Playback speed, thirty-second skips, bookmarks, chapter jumping, offline download, sleep timer, and Immersion Reading are in the player. Your place in each title is saved and follows you across devices.

This welcome chapter was generated the first time the app started. Import your own material whenever you are ready.
""".strip()


def book_audio_dir(book_id: int) -> Path:
    path = AUDIO / str(book_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def hue_for(title: str) -> int:
    return sum(title.encode()) % 360


def _unique_title(title: str, idx: int) -> str:
    cleaned = re.sub(r"\s+", " ", title).strip() or f"Chapter {idx + 1}"
    return cleaned[:120]


async def seed_welcome() -> None:
    if db.query("SELECT id FROM books LIMIT 1"):
        return
    book_id = db.execute(
        "INSERT INTO books (title, author, source_name, voice, status, cover_hue) VALUES (?, ?, ?, ?, ?, ?)",
        ("Welcome to ListenAlong", "ListenAlong", "welcome", DEFAULT_VOICE, "processing", 32),
    )
    db.execute(
        "INSERT INTO chapters (book_id, idx, title, text, status) VALUES (?, ?, ?, ?, ?)",
        (book_id, 0, "Getting started", WELCOME_TEXT, "queued"),
    )
    asyncio.create_task(process_book(book_id))


async def _narrate_chapter(book: dict, chapter: dict) -> None:
    db.execute("UPDATE chapters SET status = ?, error = NULL WHERE id = ?", ("narrating", chapter["id"]))
    mp3_path = book_audio_dir(book["id"]) / f"{chapter['idx']}.mp3"
    cues_path = book_audio_dir(book["id"]) / f"{chapter['idx']}.json"
    try:
        async with generate_lock:
            duration, cues = await synthesize_chapter_retry(chapter["text"], book["voice"], mp3_path)
        cues_path.write_text(json.dumps(cues), encoding="utf-8")
        db.execute(
            "UPDATE chapters SET status = ?, duration = ?, error = NULL WHERE id = ?",
            ("ready", duration, chapter["id"]),
        )
    except Exception as exc:
        db.execute(
            "UPDATE chapters SET status = ?, error = ? WHERE id = ?",
            ("error", str(exc), chapter["id"]),
        )


async def process_book(book_id: int) -> None:
    book_rows = db.query("SELECT * FROM books WHERE id = ?", (book_id,))
    if not book_rows:
        return
    book = book_rows[0]
    chapters = db.query(
        "SELECT * FROM chapters WHERE book_id = ? AND status != 'ready' ORDER BY idx",
        (book_id,),
    )
    db.execute("UPDATE books SET status = ?, error = NULL WHERE id = ?", ("processing", book_id))
    if not chapters:
        db.execute("UPDATE books SET status = ? WHERE id = ?", ("ready", book_id))
        return
    first, *rest = chapters
    await _narrate_chapter(book, first)
    if rest:
        await asyncio.gather(*[_narrate_chapter(book, chapter) for chapter in rest])
    failed = db.query("SELECT COUNT(*) AS n FROM chapters WHERE book_id = ? AND status = 'error'", (book_id,))[0]["n"]
    total = db.query("SELECT COUNT(*) AS n FROM chapters WHERE book_id = ?", (book_id,))[0]["n"]
    if failed and failed == total:
        db.execute("UPDATE books SET status = ?, error = ? WHERE id = ?", ("error", "Narration failed", book_id))
    else:
        db.execute("UPDATE books SET status = ?, error = NULL WHERE id = ?", ("ready", book_id))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.environ.get("RENDER") and not auth.password():
        raise RuntimeError("APP_PASSWORD must be set in production")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    AUDIO.mkdir(parents=True, exist_ok=True)
    global PREVIEWS
    PREVIEWS = DATA_DIR / "previews"
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    icons.ensure_icons(STATIC)
    db.connect(DB_PATH)
    await seed_welcome()
    global voice_cache
    try:
        voice_cache = await list_english_voices()
    except Exception:
        voice_cache = [{"short_name": DEFAULT_VOICE, "locale": "en-US", "gender": "Female", "label": "Aria (en-US)"}]
    yield


app = FastAPI(title="ListenAlong", lifespan=lifespan)
app.middleware("http")(auth.gate)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class ProgressIn(BaseModel):
    chapter_idx: int = 0
    time: float = 0
    listened: float = 0


class LoginIn(BaseModel):
    password: str


class TitleIn(BaseModel):
    title: str | None = None
    author: str | None = None
    finished: bool | None = None


class BookmarkIn(BaseModel):
    chapter_id: int
    time: float = 0
    note: str = ""


@app.api_route("/healthz", methods=["GET", "HEAD"])
async def healthz() -> dict:
    return {"ok": True}


@app.api_route("/", methods=["GET", "HEAD"])
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/sw.js")
async def service_worker() -> FileResponse:
    return FileResponse(STATIC / "sw.js", media_type="text/javascript")


@app.get("/manifest.json")
async def manifest() -> FileResponse:
    return FileResponse(STATIC / "manifest.json", media_type="application/manifest+json")


@app.get("/api/me")
async def me(request: Request) -> dict:
    return {"ok": True, "auth": auth.required(), "signed_in": auth.authorized(request)}


@app.post("/api/login")
async def login(payload: LoginIn, request: Request) -> JSONResponse:
    ip = request.client.host if request.client else "unknown"
    if auth.rate_limited(ip):
        raise HTTPException(429, "Too many attempts. Wait a minute.")
    if auth.required() and not auth.check_password(payload.password):
        raise HTTPException(401, "Wrong password")
    response = JSONResponse({"ok": True})
    auth.set_session(response)
    return response


@app.post("/api/logout")
async def logout() -> JSONResponse:
    response = JSONResponse({"ok": True})
    auth.clear_session(response)
    return response


@app.get("/api/voices")
async def voices() -> list[dict[str, str]]:
    return voice_cache


@app.get("/api/stats")
async def listening_stats() -> dict:
    return db.stats()


@app.get("/api/search")
async def search(q: str = "") -> dict:
    return db.search_library(q)


@app.get("/api/books/{book_id}/cover")
async def book_cover(book_id: int) -> Response:
    book = db.book_with_chapters(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    svg = covers.cover_svg(book["id"], book["title"], book.get("author") or "", book.get("narrator") or "", book.get("cover_hue") or 18)
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/voices/{voice}/preview")
async def voice_preview(voice: str) -> FileResponse:
    if PREVIEWS is None:
        raise HTTPException(500, "Not ready")
    safe = re.sub(r"[^a-zA-Z0-9._-]", "", voice) or "voice"
    path = PREVIEWS / f"{safe}.mp3"
    await preview_voice(voice, path)
    return FileResponse(path, media_type="audio/mpeg")


@app.get("/api/home")
async def home() -> dict:
    return db.home()


@app.get("/api/continue")
async def continue_listening() -> dict:
    book = db.continue_book()
    if not book:
        return {"book": None}
    return {"book": book}


@app.get("/api/books")
async def list_books(q: str = "") -> list[dict]:
    return db.list_books(q)


@app.get("/api/books/{book_id}")
async def get_book(book_id: int) -> dict:
    book = db.book_with_chapters(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    return book


@app.get("/api/books/{book_id}/stream")
async def stream_book(book_id: int):
    if not db.query("SELECT id FROM books WHERE id = ?", (book_id,)):
        raise HTTPException(404, "Book not found")

    async def events():
        last = ""
        for _ in range(1800):
            book = db.book_with_chapters(book_id)
            if not book:
                break
            payload = json.dumps({
                "status": book["status"],
                "ready_chapters": book["ready_chapters"],
                "chapter_count": book["chapter_count"],
                "chapters": [
                    {"id": ch["id"], "idx": ch["idx"], "status": ch["status"], "duration": ch["duration"], "error": ch["error"]}
                    for ch in book["chapters"]
                ],
            })
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if book["status"] in {"ready", "error"}:
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/books/{book_id}/chapters/{chapter_id}")
async def get_chapter(book_id: int, chapter_id: int) -> dict:
    rows = db.query("SELECT * FROM chapters WHERE id = ? AND book_id = ?", (chapter_id, book_id))
    if not rows:
        raise HTTPException(404, "Chapter not found")
    chapter = rows[0]
    cues_path = book_audio_dir(book_id) / f"{chapter['idx']}.json"
    chapter["cues"] = json.loads(cues_path.read_text(encoding="utf-8")) if cues_path.exists() else []
    chapter["bookmarks"] = db.query(
        "SELECT * FROM bookmarks WHERE book_id = ? AND chapter_id = ? ORDER BY time",
        (book_id, chapter_id),
    )
    return chapter


@app.get("/api/books/{book_id}/chapters/{chapter_id}/audio")
async def chapter_audio(book_id: int, chapter_id: int) -> FileResponse:
    rows = db.query("SELECT * FROM chapters WHERE id = ? AND book_id = ?", (chapter_id, book_id))
    if not rows:
        raise HTTPException(404, "Chapter not found")
    path = book_audio_dir(book_id) / f"{rows[0]['idx']}.mp3"
    if not path.exists():
        raise HTTPException(409, "Audio is still being generated")
    return FileResponse(path, media_type="audio/mpeg", filename=f"{rows[0]['title']}.mp3")


@app.patch("/api/books/{book_id}/progress")
async def save_progress(book_id: int, payload: ProgressIn) -> dict:
    if not db.query("SELECT id FROM books WHERE id = ?", (book_id,)):
        raise HTTPException(404, "Book not found")
    db.execute(
        "UPDATE books SET progress_chapter = ?, progress_time = ?, last_listened_at = datetime('now') WHERE id = ?",
        (payload.chapter_idx, payload.time, book_id),
    )
    db.add_listen_seconds(payload.listened)
    book = db.book_with_chapters(book_id)
    if book and book["duration"] and book["elapsed"] >= book["duration"] * 0.98:
        db.execute("UPDATE books SET finished_at = datetime('now') WHERE id = ? AND finished_at IS NULL", (book_id,))
    return {"ok": True}


@app.patch("/api/books/{book_id}")
async def update_book(book_id: int, payload: TitleIn) -> dict:
    if not db.query("SELECT id FROM books WHERE id = ?", (book_id,)):
        raise HTTPException(404, "Book not found")
    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(400, "Title is required")
        db.execute("UPDATE books SET title = ? WHERE id = ?", (title, book_id))
    if payload.author is not None:
        db.execute("UPDATE books SET author = ? WHERE id = ?", (payload.author.strip(), book_id))
    if payload.finished is True:
        db.execute("UPDATE books SET finished_at = datetime('now') WHERE id = ?", (book_id,))
    if payload.finished is False:
        db.execute("UPDATE books SET finished_at = NULL WHERE id = ?", (book_id,))
    book = db.book_with_chapters(book_id)
    assert book
    return book


@app.get("/api/books/{book_id}/bookmarks")
async def list_bookmarks(book_id: int) -> list[dict]:
    return db.query("SELECT * FROM bookmarks WHERE book_id = ? ORDER BY created_at DESC", (book_id,))


@app.post("/api/books/{book_id}/bookmarks")
async def add_bookmark(book_id: int, payload: BookmarkIn) -> dict:
    chapter = db.query("SELECT id FROM chapters WHERE id = ? AND book_id = ?", (payload.chapter_id, book_id))
    if not chapter:
        raise HTTPException(404, "Chapter not found")
    bookmark_id = db.execute(
        "INSERT INTO bookmarks (book_id, chapter_id, time, note) VALUES (?, ?, ?, ?)",
        (book_id, payload.chapter_id, payload.time, payload.note.strip()[:200]),
    )
    rows = db.query("SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,))
    return rows[0]


@app.delete("/api/bookmarks/{bookmark_id}")
async def delete_bookmark(bookmark_id: int) -> dict:
    db.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
    return {"ok": True}


@app.delete("/api/books/{book_id}")
async def delete_book(book_id: int) -> dict:
    if not db.query("SELECT id FROM books WHERE id = ?", (book_id,)):
        raise HTTPException(404, "Book not found")
    db.execute("DELETE FROM books WHERE id = ?", (book_id,))
    shutil.rmtree(book_audio_dir(book_id), ignore_errors=True)
    return {"ok": True}


@app.post("/api/books")
async def create_book(
    files: list[UploadFile] = File(...),
    title: str = Form(""),
    author: str = Form(""),
    voice: str = Form(DEFAULT_VOICE),
) -> dict:
    if not files:
        raise HTTPException(400, "Choose a document, zip, or folder")
    work = UPLOADS / f"in_{os.getpid()}_{id(files)}"
    work.mkdir(parents=True, exist_ok=True)
    chapters: list[extract.ExtractedChapter] = []
    source_names: list[str] = []
    inferred = "Untitled"
    try:
        if len(files) == 1:
            upload = files[0]
            filename = Path(upload.filename or "document").name
            source_names.append(filename)
            data = await upload.read()
            chapters = extract.extract_bytes(filename, data, work)
            inferred = extract.title_from_name(filename)
        else:
            for upload in files:
                filename = Path(upload.filename or "document").name
                if not extract.is_supported(filename):
                    continue
                source_names.append(filename)
                data = await upload.read()
                extracted = extract.extract_bytes(filename, data, work)
                if len(extracted) == 1:
                    extracted[0].title = extract.title_from_name(filename)
                chapters.extend(extracted)
            inferred = extract.title_from_name(source_names[0]) if source_names else "Untitled"
            if files[0].filename and "/" in files[0].filename:
                inferred = files[0].filename.split("/")[0]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)

    chapters = [ch for ch in chapters if ch.text.strip()]
    if not chapters:
        raise HTTPException(400, "No readable text was found")

    book_title = title.strip() or inferred
    book_id = db.execute(
        "INSERT INTO books (title, author, source_name, voice, status, cover_hue) VALUES (?, ?, ?, ?, ?, ?)",
        (book_title, author.strip(), "; ".join(source_names[:8]), voice or DEFAULT_VOICE, "processing", hue_for(book_title)),
    )
    for idx, chapter in enumerate(chapters):
        db.execute(
            "INSERT INTO chapters (book_id, idx, title, text, status) VALUES (?, ?, ?, ?, ?)",
            (book_id, idx, _unique_title(chapter.title, idx), chapter.text, "queued"),
        )
    asyncio.create_task(process_book(book_id))
    book = db.book_with_chapters(book_id)
    assert book
    return book
