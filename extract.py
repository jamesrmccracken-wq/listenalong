from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import mammoth
from pypdf import PdfReader

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".idea",
    ".vs",
    "dist",
    "build",
    ".next",
    "target",
}

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".org",
    ".csv",
    ".log",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".xml",
    ".html",
    ".htm",
    ".css",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".sql",
    ".sh",
    ".ps1",
    ".bat",
    ".r",
    ".lua",
    ".scala",
}

DOC_EXTENSIONS = {".pdf", ".docx", ".epub"}
SUPPORTED = TEXT_EXTENSIONS | DOC_EXTENSIONS | {".zip"}

MAX_CHAPTER_CHARS = 4500
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_BOOK_CHARS = 2_000_000


@dataclass
class ExtractedChapter:
    title: str
    text: str


def is_supported(name: str) -> bool:
    return Path(name).suffix.lower() in SUPPORTED


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def title_from_name(name: str) -> str:
    stem = Path(name).stem.replace("_", " ").replace("-", " ").strip()
    return re.sub(r"\s+", " ", stem) or "Untitled"


def split_into_chapters(title: str, text: str) -> list[ExtractedChapter]:
    text = clean_text(text)
    if not text:
        return []

    blocks = _split_blocks(text)
    chapters: list[ExtractedChapter] = []
    current_title = title
    current: list[str] = []
    current_len = 0
    part = 1

    def flush(force_title: str | None = None) -> None:
        nonlocal current, current_len, part, current_title
        body = clean_text("\n\n".join(current))
        if not body:
            current, current_len = [], 0
            return
        label = force_title or current_title
        if chapters and label == title:
            label = f"{title} · part {part}"
            part += 1
        elif chapters and label == current_title and current_title != title:
            label = f"{current_title} · continued"
        chapters.append(ExtractedChapter(title=label, text=body))
        current, current_len = [], 0

    heading_re = re.compile(r"^(#{1,3})\s+(.+)$", re.M)

    for block in blocks:
        heading = heading_re.match(block)
        if heading and current:
            flush()
            current_title = heading.group(2).strip()
            current.append(block)
            current_len = len(block)
            continue
        if current_len + len(block) + 2 > MAX_CHAPTER_CHARS and current:
            flush()
            current_title = title
        current.append(block)
        current_len += len(block) + 2

    flush()
    return chapters


def _split_blocks(text: str) -> list[str]:
    raw = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    return raw or [text]


def extract_path(path: Path, display_name: str | None = None) -> list[ExtractedChapter]:
    name = display_name or path.name
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return extract_zip(path, title_from_name(name))
    if suffix == ".pdf":
        return extract_pdf(path, title_from_name(name))
    if suffix == ".docx":
        return extract_docx(path, title_from_name(name))
    if suffix == ".epub":
        return extract_epub(path, title_from_name(name))
    text = path.read_text(encoding="utf-8", errors="ignore")
    if suffix in {".md", ".markdown"}:
        text = _soften_markdown(text)
    elif suffix in {".html", ".htm"}:
        text = _html_to_text(text)
    return split_into_chapters(title_from_name(name), text)


def extract_bytes(filename: str, data: bytes, work_dir: Path) -> list[ExtractedChapter]:
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"{filename} is larger than 40 MB")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"Unsupported file type: {suffix or filename}")
    dest = work_dir / Path(filename).name
    dest.write_bytes(data)
    chapters = extract_path(dest, filename)
    total = sum(len(ch.text) for ch in chapters)
    if total > MAX_BOOK_CHARS:
        raise ValueError("That folder or document is too large to narrate in one go")
    return chapters


def extract_zip(path: Path, fallback_title: str) -> list[ExtractedChapter]:
    chapters: list[ExtractedChapter] = []
    with zipfile.ZipFile(path) as zf:
        names = sorted(
            n
            for n in zf.namelist()
            if not n.endswith("/")
            and not any(part in SKIP_DIRS for part in Path(n).parts)
            and is_supported(n)
            and Path(n).suffix.lower() != ".zip"
        )
        if not names:
            raise ValueError("No readable documents were found in that folder")
        nested_dir = path.parent / "_unzip"
        nested_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            info = zf.getinfo(name)
            if info.file_size > MAX_FILE_BYTES:
                continue
            data = zf.read(name)
            nested = extract_bytes(Path(name).name, data, nested_dir)
            if len(nested) == 1:
                nested[0].title = title_from_name(name)
            else:
                for i, ch in enumerate(nested, start=1):
                    ch.title = f"{title_from_name(name)} · {ch.title if ch.title else i}"
            chapters.extend(nested)
    return chapters or [ExtractedChapter(title=fallback_title, text="")]


def extract_pdf(path: Path, title: str) -> list[ExtractedChapter]:
    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(clean_text(page.extract_text() or ""))
    text = clean_text("\n\n".join(p for p in pages if p))
    if not text:
        raise ValueError("No text could be extracted from that PDF (it may be scanned images)")
    return split_into_chapters(title, text)


def extract_docx(path: Path, title: str) -> list[ExtractedChapter]:
    with path.open("rb") as fh:
        result = mammoth.convert_to_html(fh)
    text = _html_to_text(result.value)
    if not text:
        raise ValueError("That Word document appears to be empty")
    return split_into_chapters(title, text)


def extract_epub(path: Path, fallback_title: str) -> list[ExtractedChapter]:
    chapters: list[ExtractedChapter] = []
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        opf_name = next((n for n in names if n.endswith(".opf")), None)
        spine_hrefs: list[str] = []
        book_title = fallback_title
        if opf_name:
            root = ET.fromstring(zf.read(opf_name))
            ns = {"n": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
            title_el = root.find(".//dc:title", ns)
            if title_el is not None and title_el.text:
                book_title = title_el.text.strip()
            manifest = {
                item.attrib.get("id"): item.attrib.get("href")
                for item in root.findall(".//n:item", ns)
            }
            base = str(Path(opf_name).parent).replace("\\", "/")
            if base == ".":
                base = ""
            for itemref in root.findall(".//n:itemref", ns):
                href = manifest.get(itemref.attrib.get("idref"))
                if not href:
                    continue
                spine_hrefs.append(f"{base}/{href}".lstrip("/").replace("/./", "/"))
        if not spine_hrefs:
            spine_hrefs = sorted(n for n in names if n.lower().endswith((".xhtml", ".html", ".htm")))
        for href in spine_hrefs:
            match = next((n for n in names if n.replace("\\", "/") == href or n.endswith(href)), None)
            if not match:
                continue
            html = zf.read(match).decode("utf-8", errors="ignore")
            text = _html_to_text(html)
            if len(text) < 40:
                continue
            heading = _first_heading(html) or title_from_name(match)
            chapters.extend(split_into_chapters(heading, text))
    if not chapters:
        raise ValueError("No readable chapters were found in that EPUB")
    if book_title and chapters and chapters[0].title != book_title:
        pass
    return chapters


def _first_heading(html: str) -> str | None:
    match = re.search(r"<h[1-3][^>]*>(.*?)</h[1-3]>", html, re.I | re.S)
    if not match:
        return None
    return clean_text(_html_to_text(match.group(1))) or None


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|li|tr|section|article)>", "\n\n", html)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"&nbsp;", " ", html)
    html = re.sub(r"&amp;", "&", html)
    html = re.sub(r"&lt;", "<", html)
    html = re.sub(r"&gt;", ">", html)
    html = re.sub(r"&#39;|&apos;", "'", html)
    html = re.sub(r"&quot;", '"', html)
    return clean_text(html)


def _soften_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"[*_~]{1,3}", "", text)
    return text
