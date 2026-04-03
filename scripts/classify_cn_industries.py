#!/usr/bin/env python3
"""Fill industry_group for CN funding events.

Usage:
    python scripts/classify_cn_industries.py [--dry-run]

This script:
1. Reads all CN funding events with empty industry_group
2. Classifies each using the cn_industry_classifier module
3. Updates the database with the classified industry_group
"""

import argparse
import sqlite3
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.cn_industry_classifier import classify_industry


def resolve_db_path() -> Path:
    """Resolve database path relative to project root."""
    config_path = project_root / "config.yaml"
    if config_path.exists():
        import yaml
        with open(config_path) as f:
            config = yaml.safe_load(f)
        db_path = project_root / config.get("database_path", "data/fund_job_radar.db")
    else:
        db_path = project_root / "data/fund_job_radar.db"
    return db_path.resolve()


def classify_and_update(dry_run: bool = True) -> None:
    """Classify all unclassified CN funding events and update the database."""
    db_path = resolve_db_path()
    
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Get all CN events with empty industry_group
    cur.execute(
        "SELECT id, company_name, industry_group FROM funding_events WHERE source='cn'"
    )
    rows = cur.fetchall()
    
    print(f"Found {len(rows)} CN funding events")
    print("-" * 80)
    
    updated = 0
    already_filled = 0
    unknown = []
    
    for row_id, company_name, industry_group in rows:
        # Check if already filled (non-empty)
        if industry_group and industry_group.strip():
            already_filled += 1
            print(f"  [SKIP] {company_name} → already set: '{industry_group}'")
            continue
        
        # Classify
        industry = classify_industry(company_name)
        
        if industry:
            print(f"  [CLASSIFY] {company_name} → {industry}")
            if not dry_run:
                cur.execute(
                    "UPDATE funding_events SET industry_group=? WHERE id=?",
                    (industry, row_id)
                )
            updated += 1
        else:
            print(f"  [UNKNOWN] {company_name} → no match")
            unknown.append((row_id, company_name))
    
    print("-" * 80)
    print(f"Summary:")
    print(f"  Already filled: {already_filled}")
    print(f"  Newly classified: {updated}")
    print(f"  Unknown (no match): {len(unknown)}")
    
    if unknown:
        print(f"\nUnknown companies (need manual classification or web search):")
        for _, name in unknown:
            print(f"  - {name}")
    
    if not dry_run:
        conn.commit()
        print(f"\n✅ Database updated (mode=write, {updated} records)")
    else:
        print(f"\n[DRY RUN] No changes written. Re-run without --dry-run to write.")
    
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify CN funding event industries")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Show what would be done without writing to DB (default: True)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Actually write changes to database (default: dry-run)",
    )
    args = parser.parse_args()
    
    dry_run = not args.write
    classify_and_update(dry_run=dry_run)


if __name__ == "__main__":
    main()
