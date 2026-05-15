import sqlite3
import aiosqlite
from config import DB_PATH

DB = DB_PATH

def init_db():
    """Synchronous init — safe to call before event loop starts."""
    with sqlite3.connect(DB) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                client_id TEXT NOT NULL UNIQUE,
                key_hex TEXT NOT NULL,
                room_id TEXT,
                carrier TEXT DEFAULT 'jazz',
                transport TEXT DEFAULT 'datachannel',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER REFERENCES profiles(id),
                service_name TEXT NOT NULL,
                status TEXT,
                last_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

async def create_profile(name: str, client_id: str, key_hex: str, room_id: str, carrier: str = "jazz", transport: str = "datachannel") -> int | None:
    async with aiosqlite.connect(DB) as db:
        try:
            cur = await db.execute(
                "INSERT INTO profiles (name, client_id, key_hex, room_id, carrier, transport) VALUES (?, ?, ?, ?, ?, ?)",
                (name, client_id, key_hex, room_id, carrier, transport)
            )
            await db.commit()
            return cur.lastrowid
        except aiosqlite.IntegrityError:
            return None

async def list_profiles() -> list[dict]:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM profiles ORDER BY created_at DESC")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

async def get_profile(profile_id: int) -> dict | None:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

async def delete_profile(profile_id: int) -> bool:
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        await db.commit()
        return cur.rowcount > 0

async def set_profile_active(profile_id: int, active: bool):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE profiles SET active = ? WHERE id = ?",
            (1 if active else 0, profile_id)
        )
        await db.commit()

async def update_profile_room(profile_id: int, room_id: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE profiles SET room_id = ? WHERE id = ?",
            (room_id, profile_id)
        )
        await db.commit()
