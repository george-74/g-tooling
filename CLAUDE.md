# G-Tooling — Claude Instructions

## Overview
- Standalone Python web app — SQLite DB editor for CNC tool catalog
- Runs on a Debian server, serves on `http://127.0.0.1:8765`
- G-NodeCAM (sibling repo at `../G-NodeCAM/`) downloads the DB for local lookup via `ToolLibrary.cpp`
- When working on DB schema changes, check `../G-NodeCAM/src/model/ToolLibrary.cpp` for how G-NodeCAM reads the DB

## Stack
- Python 3 standard library only (no dependencies)
- SQLite (single file DB)
- Vanilla HTML/CSS/JS frontend

## Key files
- `app.py` — server and all API endpoints
- `static/index.html` — single-page UI
- `static/app.js` — frontend logic
- `static/styles.css` — styling
- `data/tooling.db` — SQLite database (gitignored)
- `data/settings.json` — local settings (gitignored)
