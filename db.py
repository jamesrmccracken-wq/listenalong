from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def connect(db_path: Path) -> None:
    global _conn
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(db_path, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA foreign_keys=ON")
    _conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL DEFAULT '',
            source_name TEXT NOT NULL DEFAULT '',
            voice TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'processing',
            error TEXT,
            cover_hue INTEGER NOT NULL DEFAULT 28,
            progress_chapter INTEGER NOT NULL DEFAULT 0,
            progress_time REAL NOT NULL DEFAULT 0,
            last_listened_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            idx INTEGER NOT NULL,
            title TEXT NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            duration REAL NOT NULL DEFAULT 0,
            error TEXT,
            UNIQUE(book_id, idx)
        );

        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
            time REAL NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    _ensure_column("books", "last_listened_at", "TEXT")
    _ensure_column("books", "finished_at", "TEXT")
    _conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS listen_days (
            day TEXT PRIMARY KEY,
            seconds REAL NOT NULL DEFAULT 0
        );
        """
    )
    _conn.commit()


def _ensure_column(table: str, name: str, spec: str) -> None:
    rows = _db().execute(f"PRAGMA table_info({table})").fetchall()
    if name not in {row["name"] for row in rows}:
        _db().execute(f"ALTER TABLE {table} ADD COLUMN {name} {spec}")


def _db() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("Database is not connected")
    return _conn


def query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with _lock:
        rows = _db().execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def execute(sql: str, params: tuple = ()) -> int:
    with _lock:
        cur = _db().execute(sql, params)
        _db().commit()
        return int(cur.lastrowid)


def _progress_stats(book: dict[str, Any], chapters: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(float(ch.get("duration") or 0) for ch in chapters)
    idx = int(book.get("progress_chapter") or 0)
    elapsed = float(book.get("progress_time") or 0)
    for chapter in chapters:
        if int(chapter["idx"]) < idx:
            elapsed += float(chapter.get("duration") or 0)
    book["duration"] = total
    book["elapsed"] = elapsed
    book["remaining"] = max(0.0, total - elapsed)
    book["progress_pct"] = 0 if not total else min(100, round(100 * elapsed / total, 1))
    ready = sum(1 for ch in chapters if ch["status"] == "ready")
    book["ready_chapters"] = ready
    book["chapter_count"] = len(chapters)
    book["finished"] = bool(book.get("finished_at")) or (total > 0 and elapsed >= total * 0.98)
    book["narrator"] = _narrator_name(book.get("voice") or "")
    if not book.get("author"):
        book["author"] = "Unknown"
    return book


def book_with_chapters(book_id: int) -> dict[str, Any] | None:
    books = query("SELECT * FROM books WHERE id = ?", (book_id,))
    if not books:
        return None
    book = books[0]
    book["chapters"] = query(
        """
        SELECT id, book_id, idx, title, status, duration, error,
               length(text) AS char_count
        FROM chapters
        WHERE book_id = ?
        ORDER BY idx
        """,
        (book_id,),
    )
    blurb = query("SELECT substr(text, 1, 420) AS excerpt FROM chapters WHERE book_id = ? ORDER BY idx LIMIT 1", (book_id,))
    book["excerpt"] = (blurb[0]["excerpt"] if blurb else "") or ""
    return _progress_stats(book, book["chapters"])


def list_books(search: str = "") -> list[dict[str, Any]]:
    if search.strip():
        like = f"%{search.strip()}%"
        books = query(
            "SELECT * FROM books WHERE title LIKE ? OR source_name LIKE ? ORDER BY COALESCE(last_listened_at, created_at) DESC",
            (like, like),
        )
    else:
        books = query("SELECT * FROM books ORDER BY COALESCE(last_listened_at, created_at) DESC")
    for book in books:
        chapters = query(
            "SELECT idx, status, duration FROM chapters WHERE book_id = ? ORDER BY idx",
            (book["id"],),
        )
        _progress_stats(book, chapters)
    return books


def _narrator_name(voice: str) -> str:
    stem = voice.split("-")[-1] if voice else "Narrator"
    stem = stem.replace("Neural", "").replace("Multilingual", "")
    return stem or "Narrator"


def home() -> dict[str, Any]:
    books = list_books()
    listening = [b for b in books if b["elapsed"] > 8 and not b["finished"]]
    recent = sorted(books, key=lambda b: b.get("created_at") or "", reverse=True)
    finished = [b for b in books if b["finished"]]
    return {
        "continue": continue_book(),
        "listening": listening[:12],
        "recent": recent[:16],
        "finished": finished[:12],
        "library_count": len(books),
    }


def add_listen_seconds(seconds: float) -> None:
    if seconds <= 0:
        return
    execute(
        """
        INSERT INTO listen_days (day, seconds) VALUES (date('now'), ?)
        ON CONFLICT(day) DO UPDATE SET seconds = seconds + excluded.seconds
        """,
        (float(seconds),),
    )


def stats() -> dict[str, Any]:
    today = query("SELECT seconds FROM listen_days WHERE day = date('now')")
    total = query("SELECT COALESCE(SUM(seconds), 0) AS seconds FROM listen_days")
    finished = query("SELECT COUNT(*) AS n FROM books WHERE finished_at IS NOT NULL")
    titles = query("SELECT COUNT(*) AS n FROM books")
    days = query("SELECT day, seconds FROM listen_days WHERE seconds >= 60 ORDER BY day DESC LIMIT 400")
    streak = 0
    expected = query("SELECT date('now') AS d")[0]["d"]
    for row in days:
        if row["day"] != expected:
            # allow missing today
            if streak == 0 and row["day"] != expected:
                expected = query("SELECT date('now', '-1 day') AS d")[0]["d"]
                if row["day"] != expected:
                    break
        streak += 1
        expected = query("SELECT date(?, '-1 day') AS d", (row["day"],))[0]["d"]
    return {
        "today_seconds": float(today[0]["seconds"]) if today else 0,
        "total_seconds": float(total[0]["seconds"] if total else 0),
        "finished": int(finished[0]["n"] if finished else 0),
        "titles": int(titles[0]["n"] if titles else 0),
        "streak": streak,
    }


def search_library(q: str, limit: int = 24) -> dict[str, Any]:
    needle = q.strip()
    if len(needle) < 2:
        return {"books": [], "passages": []}
    like = f"%{needle}%"
    books = list_books(needle)
    passages = query(
        """
        SELECT chapters.id AS chapter_id, chapters.idx, chapters.title AS chapter_title,
               chapters.book_id, books.title AS book_title,
               substr(chapters.text, max(instr(lower(chapters.text), lower(?)) - 60, 1), 180) AS snippet,
               instr(lower(chapters.text), lower(?)) AS char_start
        FROM chapters
        JOIN books ON books.id = chapters.book_id
        WHERE chapters.text LIKE ?
        ORDER BY books.last_listened_at DESC
        LIMIT ?
        """,
        (needle, needle, like, limit),
    )
    return {"books": books[:12], "passages": [p for p in passages if p["char_start"]]}


def continue_book() -> dict[str, Any] | None:
    rows = query(
        """
        SELECT * FROM books
        WHERE last_listened_at IS NOT NULL
        ORDER BY last_listened_at DESC
        LIMIT 1
        """
    )
    if not rows:
        return None
    return book_with_chapters(rows[0]["id"])
