"""Hook registry + plugin folder / entry-point loader."""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Iterable

from src.analysis_hooks.base import AnalysisHook, NoOpHook

logger = logging.getLogger("x_pr_monitor.hooks")

_HOOKS: list[AnalysisHook] = [NoOpHook()]


def register_hook(hook: AnalysisHook, *, replace_noop: bool = True) -> None:
    global _HOOKS
    if replace_noop and len(_HOOKS) == 1 and isinstance(_HOOKS[0], NoOpHook):
        _HOOKS = [hook]
    else:
        # Avoid duplicate names
        _HOOKS = [h for h in _HOOKS if getattr(h, "name", None) != getattr(hook, "name", None)]
        _HOOKS.append(hook)


def get_hooks() -> list[AnalysisHook]:
    return list(_HOOKS)


def load_plugins(plugins_dir: Path | None = None) -> list[str]:
    """Import modules under src/analysis_hooks/plugins/ so they can register themselves.

    Also attempts entry points group ``x_pr_monitor.analysis_hooks`` if present.
    """
    loaded: list[str] = []
    base = plugins_dir or Path(__file__).resolve().parent / "plugins"
    if base.is_dir():
        package = "src.analysis_hooks.plugins"
        try:
            importlib.import_module(package)
        except ImportError:
            # Ensure namespace
            pass
        for mod in pkgutil.iter_modules([str(base)]):
            if mod.name.startswith("_"):
                continue
            name = f"{package}.{mod.name}"
            try:
                importlib.import_module(name)
                loaded.append(name)
            except Exception:
                logger.exception("Failed loading plugin %s", name)

    # Optional setuptools entry points
    try:
        from importlib.metadata import entry_points

        eps = entry_points()
        group: Iterable = []
        if hasattr(eps, "select"):
            group = eps.select(group="x_pr_monitor.analysis_hooks")
        else:  # pragma: no cover — older API
            group = eps.get("x_pr_monitor.analysis_hooks", [])  # type: ignore[index]
        for ep in group:
            try:
                obj = ep.load()
                if callable(obj) and not isinstance(obj, type):
                    hook = obj()
                else:
                    hook = obj() if isinstance(obj, type) else obj
                register_hook(hook)
                loaded.append(f"entrypoint:{ep.name}")
            except Exception:
                logger.exception("Failed loading entry point %s", ep.name)
    except Exception:
        pass

    return loaded
