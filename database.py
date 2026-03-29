import sqlite3
from datetime import datetime

DB_PATH = "secretary.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            notify_enabled INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    conn.close()


def set_notify_enabled(user_id: int, enabled: bool):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO user_settings (user_id, notify_enabled) VALUES (?, ?)",
        (user_id, 1 if enabled else 0)
    )
    conn.commit()
    conn.close()


def is_notify_enabled(user_id: int) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT notify_enabled FROM user_settings WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return bool(row["notify_enabled"]) if row else False


def get_notify_enabled_users() -> list[int]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT user_id FROM user_settings WHERE notify_enabled = 1"
    ).fetchall()
    conn.close()
    return [row["user_id"] for row in rows]


def add_schedule(user_id: int, title: str, date: str, start_time: str, end_time: str, notes: str = None) -> int:
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO schedules (user_id, title, date, start_time, end_time, notes) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, title, date, start_time, end_time, notes)
    )
    conn.commit()
    schedule_id = cursor.lastrowid
    conn.close()
    return schedule_id


def add_schedules_bulk(user_id: int, schedules: list[dict]) -> int:
    conn = get_connection()
    count = 0
    for s in schedules:
        conn.execute(
            "INSERT INTO schedules (user_id, title, date, start_time, end_time, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, s["title"], s["date"], s["start_time"], s["end_time"], s.get("notes"))
        )
        count += 1
    conn.commit()
    conn.close()
    return count


def get_schedules(user_id: int, date: str = None) -> list[dict]:
    conn = get_connection()
    if date:
        rows = conn.execute(
            "SELECT * FROM schedules WHERE user_id = ? AND date = ? ORDER BY start_time",
            (user_id, date)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM schedules WHERE user_id = ? ORDER BY date, start_time",
            (user_id,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_schedules_range(user_id: int, start_date: str, end_date: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM schedules WHERE user_id = ? AND date >= ? AND date <= ? ORDER BY date, start_time",
        (user_id, start_date, end_date)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_schedule(user_id: int, schedule_id: int) -> bool:
    conn = get_connection()
    cursor = conn.execute(
        "DELETE FROM schedules WHERE id = ? AND user_id = ?",
        (schedule_id, user_id)
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def delete_schedules_by_date(user_id: int, date: str) -> int:
    conn = get_connection()
    cursor = conn.execute(
        "DELETE FROM schedules WHERE user_id = ? AND date = ?",
        (user_id, date)
    )
    conn.commit()
    count = cursor.rowcount
    conn.close()
    return count
