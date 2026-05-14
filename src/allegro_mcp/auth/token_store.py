"""Single-row SQLite token store with strict file permissions."""

from __future__ import annotations

import contextlib
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    access_expires_at TIMESTAMP NOT NULL,
    scope TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass(frozen=True, slots=True)
class StoredTokens:
    """Tokens read from the store. `access_expires_at` is timezone-aware UTC."""

    access_token: str
    refresh_token: str
    access_expires_at: datetime
    scope: str


class TokenStore:
    """Persistent SQLite-backed token store.

    Enforces 0600 on the database file and 0700 on the parent directory so that
    refresh tokens are not readable by other users on shared hosts.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    @property
    def db_path(self) -> Path:
        return self._db_path

    async def initialise(self) -> None:
        """Create the database and apply schema with secure permissions."""
        self._ensure_secure_parent()
        existed = self._db_path.exists()
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()
        if not existed:
            self._restrict_file_mode()
        else:
            # Make sure existing files have correct permissions too.
            self._restrict_file_mode()

    def _ensure_secure_parent(self) -> None:
        parent = self._db_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        # On platforms without POSIX chmod semantics this is best-effort.
        with contextlib.suppress(OSError):
            parent.chmod(stat.S_IRWXU)  # 0700

    def _restrict_file_mode(self) -> None:
        with contextlib.suppress(OSError):
            self._db_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600

    async def load(self) -> StoredTokens | None:
        """Return stored tokens or `None` if none have been persisted."""
        if not self._db_path.exists():
            return None
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT access_token, refresh_token, access_expires_at, scope "
                "FROM tokens WHERE id = 1"
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return StoredTokens(
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            access_expires_at=_parse_timestamp(row["access_expires_at"]),
            scope=row["scope"],
        )

    async def save(self, tokens: StoredTokens) -> None:
        """Persist tokens, replacing any existing row."""
        await self.initialise()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO tokens (id, access_token, refresh_token, access_expires_at, scope)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    access_expires_at = excluded.access_expires_at,
                    scope = excluded.scope,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    tokens.access_token,
                    tokens.refresh_token,
                    tokens.access_expires_at.astimezone(UTC).isoformat(),
                    tokens.scope,
                ),
            )
            await db.commit()
        self._restrict_file_mode()

    async def clear(self) -> None:
        """Delete the stored token row."""
        if not self._db_path.exists():
            return
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM tokens WHERE id = 1")
            await db.commit()


def _parse_timestamp(raw: str | datetime) -> datetime:
    value = raw if isinstance(raw, datetime) else datetime.fromisoformat(raw)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


def file_mode(path: Path) -> int:
    """Helper for tests: return the file mode bits of `path`."""
    return stat.S_IMODE(os.stat(path).st_mode)
