"""
Twice-daily ticker refresh scheduler (America/New_York).

ONLY scheduled job in this project:
  08:12 and 16:12 ET (configurable) → pull Trade Plan sheet Ticker column
  → update local cache → rebuild/update Filtered Stream rules.

This does NOT detect posts. Post detection is X Filtered Stream Webhooks only.
Monitoring consumes zero inference tokens; detection is X→webhook push only.
"""

from __future__ import annotations

import logging
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import SHEET_REFRESH_CRON, SHEET_REFRESH_TIMES
from src.rules_sync import sync_rules_to_x
from src.sheet_sync import sync_from_sheet

logger = logging.getLogger("x_pr_monitor.scheduler")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

TZ = "America/New_York"


def refresh_job() -> None:
    """Sheet → tickers → stream rules. Never polls tweets. Never calls an LLM."""
    logger.info("Starting scheduled ticker/rules refresh (filter maintenance only)")
    try:
        sheet_summary = sync_from_sheet()
        logger.info("Sheet sync: %s", sheet_summary)
    except Exception:
        logger.exception(
            "Sheet sync failed — keeping existing ticker cache; will still attempt rules sync"
        )
        sheet_summary = {"error": True}
    try:
        rules_summary = sync_rules_to_x(dry_run=False)
        logger.info("Rules sync: %s", {k: rules_summary[k] for k in rules_summary if k != "x_result"})
    except Exception:
        logger.exception("Rules sync failed")
        raise
    logger.info("Refresh complete (sheet=%s)", sheet_summary.get("count", sheet_summary))


def _parse_times(raw: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        hh, mm = part.split(":")
        out.append((int(hh), int(mm)))
    return out


def main() -> int:
    sched = BlockingScheduler(timezone=TZ)
    if SHEET_REFRESH_CRON:
        # Cron: min hour day month dow — user may pass "12 8,16 * * *"
        parts = SHEET_REFRESH_CRON.split()
        if len(parts) != 5:
            logger.error("SHEET_REFRESH_CRON must have 5 fields: %r", SHEET_REFRESH_CRON)
            return 2
        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
            timezone=TZ,
        )
        sched.add_job(refresh_job, trigger, id="sheet_refresh")
        logger.info("Scheduled cron %s (%s)", SHEET_REFRESH_CRON, TZ)
    else:
        times = _parse_times(SHEET_REFRESH_TIMES)
        if not times:
            times = [(8, 12), (16, 12)]
        for i, (h, m) in enumerate(times):
            sched.add_job(
                refresh_job,
                CronTrigger(hour=h, minute=m, timezone=TZ),
                id=f"sheet_refresh_{i}",
            )
            logger.info("Scheduled refresh at %02d:%02d %s", h, m, TZ)

    logger.info(
        "Scheduler running. Post detection remains webhook-only "
        "(zero inference tokens; X→webhook push)."
    )
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
