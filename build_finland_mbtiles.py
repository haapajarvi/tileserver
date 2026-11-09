#!/usr/bin/env python3
"""Build a small offline Finland MBTiles database from raster OSM tiles.

This intentionally uses only the Python standard library so it can run in this
workspace without extra dependencies. It is meant for local development use.
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import time
from pathlib import Path
from urllib.request import Request, urlopen

FINLAND_BOUNDS = (19.0, 59.0, 32.2, 70.5)
DEFAULT_OUTPUT = Path("data/finland.mbtiles")
DEFAULT_TEMPLATE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
DEFAULT_USER_AGENT = "FinlandMBTilesBuilder/1.0 (local development)"


def lon_to_tile_x(lon: float, zoom: int) -> int:
    return int((lon + 180.0) / 360.0 * (2**zoom))


def lat_to_tile_y(lat: float, zoom: int) -> int:
    return int(
        (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * (2**zoom)
    )


def mbtiles_row(zoom: int, y: int) -> int:
    return (2**zoom - 1) - y


def iter_finland_tiles(min_zoom: int, max_zoom: int):
    west, south, east, north = FINLAND_BOUNDS
    for zoom in range(min_zoom, max_zoom + 1):
        max_index = 2**zoom - 1
        x_min = max(0, min(max_index, lon_to_tile_x(west, zoom)))
        x_max = max(0, min(max_index, lon_to_tile_x(east, zoom)))
        y_min = max(0, min(max_index, lat_to_tile_y(north, zoom)))
        y_max = max(0, min(max_index, lat_to_tile_y(south, zoom)))
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                yield zoom, x, y


def ensure_schema(conn: sqlite3.Connection, min_zoom: int, max_zoom: int) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS tiles (
            zoom_level INTEGER,
            tile_column INTEGER,
            tile_row INTEGER,
            tile_data BLOB,
            PRIMARY KEY (zoom_level, tile_column, tile_row)
        );
        """
    )
    west, south, east, north = FINLAND_BOUNDS
    center_lon = (west + east) / 2
    center_lat = (south + north) / 2
    metadata = {
        "name": "Finland raster tiles",
        "type": "baselayer",
        "version": "1",
        "description": "Offline raster MBTiles for Finland built from OSM standard tiles",
        "format": "png",
        "bounds": f"{west},{south},{east},{north}",
        "center": f"{center_lon},{center_lat},{min_zoom}",
        "minzoom": str(min_zoom),
        "maxzoom": str(max_zoom),
    }
    for key, value in metadata.items():
        conn.execute(
            "INSERT OR REPLACE INTO metadata(name, value) VALUES(?, ?)",
            (key, value),
        )
    conn.commit()


def has_tile(conn: sqlite3.Connection, zoom: int, x: int, y: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM tiles WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
        (zoom, x, mbtiles_row(zoom, y)),
    ).fetchone()
    return row is not None


def save_tile(conn: sqlite3.Connection, zoom: int, x: int, y: int, data: bytes) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO tiles(zoom_level, tile_column, tile_row, tile_data)
        VALUES(?, ?, ?, ?)
        """,
        (zoom, x, mbtiles_row(zoom, y), data),
    )


def build_mbtiles(output: Path, min_zoom: int, max_zoom: int, delay: float, template: str, user_agent: str) -> tuple[int, int]:
    output.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(output)
    ensure_schema(conn, min_zoom, max_zoom)

    downloaded = 0
    skipped = 0
    try:
        for zoom, x, y in iter_finland_tiles(min_zoom, max_zoom):
            if has_tile(conn, zoom, x, y):
                skipped += 1
                continue

            url = template.format(z=zoom, x=x, y=y)
            print(f"Downloading z={zoom} x={x} y={y} -> {url}")
            request = Request(url, headers={"User-Agent": user_agent})
            with urlopen(request, timeout=30) as response:
                data = response.read()
            save_tile(conn, zoom, x, y, data)
            conn.commit()
            downloaded += 1
            if delay > 0:
                time.sleep(delay)
    finally:
        conn.close()

    return downloaded, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Build offline Finland MBTiles")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output MBTiles path")
    parser.add_argument("--min-zoom", type=int, default=0, help="Minimum zoom level")
    parser.add_argument("--max-zoom", type=int, default=6, help="Maximum zoom level")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between downloads in seconds")
    parser.add_argument("--template", default=DEFAULT_TEMPLATE, help="Upstream raster tile URL template")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="User-Agent header")
    args = parser.parse_args()

    if args.min_zoom < 0 or args.max_zoom < args.min_zoom:
        raise SystemExit("Invalid zoom range")

    downloaded, skipped = build_mbtiles(
        output=Path(args.output),
        min_zoom=args.min_zoom,
        max_zoom=args.max_zoom,
        delay=args.delay,
        template=args.template,
        user_agent=args.user_agent,
    )
    print(f"Done. Downloaded {downloaded} new tiles, skipped {skipped} existing tiles.")
    print(f"MBTiles written to: {Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
