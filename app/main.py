"""Main entry point for Fund Job Radar scheduler."""

import logging
import sys
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from .config import get_config
from .database import init_db
from .scrapers.techcrunch import fetch_techcrunch_fundings
from .scrapers.edgar import fetch_edgar_filings
from .scrapers.crunchbase import fetch_crunchbase_fundings
from .scrapers.cn_funding import fetch_cn_fundings
from .scrapers.jobs import fetch_job_postings
from .analyzer import process_new_fundings
from .notifier import push_daily_summary, push_pending_notifications

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("fund-job-radar")


def _fetch_and_insert(scraper_func, source_name: str, **scraper_kwargs) -> int:
    """
    Common pattern: call scraper, insert each event into DB.
    Returns number of newly inserted events.
    """
    import requests as _req
    try:
        events = scraper_func(**scraper_kwargs)
        logger.info(f"Fetched {len(events)} funding events from {source_name}")
    except _req.RequestException as e:
        logger.error(f"[{source_name}] Network error during fetch: {e}")
        return 0
    except (ValueError, KeyError, AttributeError) as e:
        logger.error(f"[{source_name}] Parse error during fetch: {e}", exc_info=True)
        return 0

    from .database import insert_funding_event
    new_count = 0
    for event in events:
        if insert_funding_event(event):
            new_count += 1
    logger.info(f"Inserted {new_count} new {source_name} funding events")
    return new_count


def job_fetch_techcrunch():
    """Job: Fetch and process TechCrunch RSS feed."""
    logger.info("=== Starting TechCrunch fetch job ===")
    try:
        new_count = _fetch_and_insert(fetch_techcrunch_fundings, "TechCrunch", limit=50)
        if new_count > 0:
            opportunities = process_new_fundings()
            logger.info(f"Generated {len(opportunities)} new opportunities")
            if opportunities:
                sent = push_pending_notifications()
                logger.info(f"Sent {sent} notifications")
    except Exception as e:
        logger.error(f"TechCrunch fetch job failed: {e}", exc_info=True)


def job_fetch_edgar():
    """Job: Fetch SEC EDGAR Form D filings."""
    config = get_config()
    logger.info("=== Starting EDGAR Form D fetch job ===")
    try:
        from .scrapers.edgar import fetch_edgar_filings_simple
        new_count = _fetch_and_insert(
            fetch_edgar_filings_simple, "EDGAR",
            days=config.edgar_days_lookback, min_amount=config.edgar_min_amount,
        )
        logger.info(f"EDGAR returned {new_count} new events")
    except Exception as e:
        logger.error(f"EDGAR fetch job failed: {e}", exc_info=True)


def job_fetch_crunchbase():
    """Job: Fetch Crunchbase API data (Phase 2 - placeholder)."""
    logger.info("=== Crunchbase job (Phase 2 - not implemented yet) ===")
    config = get_config()
    if not config.crunchbase_key:
        logger.info("Crunchbase key not configured, skipping")
        return
    try:
        events = fetch_crunchbase_fundings(config.crunchbase_key)
        logger.info(f"Crunchbase returned {len(events)} events (Phase 2)")
    except Exception as e:
        logger.error(f"Crunchbase fetch job failed: {e}", exc_info=True)


def job_fetch_cn_funding():
    """Job: Fetch funding events from Chinese sources (36kr, etc.)."""
    logger.info("=== Starting CN funding fetch job ===")
    try:
        new_count = _fetch_and_insert(fetch_cn_fundings, "CN Funding", limit=50)
        if new_count > 0:
            opportunities = process_new_fundings()
            logger.info(f"Generated {len(opportunities)} new opportunities")
    except Exception as e:
        logger.error(f"CN funding fetch job failed: {e}", exc_info=True)


def job_fetch_jobs():
    """Job: Fetch job postings for funded companies."""
    logger.info("=== Starting job postings fetch job ===")
    try:
        from .database import get_all_funding_events
        from .scrapers.jobs import fetch_company_jobs
        
        # Get all funding events to find company names
        fundings = get_all_funding_events()
        
        if not fundings:
            logger.info("No funding events found, skipping job fetch")
            return
        
        # Get unique company names from recent fundings (preserve domain info)
        recent_companies = {}  # name -> domain
        for f in fundings:
            if f.amount_cny >= 500000:  # Only fetch jobs for significant fundings
                if f.company_name not in recent_companies:
                    recent_companies[f.company_name] = f.company_domain
        
        logger.info(f"Fetching job postings for {len(recent_companies)} companies")
        
        # Fetch jobs for each company
        new_count = 0
        from .database import insert_job_posting
        for company_name, company_domain in recent_companies.items():
            try:
                jobs = fetch_company_jobs(company_name, company_domain)
                for job in jobs:
                    if insert_job_posting(job):
                        new_count += 1
            except Exception as e:
                logger.warning(f"Failed to fetch jobs for {company_name}: {e}")
        
        logger.info(f"Inserted {new_count} new job postings")
        
    except Exception as e:
        logger.error(f"Job postings fetch job failed: {e}", exc_info=True)


def job_fetch_company_careers():
    """Job: Fetch careers pages for funded companies using Playwright."""
    logger.info("=== Starting company careers page fetch (Playwright) ===")
    try:
        from .database import get_all_funding_events
        from .scrapers.jobs import _fetch_company_careers_page
        
        fundings = get_all_funding_events()
        if not fundings:
            logger.info("No funding events found, skipping careers fetch")
            return
        
        # Get companies with domains from recent fundings
        companies_with_domains = {}
        for f in fundings:
            if f.amount_cny >= 500000 and f.company_domain:
                if f.company_name not in companies_with_domains:
                    companies_with_domains[f.company_name] = f.company_domain
        
        logger.info(f"Fetching careers pages for {len(companies_with_domains)} companies with known domains")
        
        new_count = 0
        from .database import insert_job_posting
        for company_name, company_domain in companies_with_domains.items():
            try:
                postings = _fetch_company_careers_page(company_name, company_domain)
                for job in postings:
                    if insert_job_posting(job):
                        new_count += 1
            except Exception as e:
                logger.warning(f"Failed to fetch careers for {company_name}: {e}")
        
        logger.info(f"Inserted {new_count} new job postings from careers pages")
        
    except Exception as e:
        logger.error(f"Company careers fetch job failed: {e}", exc_info=True)


def job_daily_summary():
    """Job: Send daily summary notification."""
    logger.info("=== Starting daily summary job ===")
    try:
        # First process any new fundings to ensure we have latest opportunities
        opportunities = process_new_fundings()
        logger.info(f"Processed {len(opportunities)} new opportunities")
        
        # Push daily summary
        success = push_daily_summary()
        if success:
            logger.info("Daily summary sent successfully")
        else:
            logger.warning("Daily summary failed or skipped")
    except Exception as e:
        logger.error(f"Daily summary job failed: {e}", exc_info=True)


def main():
    """Main entry point."""
    logger.info("=" * 50)
    logger.info("Fund Job Radar starting...")
    logger.info(f"Time: {datetime.now().isoformat()}")
    logger.info("=" * 50)
    
    # Initialize database
    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        sys.exit(1)
    
    # Get config
    config = get_config()
    
    # Create scheduler
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai", misfire_grace_time=300)
    
    # TechCrunch fetch job - every N minutes (default 30)
    scheduler.add_job(
        job_fetch_techcrunch,
        trigger=IntervalTrigger(minutes=config.techcrunch_interval),
        id="fetch_techcrunch",
        name="TechCrunch RSS Fetch",
        replace_existing=True,
        misfire_grace_time=60,
        coalesce=True,
        max_instances=1,
    )
    
    # EDGAR fetch job - every N hours (default 6 hours)
    scheduler.add_job(
        job_fetch_edgar,
        trigger=IntervalTrigger(hours=config.edgar_interval_hours),
        id="fetch_edgar",
        name="SEC EDGAR Fetch",
        replace_existing=True,
        misfire_grace_time=300,
        coalesce=True,
        max_instances=1,
    )
    
    # Crunchbase fetch job - every N minutes (Phase 2, default 60)
    scheduler.add_job(
        job_fetch_crunchbase,
        trigger=IntervalTrigger(minutes=config.crunchbase_interval),
        id="fetch_crunchbase",
        name="Crunchbase API Fetch",
        replace_existing=True,
        misfire_grace_time=120,
        coalesce=True,
        max_instances=1,
    )
    
    # CN funding fetch job - every 30 minutes
    scheduler.add_job(
        job_fetch_cn_funding,
        trigger=IntervalTrigger(minutes=30),
        id="fetch_cn_funding",
        name="CN Funding RSS Fetch (36kr)",
        replace_existing=True,
        misfire_grace_time=300,
        coalesce=True,
        max_instances=1,
    )
    
    # Job postings fetch - every 6 hours (Phase 2)
    scheduler.add_job(
        job_fetch_jobs,
        trigger=IntervalTrigger(hours=6),
        id="fetch_jobs",
        name="Job Postings Fetch",
        replace_existing=True,
        misfire_grace_time=300,
        coalesce=True,
        max_instances=1,
    )
    
    # Company careers pages - Playwright fetch every 12 hours
    scheduler.add_job(
        job_fetch_company_careers,
        trigger=IntervalTrigger(hours=12),
        id="fetch_company_careers",
        name="Company Careers Pages (Playwright)",
        replace_existing=True,
        misfire_grace_time=600,
        coalesce=True,
        max_instances=1,
    )
    
    # Daily summary - at configured times (default 09:00)
    for push_time in config.push_times:
        try:
            hour, minute = map(int, push_time.split(":"))
            scheduler.add_job(
                job_daily_summary,
                trigger=CronTrigger(hour=hour, minute=minute, timezone="Asia/Shanghai"),
                id=f"daily_summary_{push_time}",
                name=f"Daily Summary {push_time}",
                replace_existing=True,
                misfire_grace_time=300,
                coalesce=True,
                max_instances=1,
            )
            logger.info(f"Scheduled daily summary at {push_time}")
        except ValueError:
            logger.warning(f"Invalid push time format: {push_time}")
    
    # Start scheduler
    scheduler.start()
    logger.info("Scheduler started")
    
    # Run TechCrunch fetch immediately on startup
    logger.info("Running initial TechCrunch fetch...")
    job_fetch_techcrunch()
    
    # Run EDGAR fetch immediately on startup (if enabled)
    if config.edgar_enabled:
        logger.info("Running initial EDGAR fetch...")
        job_fetch_edgar()
    
    # Run CN funding fetch immediately on startup
    logger.info("Running initial CN funding fetch...")
    job_fetch_cn_funding()
    
    # Keep the main thread alive
    logger.info("Fund Job Radar is running. Press Ctrl+C to stop.")
    try:
        import time
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        scheduler.shutdown(wait=False)
        logger.info("Stopped.")


if __name__ == "__main__":
    main()
