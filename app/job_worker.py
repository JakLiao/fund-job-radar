"""Standalone worker for job postings fetching.

Runs as its own PM2 process so the multi-hour crawl never occupies the
APScheduler thread pool shared with the funding-event fetch jobs.
"""

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("job-worker")

# Only fetch jobs for significant fundings, matching the original threshold.
MIN_AMOUNT_CNY = 500000


def select_batch(items: list, offset: int, limit: int) -> list:
    """Return a slice of items without triggering negative-index wraparound.

    Args:
        items: Full list to slice.
        offset: Start index, may exceed len(items).
        limit: Maximum number of items to return.

    Returns:
        The requested slice, or an empty list if offset is out of range.
    """
    if offset >= len(items):
        return []
    return items[offset:offset + limit]


def collect_target_companies(fundings: list) -> list:
    """Build a de-duplicated company list from funding events.

    Companies at or above MIN_AMOUNT_CNY qualify; the first occurrence wins so
    the earliest recorded domain is preserved.

    Args:
        fundings: FundingEvent records.

    Returns:
        List of (company_name, company_domain) tuples.
    """
    companies = {}
    for f in fundings:
        if f.amount_cny < MIN_AMOUNT_CNY:
            continue
        if f.company_name not in companies:
            companies[f.company_name] = f.company_domain
    return list(companies.items())


def run_batch(offset: int, limit: int) -> int:
    """Fetch one batch of companies and insert their job postings.

    Args:
        offset: Index into the target company list to start from.
        limit: Maximum number of companies to process.

    Returns:
        Number of newly inserted job postings.
    """
    from .database import get_all_funding_events, insert_job_posting
    from .scrapers.jobs import fetch_company_jobs

    fundings = get_all_funding_events()
    if not fundings:
        logger.info("No funding events found, skipping")
        return 0

    targets = collect_target_companies(fundings)
    batch = select_batch(targets, offset, limit)
    logger.info(
        "Batch offset=%d size=%d of %d target companies",
        offset, len(batch), len(targets),
    )

    inserted = 0
    for idx, (company_name, company_domain) in enumerate(batch, start=1):
        try:
            postings = fetch_company_jobs(company_name, company_domain)
        except Exception as e:
            logger.warning("jobs fetch failed for %s: %s", company_name, e)
            continue

        for posting in postings:
            if insert_job_posting(posting):
                inserted += 1

        if idx % 10 == 0:
            logger.info("Progress: %d/%d companies processed", idx, len(batch))

    logger.info("Batch done, inserted %d new job postings", inserted)
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch job postings in batches")
    parser.add_argument("--offset", type=int, required=True)
    parser.add_argument("--limit", type=int, required=True)
    args = parser.parse_args()

    run_batch(args.offset, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
