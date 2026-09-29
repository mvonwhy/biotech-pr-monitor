"""Alert pipeline: original filter (done upstream) → PR URL resolve → analysis hooks → store.

Monitoring consumes zero inference tokens; detection is X→webhook push only.
LLM analysis hooks are opt-in via ALLOW_INFERENCE_HOOKS=1.
"""

from __future__ import annotations

import logging
from typing import Any

from src.alerts import STORE
from src.analysis_hooks import get_hooks, load_plugins, run_hooks
from src.pr_resolve import resolve_press_release
from src import source_race

logger = logging.getLogger("x_pr_monitor.pipeline")

_plugins_loaded = False


def ensure_plugins() -> None:
    global _plugins_loaded
    if not _plugins_loaded:
        loaded = load_plugins()
        if loaded:
            logger.info("Loaded analysis plugins: %s", loaded)
        _plugins_loaded = True


def process_alert(alert: dict[str, Any]) -> dict[str, Any]:
    """Resolve PR link, run hooks, append to alert store. Returns stored record."""
    ensure_plugins()
    enriched = resolve_press_release(dict(alert))
    enriched = run_hooks(enriched, get_hooks())
    stored = STORE.append(enriched)
    # After PR resolve (URL when possible) + store (received_at set) → race stats
    source_race.record(stored)
    return stored


def process_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [process_alert(e) for e in events]
