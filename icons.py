from __future__ import annotations

import struct
import zlib
from pathlib import Path


def ensure_icons(static_dir: Path) -> None:
    icons = static_dir / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        path = icons / f"icon-{size}.png"
        if not path.exists():
            _write_play_icon(path, size)


def _write_play_icon(path: Path, size: int) -> None:
    bg = (240, 162, 2, 255)
    fg = (20, 16, 12, 255)
    pixels = bytearray()
    cx = cy = size / 2
    r = size * 0.34
    for y in range(size):
        for x in range(size):
            # rounded square mask
            m = size * 0.18
            if x < m and y < m and (m - x) ** 2 + (m - y) ** 2 > m * m:
                pixels.extend((0, 0, 0, 0))
                continue
            if x > size - m and y < m and (x - (size - m)) ** 2 + (m - y) ** 2 > m * m:
                pixels.extend((0, 0, 0, 0))
                continue
            if x < m and y > size - m and (m - x) ** 2 + (y - (size - m)) ** 2 > m * m:
                pixels.extend((0, 0, 0, 0))
                continue
            if x > size - m and y > size - m and (x - (size - m)) ** 2 + (y - (size - m)) ** 2 > m * m:
                pixels.extend((0, 0, 0, 0))
                continue
            # play triangle
            px = (x - (cx - r * 0.35)) / (r * 1.25)
            py = (y - (cy - r)) / (2 * r)
            if 0 <= py <= 1 and px >= py * 0.55 and px <= 0.9 - py * 0.55:
                pixels.extend(fg)
            else:
                pixels.extend(bg)

    raw = b"".join(b"\x00" + pixels[i * size * 4 : (i + 1) * size * 4] for i in range(size))
    compressed = zlib.compress(raw, 9)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")
    path.write_bytes(png)
