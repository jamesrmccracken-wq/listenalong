from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import edge_tts

MAX_TTS_CHARS = 4200

DEFAULT_VOICE = "en-US-AriaNeural"

PREFERRED_VOICES = [
    "en-US-AndrewMultilingualNeural",
    "en-US-AvaMultilingualNeural",
    "en-US-BrianMultilingualNeural",
    "en-US-EmmaMultilingualNeural",
    "en-GB-SoniaNeural",
    "en-GB-RyanNeural",
    "en-AU-NatashaNeural",
    "en-AU-WilliamNeural",
    "en-IN-NeerjaNeural",
]


def sanitize_spoken_text(text: str) -> str:
    text = text.replace("&", " and ")
    text = re.sub(r"[<>]", " ", text)
    text = re.sub(r"https?://\S+", " link ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_tts_chunks(text: str) -> list[str]:
    text = text.strip()
    if len(text) <= MAX_TTS_CHARS:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= MAX_TTS_CHARS:
            chunks.append(remaining.strip())
            break
        window = remaining[:MAX_TTS_CHARS]
        split_at = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("? "), window.rfind("! "))
        if split_at < MAX_TTS_CHARS * 0.4:
            split_at = window.rfind(" ")
        if split_at < 1:
            split_at = MAX_TTS_CHARS
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    return [c for c in chunks if c]


def _align_words(text: str, boundaries: list[dict[str, Any]], time_offset: float, char_offset: int) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    cursor = 0
    for boundary in boundaries:
        word = str(boundary.get("text") or "")
        if not word.strip():
            continue
        idx = text.find(word, cursor)
        if idx < 0:
            idx = text.lower().find(word.lower(), cursor)
        if idx < 0:
            idx = cursor
        start_char = idx
        end_char = min(len(text), idx + len(word))
        start = time_offset + float(boundary["offset"]) / 10_000_000
        end = start + float(boundary.get("duration") or 0) / 10_000_000
        cues.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "text": word,
                "charStart": char_offset + start_char,
                "charEnd": char_offset + end_char,
            }
        )
        cursor = end_char
    return cues


async def synthesize_chapter(text: str, voice: str, mp3_path: Path) -> tuple[float, list[dict[str, Any]]]:
    chunks = split_tts_chunks(text)
    audio = bytearray()
    cues: list[dict[str, Any]] = []
    time_offset = 0.0
    search_from = 0

    for chunk in chunks:
        spoken = sanitize_spoken_text(chunk)
        if not spoken:
            search_from += len(chunk)
            continue
        communicate = edge_tts.Communicate(spoken, voice)
        chunk_audio = bytearray()
        boundaries: list[dict[str, Any]] = []
        async for message in communicate.stream():
            kind = message.get("type")
            if kind == "audio":
                chunk_audio.extend(message["data"])
            elif kind == "WordBoundary":
                boundaries.append(message)

        duration = 0.0
        if boundaries:
            last = boundaries[-1]
            duration = (float(last["offset"]) + float(last.get("duration") or 0)) / 10_000_000
        if duration <= 0 and chunk_audio:
            duration = max(0.8, len(chunk_audio) / 16000)

        local = text.find(chunk, search_from)
        char_offset = local if local >= 0 else search_from
        cues.extend(_align_words(chunk, boundaries, time_offset, char_offset))
        audio.extend(chunk_audio)
        time_offset += duration
        search_from = char_offset + len(chunk)

    if not audio:
        raise RuntimeError("Narration produced no audio")
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = mp3_path.with_suffix(".part.mp3")
    tmp.write_bytes(bytes(audio))
    tmp.replace(mp3_path)
    return round(time_offset, 3), cues


async def synthesize_chapter_retry(text: str, voice: str, mp3_path: Path) -> tuple[float, list[dict[str, Any]]]:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            return await synthesize_chapter(text, voice, mp3_path)
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(1.6 * (attempt + 1))
    assert last_error is not None
    raise last_error


PREVIEW_LINE = "This is how I will sound when I read your book. Settle in, and follow along."


async def preview_voice(voice: str, mp3_path: Path) -> None:
    if mp3_path.exists() and mp3_path.stat().st_size > 1000:
        return
    await synthesize_chapter_retry(PREVIEW_LINE, voice, mp3_path)


async def list_english_voices() -> list[dict[str, str]]:
    voices = await edge_tts.list_voices()
    english = [
        {
            "short_name": v["ShortName"],
            "locale": v["Locale"],
            "gender": v["Gender"],
            "label": f"{v['FriendlyName'].replace('Microsoft ', '').replace('Online (Natural)', '').strip()} ({v['Locale']})",
        }
        for v in voices
        if str(v.get("Locale", "")).startswith("en")
    ]
    preferred = []
    seen = set()
    by_name = {v["short_name"]: v for v in english}
    for name in PREFERRED_VOICES:
        if name in by_name:
            preferred.append(by_name[name])
            seen.add(name)
    rest = [v for v in english if v["short_name"] not in seen]
    rest.sort(key=lambda v: v["label"])
    return preferred + rest
