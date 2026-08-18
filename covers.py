from __future__ import annotations

import hashlib
from xml.sax.saxutils import escape


PALETTES = [
    ("#1b3a4b", "#0e1c24", "#e8c07a"),
    ("#3b1d2f", "#160a12", "#f2a65a"),
    ("#1f3d2b", "#0c1812", "#d7e3a1"),
    ("#2c2156", "#120c28", "#f0b7c8"),
    ("#4a1f12", "#1a0b07", "#f4d58d"),
    ("#163a4a", "#07151c", "#7fd1c5"),
    ("#3a2a12", "#140e06", "#f0c27b"),
    ("#1a2744", "#0a1020", "#c9b8ff"),
]


def cover_svg(book_id: int, title: str, author: str, narrator: str, hue: int = 18) -> str:
    digest = hashlib.sha256(f"{book_id}:{title}".encode()).digest()
    palette = PALETTES[digest[0] % len(PALETTES)]
    c1, c2, ink = palette
    pattern = digest[1] % 4
    initials = "".join(part[0] for part in title.split()[:2]).upper() or "LA"
    safe_title = escape(title[:48])
    safe_author = escape((author or "Unknown")[:32])
    safe_narrator = escape((narrator or "")[:28])
    shapes = _pattern(pattern, ink)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 600">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{c1}"/>
      <stop offset="1" stop-color="{c2}"/>
    </linearGradient>
  </defs>
  <rect width="400" height="600" fill="url(#g)"/>
  <rect x="0" y="0" width="22" height="600" fill="#000" opacity="0.28"/>
  {shapes}
  <text x="48" y="78" fill="{ink}" font-family="Georgia, serif" font-size="42" font-weight="700">{escape(initials)}</text>
  <rect x="48" y="96" width="72" height="4" fill="{ink}" opacity="0.8"/>
  <text x="48" y="430" fill="#f7f3ea" font-family="Georgia, serif" font-size="28" font-weight="700">
    <tspan x="48" dy="0">{escape(_wrap(title, 0))}</tspan>
    <tspan x="48" dy="34">{escape(_wrap(title, 1))}</tspan>
    <tspan x="48" dy="34">{escape(_wrap(title, 2))}</tspan>
  </text>
  <text x="48" y="548" fill="#f7f3ea" opacity="0.8" font-family="Manrope, sans-serif" font-size="14">{safe_author}</text>
  <text x="48" y="572" fill="{ink}" font-family="Manrope, sans-serif" font-size="12">Narrated by {safe_narrator}</text>
</svg>
"""


def _wrap(title: str, line: int) -> str:
    words = title.split()
    lines = ["", "", ""]
    idx = 0
    for word in words:
        trial = (lines[idx] + " " + word).strip()
        if len(trial) > 18 and idx < 2:
            idx += 1
            lines[idx] = word
        else:
            lines[idx] = trial
    return lines[line]


def _pattern(kind: int, ink: str) -> str:
    if kind == 0:
        return f'<circle cx="300" cy="160" r="90" fill="{ink}" opacity="0.16"/><circle cx="330" cy="210" r="40" fill="{ink}" opacity="0.2"/>'
    if kind == 1:
        return '<path d="M80 140h240l-40 120H120z" fill="#fff" opacity="0.06"/>'
    if kind == 2:
        return "".join(f'<rect x="{60 + i * 28}" y="130" width="10" height="{80 + (i % 4) * 18}" fill="#fff" opacity="0.08"/>' for i in range(9))
    return f'<ellipse cx="270" cy="180" rx="120" ry="50" fill="{ink}" opacity="0.14"/>'
