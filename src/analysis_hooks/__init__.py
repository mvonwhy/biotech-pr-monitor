"""Pluggable analysis hooks.

Core monitoring path consumes ZERO inference tokens.
Hooks that call LLMs must be opt-in (disabled by default) and registered explicitly.
"""

from __future__ import annotations

from src.analysis_hooks.base import AnalysisHook, Alert, NoOpHook, run_hooks
from src.analysis_hooks.registry import get_hooks, load_plugins, register_hook

__all__ = [
    "Alert",
    "AnalysisHook",
    "NoOpHook",
    "get_hooks",
    "load_plugins",
    "register_hook",
    "run_hooks",
]
