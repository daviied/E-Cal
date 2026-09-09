import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.environ.get("DB_PATH", "./data/calcvault.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calculators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('calculator','function')),
                data TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def default_data(kind: str) -> dict:
    # Every calculator has one unified shape: an ordered list of lines, each
    # either a plain equation, a labeled input, or a labeled output, plus a
    # lock flag that governs whether lines marked "hidden" are collapsed.
    return {"locked": False, "lines": []}


def get_tree() -> dict:
    with get_conn() as conn:
        folders = [dict(r) for r in conn.execute("SELECT * FROM folders ORDER BY name COLLATE NOCASE")]
        calcs = [
            dict(r)
            for r in conn.execute(
                "SELECT id, folder_id, name, kind, created_at, updated_at FROM calculators ORDER BY name COLLATE NOCASE"
            )
        ]
    return {"folders": folders, "calculators": calcs}


def create_folder(name: str, parent_id: int | None) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO folders (parent_id, name, created_at) VALUES (?, ?, ?)",
            (parent_id, name, _now()),
        )
        row = conn.execute("SELECT * FROM folders WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def update_folder(folder_id: int, name: str | None, parent_id: int | None, has_parent: bool) -> dict | None:
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)).fetchone()
        if not existing:
            return None
        new_name = name if name is not None else existing["name"]
        new_parent = parent_id if has_parent else existing["parent_id"]
        conn.execute(
            "UPDATE folders SET name = ?, parent_id = ? WHERE id = ?",
            (new_name, new_parent, folder_id),
        )
        row = conn.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)).fetchone()
        return dict(row)


def delete_folder(folder_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        return cur.rowcount > 0


def create_calculator(name: str, folder_id: int | None, kind: str) -> dict:
    now = _now()
    data = json.dumps(default_data(kind))
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO calculators (folder_id, name, kind, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (folder_id, name, kind, data, now, now),
        )
        row = conn.execute("SELECT * FROM calculators WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _calc_out(row)


def get_calculator(calc_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM calculators WHERE id = ?", (calc_id,)).fetchone()
        return _calc_out(row) if row else None


def update_calculator(
    calc_id: int, name: str | None, folder_id: int | None, has_folder: bool, data: dict | None
) -> dict | None:
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM calculators WHERE id = ?", (calc_id,)).fetchone()
        if not existing:
            return None
        new_name = name if name is not None else existing["name"]
        new_folder = folder_id if has_folder else existing["folder_id"]
        new_data = json.dumps(data) if data is not None else existing["data"]
        conn.execute(
            "UPDATE calculators SET name = ?, folder_id = ?, data = ?, updated_at = ? WHERE id = ?",
            (new_name, new_folder, new_data, _now(), calc_id),
        )
        row = conn.execute("SELECT * FROM calculators WHERE id = ?", (calc_id,)).fetchone()
        return _calc_out(row)


def delete_calculator(calc_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM calculators WHERE id = ?", (calc_id,))
        return cur.rowcount > 0


def _calc_out(row) -> dict:
    out = dict(row)
    out["data"] = json.loads(out["data"])
    return out
