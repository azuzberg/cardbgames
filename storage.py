"""SQLite persistence with one atomic transaction for each move and revision check."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from game import GameError, new_game, public_state


class Storage:
    def __init__(self, path: str):
        self.path = str(Path(path).expanduser().resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    game_json TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS match_history (
                    game_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    finished_at TEXT NOT NULL,
                    player_score INTEGER NOT NULL,
                    bot_score INTEGER NOT NULL,
                    winner TEXT NOT NULL CHECK(winner IN ('player', 'bot')),
                    rounds INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS history_by_session
                ON match_history(session_id, finished_at DESC);
            """)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _game(conn, session_id: str) -> dict | None:
        row = conn.execute("SELECT game_json FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return json.loads(row["game_json"]) if row and row["game_json"] else None

    @staticmethod
    def _envelope(conn, session_id: str, game: dict | None) -> dict:
        stats = conn.execute("""
            SELECT COUNT(*) AS played,
                   COALESCE(SUM(winner='player'), 0) AS wins,
                   COALESCE(SUM(winner='bot'), 0) AS losses
            FROM match_history WHERE session_id=?
        """, (session_id,)).fetchone()
        history = conn.execute("""
            SELECT finished_at, player_score, bot_score, winner, rounds
            FROM match_history WHERE session_id=? ORDER BY finished_at DESC, game_id DESC LIMIT 10
        """, (session_id,)).fetchall()
        return {"game": public_state(game), "stats": dict(stats), "history": [dict(row) for row in history]}

    def state(self, session_id: str) -> dict:
        with self.connection() as conn:
            conn.execute("BEGIN")
            try:
                result = self._envelope(conn, session_id, self._game(conn, session_id))
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def start(self, session_id: str) -> dict:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                previous = self._game(conn, session_id)
                game = new_game()
                # Resetting a match also advances the session's revision, so old requests fail.
                if previous:
                    game["revision"] = previous["revision"] + 1
                conn.execute("""
                    INSERT INTO sessions(session_id, game_json, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET game_json=excluded.game_json,
                                                        updated_at=excluded.updated_at
                """, (session_id, json.dumps(game, ensure_ascii=False), self._now()))
                result = self._envelope(conn, session_id, game)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def mutate(self, session_id: str, revision: int, operation: Callable[[dict], None]) -> dict:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                game = self._game(conn, session_id)
                if game is None:
                    raise GameError("Сначала начните новую игру.", "no_game", 409)
                if game["revision"] != revision:
                    raise GameError("Состояние игры изменилось. Обновите стол и повторите ход.", "stale_revision", 409)
                previous_status = game["status"]
                operation(game)
                now = self._now()
                conn.execute("UPDATE sessions SET game_json=?, updated_at=? WHERE session_id=?",
                             (json.dumps(game, ensure_ascii=False), now, session_id))
                if game["status"] == "match_over" and previous_status != "match_over":
                    conn.execute("""
                        INSERT INTO match_history(game_id, session_id, finished_at, player_score,
                                                  bot_score, winner, rounds)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (game["id"], session_id, now, game["scores"]["player"],
                          game["scores"]["bot"], game["winner"], game["round"]))
                result = self._envelope(conn, session_id, game)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise
