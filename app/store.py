"""SQLite storage of scored seeds. Seeds are stored as text so they stay exact."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from app.scoring import Result

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seeds (
    seed TEXT PRIMARY KEY,
    input_text TEXT,
    score REAL NOT NULL,
    breakdown TEXT NOT NULL,
    spawn_x INTEGER NOT NULL,
    spawn_z INTEGER NOT NULL,
    spawn_biome TEXT NOT NULL,
    mean_weirdness REAL NOT NULL,
    rejected_reason TEXT,
    structures TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""
_ORDER = {
    "score": "rejected_reason IS NOT NULL, score DESC, created_at DESC",
    "weirdness": "mean_weirdness DESC, created_at DESC",
}


class Store:
    def __init__(self, path: str):
        self._path = path
        with closing(self._connect()) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def save(self, seed: int, input_text: str | None, result: Result, spawn: tuple[int, int],
             spawn_biome: str, structures: list[tuple[str, int, int]], source: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                """
                INSERT INTO seeds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(seed) DO UPDATE SET
                    input_text = COALESCE(excluded.input_text, input_text),
                    score = excluded.score,
                    breakdown = excluded.breakdown,
                    spawn_x = excluded.spawn_x,
                    spawn_z = excluded.spawn_z,
                    spawn_biome = excluded.spawn_biome,
                    mean_weirdness = excluded.mean_weirdness,
                    rejected_reason = excluded.rejected_reason,
                    structures = excluded.structures,
                    source = CASE WHEN source = 'manual' THEN 'manual' ELSE excluded.source END
                """,
                (str(seed), input_text, result.score, json.dumps(result.breakdown), spawn[0], spawn[1],
                 spawn_biome, result.mean_weirdness, result.rejected_reason, json.dumps(structures),
                 source, datetime.now(timezone.utc).isoformat()),
            )

    def get(self, seed: int) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM seeds WHERE seed = ?", (str(seed),)).fetchone()
        return _row(row) if row else None

    def list(self, sort: str, limit: int = 500) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute(
                f"""
                SELECT * FROM seeds
                WHERE source = 'manual' OR seed IN (
                    SELECT seed FROM seeds WHERE source != 'manual' ORDER BY {_ORDER[sort]} LIMIT ?
                )
                ORDER BY {_ORDER[sort]}
                """,
                (limit,),
            ).fetchall()
        return [_row(r) for r in rows]

    def delete_search_seed(self, seed: int) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM seeds WHERE seed = ? AND source = 'search'", (str(seed),))


def _row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["breakdown"] = json.loads(out["breakdown"])
    out["structures"] = json.loads(out["structures"])
    return out
