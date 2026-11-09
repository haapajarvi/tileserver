#!/usr/bin/env python3
"""Local tile server for Finland.

Priority order for tile requests:
1. `data/finland.mbtiles` (offline MBTiles)
2. `data/cache/` local PNG cache
3. OpenStreetMap upstream fallback, unless `OFFLINE_ONLY=1`

This is intended for local development and testing.
"""

from __future__ import annotations

import html
import math
import os
import re
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))
CACHE_DIR = Path(os.getenv("CACHE_DIR", "data/cache"))
MBTILES_PATH = Path(os.getenv("MBTILES_PATH", "data/finland.mbtiles"))
UPSTREAM_TEMPLATE = os.getenv(
    "UPSTREAM_TEMPLATE", "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
)
MIN_ZOOM = int(os.getenv("MIN_ZOOM", "0"))
MAX_ZOOM = int(os.getenv("MAX_ZOOM", "16"))
OFFLINE_ONLY = os.getenv("OFFLINE_ONLY", "0").lower() in {"1", "true", "yes", "on"}
USER_AGENT = os.getenv(
    "TILESERVER_USER_AGENT", "FinlandLocalTileServer/1.1 (local development)"
)

# Rough Finland bounds: west, south, east, north
FINLAND_BOUNDS = (19.0, 59.0, 32.2, 70.5)
TILE_PATH_RE = re.compile(r"^/tiles/(\d+)/(\d+)/(\d+)\.png$")


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    n = 2**z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0

    def lat(tile_y: int) -> float:
        value = math.atan(math.sinh(math.pi * (1 - 2 * tile_y / n)))
        return math.degrees(value)

    north = lat(y)
    south = lat(y + 1)
    return (west, south, east, north)


def intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def mbtiles_row(z: int, y: int) -> int:
    return (2**z - 1) - y


def guess_content_type(data: bytes, tile_format: str | None = None) -> str:
    known = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "pbf": "application/x-protobuf",
        "mvt": "application/x-protobuf",
    }
    if tile_format:
        content_type = known.get(tile_format.lower())
        if content_type:
            return content_type
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def lookup_mbtiles(z: int, x: int, y: int) -> tuple[bytes, str] | None:
    if not MBTILES_PATH.exists():
        return None

    try:
        with sqlite3.connect(MBTILES_PATH) as conn:
            row = conn.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
                (z, x, mbtiles_row(z, y)),
            ).fetchone()
            if not row:
                return None
            fmt = conn.execute(
                "SELECT value FROM metadata WHERE name = 'format'"
            ).fetchone()
    except sqlite3.Error:
        return None

    tile_data = row[0]
    tile_format = fmt[0] if fmt else None
    return tile_data, guess_content_type(tile_data, tile_format)


class TileHandler(BaseHTTPRequestHandler):
    server_version = "FinlandTileServer/1.1"

    def do_GET(self) -> None:
        self.handle_request(head_only=False)

    def do_HEAD(self) -> None:
        self.handle_request(head_only=True)

    def handle_request(self, head_only: bool) -> None:
        if self.path in {"/", "/index.html"}:
            self.serve_index(head_only=head_only)
            return

        if self.path == "/healthz":
            payload = b'{"status":"ok"}'
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)
            return

        match = TILE_PATH_RE.match(self.path)
        if not match:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown route")
            return

        z, x, y = map(int, match.groups())
        max_index = 2**z - 1
        if z < MIN_ZOOM or z > MAX_ZOOM or x < 0 or y < 0 or x > max_index or y > max_index:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid tile coordinates")
            return

        if not intersects(tile_bounds(z, x, y), FINLAND_BOUNDS):
            self.send_error(HTTPStatus.NOT_FOUND, "Tile outside Finland bounds")
            return

        self.serve_tile(z, x, y, head_only=head_only)

    def serve_index(self, head_only: bool = False) -> None:
        example = "/tiles/6/36/18.png"
        mbtiles_status = "present" if MBTILES_PATH.exists() else "not found"
        offline_status = "enabled" if OFFLINE_ONLY else "disabled"
        html_body = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Finland Tile Server</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 760px; margin: 2rem auto; padding: 0 1rem; }}
    code {{ background: #f3f4f6; padding: 0.1rem 0.35rem; border-radius: 4px; }}
    .card {{ border: 1px solid #e5e7eb; border-radius: 10px; padding: 1rem; margin-top: 1rem; }}
  </style>
</head>
<body>
  <h1>Finland Tile Server</h1>
  <p>This local server prefers offline MBTiles for Finland and falls back to the local cache or upstream when allowed.</p>
  <div class=\"card\">
    <p><strong>Health:</strong> <code>/healthz</code></p>
    <p><strong>Tile endpoint:</strong> <code>/tiles/{{z}}/{{x}}/{{y}}.png</code></p>
    <p><strong>Example tile:</strong> <a href=\"{html.escape(example)}\">{html.escape(example)}</a></p>
    <p><strong>MBTiles:</strong> <code>{html.escape(str(MBTILES_PATH))}</code> ({html.escape(mbtiles_status)})</p>
    <p><strong>Cache directory:</strong> <code>{html.escape(str(CACHE_DIR))}</code></p>
    <p><strong>Offline only:</strong> <code>{html.escape(offline_status)}</code></p>
  </div>
  <p>For a local offline database, run <code>python3 build_finland_mbtiles.py</code> first.</p>
</body>
</html>"""
        payload = html_body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)

    def serve_tile(self, z: int, x: int, y: int, head_only: bool = False) -> None:
        mbtile = lookup_mbtiles(z, x, y)
        if mbtile is not None:
            data, content_type = mbtile
            self.respond_with_bytes(data, content_type=content_type, head_only=head_only)
            return

        tile_path = CACHE_DIR / str(z) / str(x) / f"{y}.png"
        tile_path.parent.mkdir(parents=True, exist_ok=True)
        if tile_path.exists():
            self.respond_with_file(tile_path, head_only=head_only)
            return

        if OFFLINE_ONLY:
            self.send_error(HTTPStatus.NOT_FOUND, "Tile not found locally while OFFLINE_ONLY=1")
            return

        url = UPSTREAM_TEMPLATE.format(z=z, x=x, y=y)
        request = Request(url, headers={"User-Agent": USER_AGENT})

        try:
            with urlopen(request, timeout=20) as response:
                data = response.read()
        except HTTPError as exc:
            self.send_error(exc.code, f"Upstream tile fetch failed: {exc.reason}")
            return
        except URLError as exc:
            self.send_error(HTTPStatus.BAD_GATEWAY, f"Upstream unreachable: {exc.reason}")
            return

        tile_path.write_bytes(data)
        self.respond_with_file(tile_path, head_only=head_only)

    def respond_with_file(self, file_path: Path, head_only: bool = False) -> None:
        self.respond_with_bytes(file_path.read_bytes(), content_type="image/png", head_only=head_only)

    def respond_with_bytes(self, data: bytes, content_type: str, head_only: bool = False) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} - {fmt % args}")


if __name__ == "__main__":
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), TileHandler)
    print(f"Serving Finland tiles on http://{HOST}:{PORT}")
    print(f"MBTiles path: {MBTILES_PATH.resolve()} (exists={MBTILES_PATH.exists()})")
    print(f"Cache directory: {CACHE_DIR.resolve()}")
    print(f"Offline only mode: {OFFLINE_ONLY}")
    server.serve_forever()
