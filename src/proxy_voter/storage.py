import json
import logging
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from proxy_voter.config import get_settings
from proxy_voter.models import BallotData, SessionStatus, VotingDecision

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    sender_email TEXT NOT NULL,
    company_name TEXT NOT NULL,
    voting_url TEXT NOT NULL,
    ballot_data TEXT NOT NULL,
    voting_decisions TEXT NOT NULL,
    metadata TEXT NOT NULL,
    status TEXT NOT NULL
)
"""


def _generate_session_id() -> str:
    chars = string.ascii_lowercase + string.digits
    suffix = "".join(secrets.choice(chars) for _ in range(6))
    return f"PV-{suffix}"


def _db_path() -> str:
    db_path = Path(get_settings().database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return str(db_path)


async def init_db() -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(_CREATE_TABLE)
        # Migration: rename voting_url -> voting_url if old schema exists
        cursor = await db.execute("PRAGMA table_info(sessions)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "proxyvote_url" in columns and "voting_url" not in columns:
            await db.execute("ALTER TABLE sessions RENAME COLUMN proxyvote_url TO voting_url")
            logger.info("Migrated column proxyvote_url -> voting_url")
        await db.commit()


async def create_session(
    sender_email: str,
    company_name: str,
    voting_url: str,
    ballot_data: BallotData,
    voting_decisions: list[VotingDecision],
    metadata: dict,
) -> str:
    session_id = _generate_session_id()
    now = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """INSERT INTO sessions
               (id, created_at, sender_email, company_name, voting_url,
                ballot_data, voting_decisions, metadata, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                now,
                sender_email,
                company_name,
                voting_url,
                ballot_data.model_dump_json(),
                json.dumps([d.model_dump() for d in voting_decisions]),
                json.dumps(metadata),
                SessionStatus.PENDING_APPROVAL.value,
            ),
        )
        await db.commit()

    logger.info("Created session %s for %s", session_id, company_name)
    return session_id


async def get_session(
    session_id: str,
) -> dict | None:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)


async def update_session_status(session_id: str, status: SessionStatus) -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            "UPDATE sessions SET status = ? WHERE id = ?",
            (status.value, session_id),
        )
        await db.commit()
    logger.info("Updated session %s status to %s", session_id, status.value)
