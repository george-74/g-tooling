# g-tooling

Standalone tooling library editor for G-NodeCAM.

## Features
- Manage tool records and defaults in a single SQLite database
- Store per-tool capabilities for supported job types
- Keep extra extensible fields in JSON without schema breaks
- Serve a browser UI using only the Python standard library

## Stack
- Python 3
- SQLite
- Vanilla HTML, CSS, and JavaScript

## Run
```bash
cd g-tooling
python3 app.py
```

Open `http://127.0.0.1:8765`.

## Database
Default database path: `data/tooling.db`

Override with an environment variable:
```bash
TOOLING_DB=/path/to/tooling.db python3 app.py
```

The UI can also switch database paths at runtime. Local app settings are stored in `data/settings.json`, which is intentionally ignored by git.

## Git Notes
- `data/*.db` is ignored so local SQLite files do not get committed
- `data/settings.json` is ignored because it contains machine-specific settings
- `__pycache__/` and Python bytecode are ignored
