"""SQLite database operations for Fund Job Radar."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional

from .config import get_config
from .models import FundingEvent, JobPosting, Opportunity


def _resolve_db_path(path: str) -> Path:
    """Resolve database path relative to project root."""
    p = Path(path)
    if p.is_absolute():
        return p
    # Resolve relative to project root (parent of app/)
    return (Path(__file__).parent.parent / p).resolve()


@contextmanager
def get_db_connection():
    """Context manager for database connections."""
    config = get_config()
    db_path = _resolve_db_path(config.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Initialize database tables."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # funding_events table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS funding_events (
                id TEXT PRIMARY KEY,
                company_name TEXT NOT NULL,
                company_domain TEXT DEFAULT '',
                round_type TEXT NOT NULL,
                amount_cny REAL NOT NULL,
                announcement_date DATETIME NOT NULL,
                investors TEXT DEFAULT '',
                source_url TEXT DEFAULT '',
                source TEXT NOT NULL,
                industry_group TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # job_postings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS job_postings (
                id TEXT PRIMARY KEY,
                company_name TEXT NOT NULL,
                job_title TEXT NOT NULL,
                job_count INTEGER DEFAULT 1,
                posting_date DATETIME NOT NULL,
                source TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # opportunities table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS opportunities (
                id TEXT PRIMARY KEY,
                company_name TEXT NOT NULL,
                funding_event_id TEXT NOT NULL,
                signal_strength TEXT NOT NULL,
                window_days_remaining INTEGER NOT NULL,
                recommended_action TEXT NOT NULL,
                status TEXT DEFAULT 'new',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (funding_event_id) REFERENCES funding_events(id)
            )
        """)

        # company_aliases table for fuzzy matching
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS company_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_name TEXT NOT NULL,
                alias TEXT NOT NULL,
                UNIQUE(alias)
            )
        """)

        # Indexes for performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_funding_announcement
            ON funding_events(announcement_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_opportunities_status
            ON opportunities(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_funding_company
            ON funding_events(company_name)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_funding_source
            ON funding_events(source)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_postings_company
            ON job_postings(company_name)
        """)

        # Migrate: add industry_group column if missing (for existing tables)
        try:
            cursor.execute("ALTER TABLE funding_events ADD COLUMN industry_group TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # Column already exists


def insert_funding_event(event: FundingEvent) -> bool:
    """
    Insert a funding event. Returns True if inserted, False if already exists.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Check for duplicate based on company + round_type + source
        # (announcement_date is excluded because some scrapers like pedaily/cyzone
        # use datetime.now() and would generate false duplicates on each run)
        cursor.execute(
            """
            SELECT id FROM funding_events
            WHERE company_name = ? AND round_type = ? AND source = ?
            """,
            (event.company_name, event.round_type, event.source),
        )
        if cursor.fetchone():
            return False

        cursor.execute(
            """
            INSERT INTO funding_events
            (id, company_name, company_domain, round_type, amount_cny,
             announcement_date, investors, source_url, source, industry_group, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.company_name,
                event.company_domain,
                event.round_type,
                event.amount_cny,
                event.announcement_date.isoformat(),
                event.investors,
                event.source_url,
                event.source,
                event.industry_group,
                event.created_at.isoformat(),
            ),
        )
        return True


def get_recent_fundings(days: int = 7) -> list[FundingEvent]:
    """Get funding events from the last N days."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM funding_events
            WHERE datetime(announcement_date) >= datetime('now', ?)
            ORDER BY announcement_date DESC
            """,
            (f"-{days} days",),
        )
        rows = cursor.fetchall()
        return [_row_to_funding_event(row) for row in rows]


def get_funding_by_id(event_id: str) -> Optional[FundingEvent]:
    """Get a funding event by ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM funding_events WHERE id = ?", (event_id,))
        row = cursor.fetchone()
        if row:
            return _row_to_funding_event(row)
        return None


def _row_to_funding_event(row: sqlite3.Row) -> FundingEvent:
    """Convert a database row to a FundingEvent object."""
    return FundingEvent(
        id=row["id"],
        company_name=row["company_name"],
        company_domain=row["company_domain"] if "company_domain" in row.keys() else "",
        round_type=row["round_type"],
        amount_cny=row["amount_cny"],
        announcement_date=datetime.fromisoformat(row["announcement_date"]),
        investors=row["investors"] if "investors" in row.keys() else "",
        source_url=row["source_url"] if "source_url" in row.keys() else "",
        source=row["source"],
        industry_group=row["industry_group"] if "industry_group" in row.keys() else "",
        created_at=datetime.fromisoformat(row["created_at"]) if "created_at" in row.keys() else datetime.now(),
    )


def insert_opportunity(opp: Opportunity) -> bool:
    """
    Insert an opportunity. Returns True if inserted, False if already exists.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Check for duplicate
        cursor.execute(
            "SELECT id FROM opportunities WHERE company_name = ? AND funding_event_id = ?",
            (opp.company_name, opp.funding_event_id),
        )
        if cursor.fetchone():
            return False

        cursor.execute(
            """
            INSERT INTO opportunities
            (id, company_name, funding_event_id, signal_strength,
             window_days_remaining, recommended_action, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                opp.id,
                opp.company_name,
                opp.funding_event_id,
                opp.signal_strength,
                opp.window_days_remaining,
                opp.recommended_action,
                opp.status,
                opp.created_at.isoformat(),
            ),
        )
        return True


def get_pending_opportunities() -> list[Opportunity]:
    """Get opportunities with status 'new'."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM opportunities WHERE status = 'new' ORDER BY created_at DESC"
        )
        rows = cursor.fetchall()
        return [_row_to_opportunity(row) for row in rows]


def update_opportunity_status(opp_id: str, status: str) -> None:
    """Update the status of an opportunity."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE opportunities SET status = ? WHERE id = ?", (status, opp_id)
        )


def _row_to_opportunity(row: sqlite3.Row) -> Opportunity:
    """Convert a database row to an Opportunity object."""
    return Opportunity(
        id=row["id"],
        company_name=row["company_name"],
        funding_event_id=row["funding_event_id"],
        signal_strength=row["signal_strength"],
        window_days_remaining=row["window_days_remaining"],
        recommended_action=row["recommended_action"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def insert_job_posting(job: JobPosting) -> bool:
    """Insert a job posting. Returns True if inserted, False if already exists."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Check for duplicate
        cursor.execute(
            "SELECT id FROM job_postings WHERE company_name = ? AND job_title = ?",
            (job.company_name, job.job_title),
        )
        if cursor.fetchone():
            return False
        
        cursor.execute(
            """
            INSERT INTO job_postings
            (id, company_name, job_title, job_count, posting_date, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.company_name,
                job.job_title,
                job.job_count,
                job.posting_date.isoformat(),
                job.source,
                job.created_at.isoformat(),
            ),
        )
        return True


def get_all_funding_events() -> list[FundingEvent]:
    """Get all funding events ordered by date descending."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM funding_events ORDER BY announcement_date DESC"
        )
        rows = cursor.fetchall()
        return [_row_to_funding_event(row) for row in rows]
