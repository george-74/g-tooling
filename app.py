#!/usr/bin/env python3
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DEFAULT_DB_PATH = BASE_DIR / "data" / "tooling.db"
SETTINGS_PATH = BASE_DIR / "data" / "settings.json"
ENV_DB_PATH = os.environ.get("TOOLING_DB", "").strip()
HOST = "0.0.0.0"
PORT = 8765

_db_path_lock = threading.RLock()
_db_path_value = ""

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS tools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number INTEGER NOT NULL CHECK (number BETWEEN 100 AND 999),
    name TEXT NOT NULL,
    diameter REAL NOT NULL CHECK (diameter > 0),
    color TEXT NOT NULL DEFAULT '#6BA4FF',
    can_plunge INTEGER NOT NULL DEFAULT 1 CHECK (can_plunge IN (0, 1)),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    aliases TEXT NOT NULL DEFAULT '',
    store_pos INTEGER NOT NULL DEFAULT 0,
    d_corrector INTEGER NOT NULL DEFAULT 0,
    comment TEXT NOT NULL DEFAULT '',
    flutes_num INTEGER NOT NULL DEFAULT 0,
    flutes_length REAL NOT NULL DEFAULT 0,
    flutes_coating TEXT NOT NULL DEFAULT '',
    flutes_type TEXT NOT NULL DEFAULT '',
    shank REAL NOT NULL DEFAULT 0,
    max_depth REAL NOT NULL DEFAULT 0,
    max_working_depth REAL NOT NULL DEFAULT 0,
    depth_per_pass REAL NOT NULL DEFAULT 0,
    extras TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tools_active_number
    ON tools(number) WHERE active = 1;

CREATE TABLE IF NOT EXISTS job_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS tool_capabilities (
    tool_id INTEGER NOT NULL,
    job_type_id INTEGER NOT NULL,
    PRIMARY KEY (tool_id, job_type_id),
    FOREIGN KEY (tool_id) REFERENCES tools(id) ON DELETE CASCADE,
    FOREIGN KEY (job_type_id) REFERENCES job_types(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tool_defaults_global (
    tool_id INTEGER PRIMARY KEY,
    speed REAL,
    feed REAL,
    plunge REAL,
    ramp REAL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (tool_id) REFERENCES tools(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tool_defaults_by_job (
    tool_id INTEGER NOT NULL,
    job_type_id INTEGER NOT NULL,
    speed REAL,
    feed REAL,
    plunge REAL,
    ramp REAL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tool_id, job_type_id),
    FOREIGN KEY (tool_id) REFERENCES tools(id) ON DELETE CASCADE,
    FOREIGN KEY (job_type_id) REFERENCES job_types(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS node_job_map (
    node_name TEXT PRIMARY KEY,
    job_code TEXT NOT NULL,
    FOREIGN KEY (job_code) REFERENCES job_types(code) ON DELETE CASCADE
);
"""

SEED_JOB_TYPES = [
    ("chamfering", "Chamfering"),
    ("corner_clearing", "Corner Clearing"),
    ("cutting", "Cutting"),
    ("drilling", "Drilling"),
    ("engraving", "Engraving"),
    ("facing", "Facing"),
    ("filleting", "Filleting"),
    ("pocketing", "Pocketing"),
    ("slotting", "Slotting"),
    ("t_slot_cutting", "T-Slot Cutting"),
]

SEED_NODE_MAP = [
    ("GridCut", "cutting"),
    ("BackCut", "cutting"),
    ("PocketMill", "pocketing"),
    ("PocketFillet", "filleting"),
    ("OuterFillet", "filleting"),
    ("HangerHole", "drilling"),
]

# Columns added in schema v2
V2_COLUMNS = [
    ("aliases", "TEXT NOT NULL DEFAULT ''"),
    ("store_pos", "INTEGER NOT NULL DEFAULT 0"),
    ("d_corrector", "INTEGER NOT NULL DEFAULT 0"),
    ("comment", "TEXT NOT NULL DEFAULT ''"),
    ("flutes_num", "INTEGER NOT NULL DEFAULT 0"),
    ("flutes_length", "REAL NOT NULL DEFAULT 0"),
    ("flutes_coating", "TEXT NOT NULL DEFAULT ''"),
    ("flutes_type", "TEXT NOT NULL DEFAULT ''"),
    ("shank", "REAL NOT NULL DEFAULT 0"),
    ("max_depth", "REAL NOT NULL DEFAULT 0"),
    ("max_working_depth", "REAL NOT NULL DEFAULT 0"),
    ("depth_per_pass", "REAL NOT NULL DEFAULT 0"),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


DEFAULT_ADMIN_PASSWORD = "root3251"


def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def get_admin_password() -> str:
    return load_settings().get("adminPassword", DEFAULT_ADMIN_PASSWORD)


def set_admin_password(new_password: str) -> None:
    data = load_settings()
    data["adminPassword"] = new_password
    save_settings(data)


def save_settings(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(data, ensure_ascii=True, separators=(",", ":")),
        encoding="utf-8",
    )


def normalize_db_path(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError("dbPath is required")
    return str(Path(value).expanduser())


def resolve_initial_db_path() -> str:
    if ENV_DB_PATH:
        return normalize_db_path(ENV_DB_PATH)

    remembered = load_settings().get("dbPath", "")
    if remembered:
        return normalize_db_path(str(remembered))

    return str(DEFAULT_DB_PATH)


def get_db_path() -> str:
    with _db_path_lock:
        return _db_path_value


def set_db_path(path: str, remember: bool = True) -> None:
    normalized = normalize_db_path(path)
    with _db_path_lock:
        global _db_path_value
        _db_path_value = normalized
    if remember:
        data = load_settings()
        data["dbPath"] = normalized
        save_settings(data)


def db_connect() -> sqlite3.Connection:
    db_path = Path(get_db_path())
    if not db_path.parent.exists():
        raise ValueError(f"Directory does not exist: {db_path.parent}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Migrate from schema v1 (number UNIQUE) to v2 (number non-unique, new columns)."""
    # Check which columns already exist
    cursor = conn.execute("PRAGMA table_info(tools)")
    existing_cols = {row["name"] for row in cursor.fetchall()}

    # Add missing columns
    for col_name, col_def in V2_COLUMNS:
        if col_name not in existing_cols:
            conn.execute(f"ALTER TABLE tools ADD COLUMN {col_name} {col_def}")

    # Recreate the table to remove UNIQUE on number
    # Check if the old unique constraint exists by trying to insert a duplicate
    # Simpler: just recreate the table
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tools_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number INTEGER NOT NULL CHECK (number BETWEEN 100 AND 999),
            name TEXT NOT NULL,
            diameter REAL NOT NULL CHECK (diameter > 0),
            color TEXT NOT NULL DEFAULT '#6BA4FF',
            can_plunge INTEGER NOT NULL DEFAULT 1 CHECK (can_plunge IN (0, 1)),
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            aliases TEXT NOT NULL DEFAULT '',
            store_pos INTEGER NOT NULL DEFAULT 0,
            d_corrector INTEGER NOT NULL DEFAULT 0,
            comment TEXT NOT NULL DEFAULT '',
            flutes_num INTEGER NOT NULL DEFAULT 0,
            flutes_length REAL NOT NULL DEFAULT 0,
            flutes_coating TEXT NOT NULL DEFAULT '',
            flutes_type TEXT NOT NULL DEFAULT '',
            shank REAL NOT NULL DEFAULT 0,
            max_depth REAL NOT NULL DEFAULT 0,
            max_working_depth REAL NOT NULL DEFAULT 0,
            depth_per_pass REAL NOT NULL DEFAULT 0,
            extras TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );

        INSERT INTO tools_v2 (id, number, name, diameter, color, can_plunge, active,
            aliases, store_pos, d_corrector, comment, flutes_num, flutes_length,
            flutes_coating, flutes_type, shank, max_depth, max_working_depth, depth_per_pass, extras, updated_at)
        SELECT id, number, name, diameter, color, can_plunge, active,
            COALESCE(aliases, ''), COALESCE(store_pos, 0), COALESCE(d_corrector, 0),
            COALESCE(comment, ''), COALESCE(flutes_num, 0), COALESCE(flutes_length, 0),
            COALESCE(flutes_coating, ''), COALESCE(flutes_type, ''), COALESCE(shank, 0),
            COALESCE(max_depth, 0), COALESCE(max_working_depth, 0), COALESCE(depth_per_pass, 0),
            extras, updated_at
        FROM tools;

        DROP TABLE tools;
        ALTER TABLE tools_v2 RENAME TO tools;
    """)

    # Create partial unique index (only one active tool per number)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tools_active_number
            ON tools(number) WHERE active = 1
    """)

    conn.execute("INSERT OR REPLACE INTO schema_version(version) VALUES (2)")


def init_db() -> None:
    with db_connect() as conn:
        # Check if tools table exists
        has_tools = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='tools'"
        ).fetchone()[0]

        if not has_tools:
            # Fresh DB — use v2 schema directly
            conn.executescript(SCHEMA_SQL)
            conn.execute("INSERT OR REPLACE INTO schema_version(version) VALUES (2)")
        else:
            # Check schema version
            try:
                ver = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
            except sqlite3.OperationalError:
                conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
                conn.execute("INSERT OR IGNORE INTO schema_version(version) VALUES (1)")
                ver = 1

            if ver < 2:
                migrate_v1_to_v2(conn)

        # Seed job types
        seed_codes = {code for code, _ in SEED_JOB_TYPES}
        placeholders = ",".join("?" for _ in seed_codes)
        if seed_codes:
            conn.execute(
                f"UPDATE job_types SET active = 0 WHERE code NOT IN ({placeholders})",
                tuple(sorted(seed_codes)),
            )

        for code, name in SEED_JOB_TYPES:
            conn.execute(
                """
                INSERT INTO job_types(code, name, active) VALUES (?, ?, 1)
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name,
                    active = 1
                """,
                (code, name),
            )

        for node_name, job_code in SEED_NODE_MAP:
            conn.execute(
                """
                INSERT INTO node_job_map(node_name, job_code) VALUES (?, ?)
                ON CONFLICT(node_name) DO UPDATE SET
                    job_code = excluded.job_code
                """,
                (node_name, job_code),
            )


def parse_json(handler: BaseHTTPRequestHandler):
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON payload")


def parse_extras(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value) if value.strip() else {}
        if not isinstance(parsed, dict):
            raise ValueError("extras must be a JSON object")
        return parsed
    raise ValueError("extras must be a JSON object")


def validate_rate(value, field):
    if value is None or value == "":
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be numeric")
    if num < 0:
        raise ValueError(f"{field} must be >= 0")
    return num


def normalize_tool_payload(payload, partial=False):
    out = {}

    def need(field):
        if not partial and field not in payload:
            raise ValueError(f"Missing field: {field}")

    need("number")
    need("name")
    need("diameter")

    if "number" in payload:
        try:
            number = int(payload["number"])
        except (TypeError, ValueError):
            raise ValueError("number must be integer")
        if number < 100 or number > 999:
            raise ValueError("number must be 3-digit (100-999)")
        out["number"] = number

    if "name" in payload:
        name = str(payload["name"]).strip()
        if not name:
            raise ValueError("name is required")
        out["name"] = name

    if "diameter" in payload:
        try:
            diameter = float(payload["diameter"])
        except (TypeError, ValueError):
            raise ValueError("diameter must be numeric")
        if diameter <= 0:
            raise ValueError("diameter must be > 0")
        out["diameter"] = diameter

    if "color" in payload:
        color = str(payload["color"]).strip()
        out["color"] = color or "#6BA4FF"

    if "canPlunge" in payload:
        out["can_plunge"] = 1 if bool(payload["canPlunge"]) else 0

    if "active" in payload:
        out["active"] = 1 if bool(payload["active"]) else 0

    # New v2 fields
    if "aliases" in payload:
        out["aliases"] = str(payload.get("aliases", "")).strip()

    if "storePos" in payload:
        try:
            out["store_pos"] = int(payload["storePos"])
        except (TypeError, ValueError):
            out["store_pos"] = 0

    if "dCorrector" in payload:
        try:
            out["d_corrector"] = int(payload["dCorrector"])
        except (TypeError, ValueError):
            out["d_corrector"] = 0

    if "comment" in payload:
        out["comment"] = str(payload.get("comment", "")).strip()

    if "flutesNum" in payload:
        try:
            out["flutes_num"] = int(payload["flutesNum"])
        except (TypeError, ValueError):
            out["flutes_num"] = 0

    if "flutesLength" in payload:
        try:
            out["flutes_length"] = float(payload["flutesLength"])
        except (TypeError, ValueError):
            out["flutes_length"] = 0.0

    if "flutesCoating" in payload:
        out["flutes_coating"] = str(payload.get("flutesCoating", "")).strip()

    if "flutesType" in payload:
        ft = str(payload.get("flutesType", "")).strip().lower()
        if ft and ft not in ("upcut", "downcut", "straight", "compression"):
            raise ValueError("flutesType must be one of: upcut, downcut, straight, compression")
        out["flutes_type"] = ft

    if "shank" in payload:
        try:
            out["shank"] = float(payload["shank"])
        except (TypeError, ValueError):
            out["shank"] = 0.0

    if "maxDepth" in payload:
        try:
            out["max_depth"] = float(payload["maxDepth"])
        except (TypeError, ValueError):
            out["max_depth"] = 0.0

    if "maxWorkingDepth" in payload:
        try:
            out["max_working_depth"] = float(payload["maxWorkingDepth"])
        except (TypeError, ValueError):
            out["max_working_depth"] = 0.0

    if "depthPerPass" in payload:
        try:
            out["depth_per_pass"] = float(payload["depthPerPass"])
        except (TypeError, ValueError):
            out["depth_per_pass"] = 0.0

    if "extras" in payload:
        extras = parse_extras(payload["extras"])
        out["extras"] = json.dumps(extras, ensure_ascii=True, separators=(",", ":"))

    return out


def fetch_job_types(conn):
    rows = conn.execute(
        "SELECT id, code, name, active FROM job_types WHERE active = 1 ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_node_map(conn):
    rows = conn.execute(
        "SELECT node_name, job_code FROM node_job_map ORDER BY node_name"
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_tool_list(conn):
    rows = conn.execute(
        """
        SELECT t.id, t.number, t.name, t.diameter, t.color, t.active, t.updated_at
          FROM tools t
         ORDER BY t.number, t.name
        """
    ).fetchall()
    data = []
    for r in rows:
        data.append(
            {
                "id": r["id"],
                "number": r["number"],
                "name": r["name"],
                "diameter": r["diameter"],
                "color": r["color"],
                "active": bool(r["active"]),
                "updatedAt": r["updated_at"],
            }
        )
    return data


def fetch_tool_detail(conn, tool_id: int):
    tool = conn.execute(
        "SELECT * FROM tools WHERE id = ?",
        (tool_id,),
    ).fetchone()
    if not tool:
        return None

    caps = conn.execute(
        """
        SELECT jt.code
          FROM tool_capabilities tc
          JOIN job_types jt ON jt.id = tc.job_type_id
         WHERE tc.tool_id = ?
         ORDER BY jt.code
        """,
        (tool_id,),
    ).fetchall()

    g = conn.execute(
        "SELECT speed, feed, plunge, ramp FROM tool_defaults_global WHERE tool_id = ?",
        (tool_id,),
    ).fetchone()

    by_job_rows = conn.execute(
        """
        SELECT jt.code, d.speed, d.feed, d.plunge, d.ramp
          FROM tool_defaults_by_job d
          JOIN job_types jt ON jt.id = d.job_type_id
         WHERE d.tool_id = ?
         ORDER BY jt.code
        """,
        (tool_id,),
    ).fetchall()

    by_job = {}
    for row in by_job_rows:
        by_job[row["code"]] = {
            "speed": row["speed"],
            "feed": row["feed"],
            "plunge": row["plunge"],
            "ramp": row["ramp"],
        }

    return {
        "id": tool["id"],
        "number": tool["number"],
        "name": tool["name"],
        "diameter": tool["diameter"],
        "color": tool["color"],
        "canPlunge": bool(tool["can_plunge"]),
        "active": bool(tool["active"]),
        "aliases": tool["aliases"],
        "storePos": tool["store_pos"],
        "dCorrector": tool["d_corrector"],
        "comment": tool["comment"],
        "flutesNum": tool["flutes_num"],
        "flutesLength": tool["flutes_length"],
        "flutesCoating": tool["flutes_coating"],
        "flutesType": tool["flutes_type"],
        "shank": tool["shank"],
        "maxDepth": tool["max_depth"],
        "maxWorkingDepth": tool["max_working_depth"],
        "depthPerPass": tool["depth_per_pass"],
        "updatedAt": tool["updated_at"],
        "extras": json.loads(tool["extras"] or "{}"),
        "capabilities": [c["code"] for c in caps],
        "defaultsGlobal": {
            "speed": g["speed"] if g else None,
            "feed": g["feed"] if g else None,
            "plunge": g["plunge"] if g else None,
            "ramp": g["ramp"] if g else None,
        },
        "defaultsByJob": by_job,
    }


def save_defaults_global(conn, tool_id, payload):
    values = {
        "speed": validate_rate(payload.get("speed"), "global.speed"),
        "feed": validate_rate(payload.get("feed"), "global.feed"),
        "plunge": validate_rate(payload.get("plunge"), "global.plunge"),
        "ramp": validate_rate(payload.get("ramp"), "global.ramp"),
    }
    conn.execute(
        """
        INSERT INTO tool_defaults_global(tool_id, speed, feed, plunge, ramp, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(tool_id) DO UPDATE SET
            speed = excluded.speed,
            feed = excluded.feed,
            plunge = excluded.plunge,
            ramp = excluded.ramp,
            updated_at = excluded.updated_at
        """,
        (tool_id, values["speed"], values["feed"], values["plunge"], values["ramp"], utc_now()),
    )


def save_capabilities(conn, tool_id, capability_codes):
    codes = set(capability_codes or [])
    rows = conn.execute("SELECT id, code FROM job_types WHERE active = 1").fetchall()
    code_to_id = {r["code"]: r["id"] for r in rows}

    for code in codes:
        if code not in code_to_id:
            raise ValueError(f"Unknown job code: {code}")

    conn.execute("DELETE FROM tool_capabilities WHERE tool_id = ?", (tool_id,))
    for code in sorted(codes):
        conn.execute(
            "INSERT INTO tool_capabilities(tool_id, job_type_id) VALUES (?, ?)",
            (tool_id, code_to_id[code]),
        )


def save_defaults_by_job(conn, tool_id, defaults_by_job):
    defaults_by_job = defaults_by_job or {}
    rows = conn.execute("SELECT id, code FROM job_types WHERE active = 1").fetchall()
    code_to_id = {r["code"]: r["id"] for r in rows}

    conn.execute("DELETE FROM tool_defaults_by_job WHERE tool_id = ?", (tool_id,))

    for code, values in defaults_by_job.items():
        if code not in code_to_id:
            raise ValueError(f"Unknown job code in defaultsByJob: {code}")
        speed = validate_rate(values.get("speed"), f"{code}.speed")
        feed = validate_rate(values.get("feed"), f"{code}.feed")
        plunge = validate_rate(values.get("plunge"), f"{code}.plunge")
        ramp = validate_rate(values.get("ramp"), f"{code}.ramp")
        conn.execute(
            """
            INSERT INTO tool_defaults_by_job(tool_id, job_type_id, speed, feed, plunge, ramp, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (tool_id, code_to_id[code], speed, feed, plunge, ramp, utc_now()),
        )


def deactivate_others(conn, tool_id: int, number: int) -> None:
    """When activating a tool, deactivate all other tools with the same number."""
    conn.execute(
        "UPDATE tools SET active = 0, updated_at = ? WHERE number = ? AND id != ? AND active = 1",
        (utc_now(), number, tool_id),
    )


class AppHandler(BaseHTTPRequestHandler):
    server_version = "GTooling/0.2"

    def log_message(self, fmt, *args):
        print("[http]", fmt % args)

    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_text(self, status, text, content_type="text/plain; charset=utf-8"):
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_static(self, rel_path):
        if rel_path == "/" or rel_path == "":
            rel_path = "/index.html"
        file_path = (STATIC_DIR / rel_path.lstrip("/")).resolve()
        if STATIC_DIR not in file_path.parents and file_path != STATIC_DIR:
            self.send_text(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not file_path.exists() or not file_path.is_file():
            self.send_text(HTTPStatus.NOT_FOUND, "Not found")
            return

        ext = file_path.suffix.lower()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
        }.get(ext, "application/octet-stream")

        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/meta":
            db = get_db_path()
            if not db:
                return self.send_json(HTTPStatus.OK, {
                    "dbPath": "",
                    "jobTypes": [],
                    "nodeJobMap": [],
                    "noDatabase": True,
                })
            with db_connect() as conn:
                return self.send_json(
                    HTTPStatus.OK,
                    {
                        "dbPath": db,
                        "jobTypes": fetch_job_types(conn),
                        "nodeJobMap": fetch_node_map(conn),
                    },
                )

        if path == "/api/tools":
            with db_connect() as conn:
                return self.send_json(HTTPStatus.OK, {"tools": fetch_tool_list(conn)})

        if path.startswith("/api/tools/") and path.endswith("/image"):
            try:
                tool_id = int(path.split("/")[-2])
            except ValueError:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid tool id"})
            return self.serve_tool_image(tool_id)

        if path.startswith("/api/tools/"):
            try:
                tool_id = int(path.split("/")[-1])
            except ValueError:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid tool id"})
            with db_connect() as conn:
                tool = fetch_tool_detail(conn, tool_id)
            if not tool:
                return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Tool not found"})
            return self.send_json(HTTPStatus.OK, tool)

        return self.serve_static(path)

    def serve_tool_image(self, tool_id):
        img_dir = Path(get_db_path()).parent / "images"
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            img_path = img_dir / f"{tool_id}{ext}"
            if img_path.exists():
                ctype = {".png": "image/png", ".jpg": "image/jpeg",
                         ".jpeg": "image/jpeg", ".webp": "image/webp"}[ext]
                data = img_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(data)
                return
        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()

    def handle_image_upload(self, tool_id):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Expected multipart/form-data"})

        # Parse boundary
        boundary = None
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[len("boundary="):]
                break
        if not boundary:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "No boundary found"})

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)

        # Simple multipart parsing — find the file data
        boundary_bytes = boundary.encode()
        parts = body.split(b"--" + boundary_bytes)

        file_data = None
        file_ext = ".png"
        for part in parts:
            if b"filename=" not in part:
                continue
            # Find content type
            header_end = part.find(b"\r\n\r\n")
            if header_end < 0:
                continue
            headers_raw = part[:header_end].decode("utf-8", errors="replace").lower()
            file_data = part[header_end + 4:]
            # Strip trailing \r\n
            if file_data.endswith(b"\r\n"):
                file_data = file_data[:-2]

            if "image/jpeg" in headers_raw or "image/jpg" in headers_raw:
                file_ext = ".jpg"
            elif "image/webp" in headers_raw:
                file_ext = ".webp"
            else:
                file_ext = ".png"
            break

        if not file_data:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "No image file found"})

        img_dir = Path(get_db_path()).parent / "images"
        img_dir.mkdir(parents=True, exist_ok=True)

        # Remove old images for this tool
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            old = img_dir / f"{tool_id}{ext}"
            if old.exists():
                old.unlink()

        img_path = img_dir / f"{tool_id}{file_ext}"
        img_path.write_bytes(file_data)
        return self.send_json(HTTPStatus.OK, {"ok": True, "path": str(img_path)})

    def check_admin(self):
        """Check X-Admin-Password header against stored password."""
        pw = self.headers.get("X-Admin-Password", "")
        return pw == get_admin_password()

    def require_admin(self):
        """Return True if authorized, otherwise send 403 and return False."""
        if self.check_admin():
            return True
        self.send_json(HTTPStatus.FORBIDDEN, {"error": "Admin password required"})
        return False

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/auth":
            try:
                payload = parse_json(self)
                password = payload.get("password", "")
                if password == get_admin_password():
                    return self.send_json(HTTPStatus.OK, {"admin": True})
                else:
                    return self.send_json(HTTPStatus.FORBIDDEN, {"admin": False, "error": "Wrong password"})
            except ValueError as e:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})

        if parsed.path == "/api/auth/change-password":
            if not self.require_admin():
                return
            try:
                payload = parse_json(self)
                new_pw = payload.get("newPassword", "").strip()
                if not new_pw:
                    return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "New password is required"})
                if len(new_pw) < 4:
                    return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Password must be at least 4 characters"})
                set_admin_password(new_pw)
                return self.send_json(HTTPStatus.OK, {"ok": True})
            except ValueError as e:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})

        if parsed.path.startswith("/api/tools/") and parsed.path.endswith("/image"):
            if not self.require_admin():
                return
            try:
                tool_id = int(parsed.path.split("/")[-2])
            except ValueError:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid tool id"})
            return self.handle_image_upload(tool_id)

        if parsed.path == "/api/settings/create-db":
            try:
                payload = parse_json(self)
                path = normalize_db_path(payload.get("dbPath", ""))
                if Path(path).exists():
                    return self.send_json(
                        HTTPStatus.CONFLICT,
                        {"error": "Database already exists at this path. Use Open DB instead."},
                    )
                parent = Path(path).parent
                if not parent.exists():
                    return self.send_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": f"Directory does not exist: {parent}"},
                    )
                set_db_path(path, remember=True)
                init_db()
                return self.send_json(HTTPStatus.CREATED, {"dbPath": get_db_path()})
            except (ValueError, sqlite3.Error) as e:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})

        if parsed.path == "/api/settings/db-path":
            try:
                payload = parse_json(self)
                path = normalize_db_path(payload.get("dbPath", ""))
                previous = get_db_path()
                set_db_path(path, remember=True)
                try:
                    init_db()
                except sqlite3.Error as e:
                    set_db_path(previous, remember=True)
                    return self.send_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": f"Cannot open DB: {e}"},
                    )
                return self.send_json(
                    HTTPStatus.OK,
                    {"dbPath": get_db_path()},
                )
            except ValueError as e:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})

        if parsed.path != "/api/tools":
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

        if not self.require_admin():
            return

        try:
            payload = parse_json(self)
            tool_fields = normalize_tool_payload(payload, partial=False)
        except ValueError as e:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})

        with db_connect() as conn:
            try:
                now = utc_now()

                # If creating an active tool, deactivate others with same number
                is_active = tool_fields.get("active", 1)
                if is_active:
                    conn.execute(
                        "UPDATE tools SET active = 0, updated_at = ? WHERE number = ? AND active = 1",
                        (now, tool_fields["number"]),
                    )

                conn.execute(
                    """
                    INSERT INTO tools(number, name, diameter, color, can_plunge, active,
                        aliases, store_pos, d_corrector, comment,
                        flutes_num, flutes_length, flutes_coating, flutes_type, shank,
                        max_depth, max_working_depth, depth_per_pass,
                        extras, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tool_fields["number"],
                        tool_fields["name"],
                        tool_fields["diameter"],
                        tool_fields.get("color", "#6BA4FF"),
                        tool_fields.get("can_plunge", 1),
                        tool_fields.get("active", 1),
                        tool_fields.get("aliases", ""),
                        tool_fields.get("store_pos", 0),
                        tool_fields.get("d_corrector", 0),
                        tool_fields.get("comment", ""),
                        tool_fields.get("flutes_num", 0),
                        tool_fields.get("flutes_length", 0.0),
                        tool_fields.get("flutes_coating", ""),
                        tool_fields.get("flutes_type", ""),
                        tool_fields.get("shank", 0.0),
                        tool_fields.get("max_depth", 0.0),
                        tool_fields.get("max_working_depth", 0.0),
                        tool_fields.get("depth_per_pass", 0.0),
                        tool_fields.get("extras", "{}"),
                        now,
                    ),
                )
                tool_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

                save_capabilities(conn, tool_id, payload.get("capabilities", []))
                save_defaults_global(conn, tool_id, payload.get("defaultsGlobal", {}))
                save_defaults_by_job(conn, tool_id, payload.get("defaultsByJob", {}))
            except sqlite3.IntegrityError as e:
                return self.send_json(HTTPStatus.CONFLICT, {"error": str(e)})
            except ValueError as e:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})

            tool = fetch_tool_detail(conn, tool_id)
            return self.send_json(HTTPStatus.CREATED, tool)

    def do_PUT(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/tools/"):
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

        if not self.require_admin():
            return

        try:
            tool_id = int(parsed.path.split("/")[-1])
            payload = parse_json(self)
            tool_fields = normalize_tool_payload(payload, partial=True)
        except ValueError as e:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})

        with db_connect() as conn:
            existing = conn.execute("SELECT id, number FROM tools WHERE id = ?", (tool_id,)).fetchone()
            if not existing:
                return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Tool not found"})

            try:
                # If activating, deactivate others with same number
                if tool_fields.get("active") == 1:
                    number = tool_fields.get("number", existing["number"])
                    deactivate_others(conn, tool_id, number)

                set_parts = []
                vals = []
                for key in ["number", "name", "diameter", "color", "can_plunge", "active",
                            "aliases", "store_pos", "d_corrector", "comment",
                            "flutes_num", "flutes_length", "flutes_coating", "flutes_type",
                            "shank", "max_depth", "max_working_depth", "depth_per_pass", "extras"]:
                    if key in tool_fields:
                        set_parts.append(f"{key} = ?")
                        vals.append(tool_fields[key])
                set_parts.append("updated_at = ?")
                vals.append(utc_now())
                vals.append(tool_id)

                conn.execute(
                    f"UPDATE tools SET {', '.join(set_parts)} WHERE id = ?",
                    vals,
                )

                if "capabilities" in payload:
                    save_capabilities(conn, tool_id, payload.get("capabilities", []))
                if "defaultsGlobal" in payload:
                    save_defaults_global(conn, tool_id, payload.get("defaultsGlobal", {}))
                if "defaultsByJob" in payload:
                    save_defaults_by_job(conn, tool_id, payload.get("defaultsByJob", {}))

            except sqlite3.IntegrityError as e:
                return self.send_json(HTTPStatus.CONFLICT, {"error": str(e)})
            except ValueError as e:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})

            tool = fetch_tool_detail(conn, tool_id)
            return self.send_json(HTTPStatus.OK, tool)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/tools/"):
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

        if not self.require_admin():
            return

        try:
            tool_id = int(parsed.path.split("/")[-1])
        except ValueError:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid tool id"})

        with db_connect() as conn:
            existing = conn.execute("SELECT id FROM tools WHERE id = ?", (tool_id,)).fetchone()
            if not existing:
                return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Tool not found"})
            conn.execute("DELETE FROM tools WHERE id = ?", (tool_id,))
            return self.send_json(HTTPStatus.OK, {"deleted": tool_id})


def main():
    try:
        initial = resolve_initial_db_path()
        if Path(initial).exists():
            set_db_path(initial, remember=not bool(ENV_DB_PATH))
            init_db()
            print(f"DB: {get_db_path()}")
        else:
            print(f"DB not found: {initial}")
            print("Waiting for user to open or create a database...")
            # Clear the path so /api/meta returns empty
            with _db_path_lock:
                global _db_path_value
                _db_path_value = ""
    except Exception as e:
        print(f"No DB configured: {e}")
        with _db_path_lock:
            _db_path_value = ""

    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"G-Tooling running on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")


if __name__ == "__main__":
    main()
