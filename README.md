# Finland Tile Server

Local tile server for **Finland** in this workspace, with an added **offline MBTiles** mode.

## Included modes

- `server.py` — serves tiles at `http://127.0.0.1:8080/tiles/{z}/{x}/{y}.png`
- `build_finland_mbtiles.py` — builds `data/finland.mbtiles` for offline use

The server checks sources in this order:

1. `data/finland.mbtiles`
2. `data/cache/`
3. OpenStreetMap upstream fallback, unless `OFFLINE_ONLY=1`

> This setup is intended for **local development/testing** only. Please keep downloads light and respect the OpenStreetMap tile usage policy.

## Quick start

### 1) Build an offline Finland MBTiles file

```bash
cd /home/haba/tileserver
python3 build_finland_mbtiles.py --min-zoom 0 --max-zoom 6
```

This creates:

- `data/finland.mbtiles`

### 2) Start the server

Online fallback allowed:

```bash
python3 server.py
```

Offline-only mode:

```bash
OFFLINE_ONLY=1 python3 server.py
```

### 3) Open

- `http://127.0.0.1:8080/`
- `http://127.0.0.1:8080/healthz`
- `http://127.0.0.1:8080/tiles/6/36/18.png`

## Optional settings

```bash
PORT=8090 MBTILES_PATH=data/finland.mbtiles OFFLINE_ONLY=1 python3 server.py
```

## Environment variables

- `HOST` (default `0.0.0.0`)
- `PORT` (default `8080`)
- `CACHE_DIR` (default `data/cache`)
- `MBTILES_PATH` (default `data/finland.mbtiles`)
- `OFFLINE_ONLY` (`1` disables upstream fetching)
- `UPSTREAM_TEMPLATE` (default `https://tile.openstreetmap.org/{z}/{x}/{y}.png`)
- `MIN_ZOOM` (default `0`)
- `MAX_ZOOM` (default `16`)
- `TILESERVER_USER_AGENT` (custom user agent for upstream requests)

## Notes

- The default MBTiles builder creates a **small local offline set** for Finland through zoom 6.
- You can raise `--max-zoom`, but downloads and file size will grow quickly.
- The sample Helsinki tile is `z=6, x=36, y=18`.
